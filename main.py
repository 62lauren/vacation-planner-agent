import asyncio
import json
import uuid
from contextlib import asynccontextmanager, AsyncExitStack
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from agent.graph import build_graph, MCP_CONFIG
from tools.oauth import build_auth_flow, exchange_code, load_credentials

load_dotenv()

_graph = None
_oauth_flows: dict[str, object] = {}  # state_token -> Flow

REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:8000/api/auth/callback")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph
    mcp_client = MultiServerMCPClient(MCP_CONFIG)
    async with AsyncExitStack() as stack:
        all_tools = []
        for server_name in MCP_CONFIG:
            session = await stack.enter_async_context(mcp_client.session(server_name))
            server_tools = await load_mcp_tools(session)
            all_tools.extend(server_tools)
        _graph = await build_graph(all_tools)
        yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/api/auth/status")
def auth_status():
    creds = load_credentials()
    return {"authenticated": creds is not None}


@app.get("/api/auth/start")
def auth_start():
    flow = build_auth_flow(redirect_uri=REDIRECT_URI)
    auth_url, state = flow.authorization_url(prompt="consent", access_type="offline")
    _oauth_flows[state] = flow
    return RedirectResponse(auth_url)


@app.get("/api/auth/callback")
def auth_callback(code: str, state: str):
    flow = _oauth_flows.pop(state, None)
    if not flow:
        return {"error": "Invalid OAuth state. Try /api/auth/start again."}
    exchange_code(flow, code)
    return RedirectResponse("/?auth=success")


# ── Planning ──────────────────────────────────────────────────────────────────

class PlanRequest(BaseModel):
    prompt: str


class ApproveRequest(BaseModel):
    thread_id: str
    decision: str        # "approve" or "revise"
    feedback: str | None = None


@app.post("/api/plan")
async def start_plan(req: PlanRequest):
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 20}

    initial_state = {
        "user_prompt": req.prompt,
        "messages": [],
        "revision_feedback": None,
        "plan_json": None,
        "plan_approved": False,
        "calendar_event_ids": [],
        "tool_rounds": 0,
    }

    async def event_stream():
        yield {"event": "thread", "data": thread_id}
        plan_sent = False
        try:
            async for event in _graph.astream_events(initial_state, config=config, version="v2"):
                kind = event["event"]

                if kind == "on_tool_start":
                    yield {"event": "progress", "data": json.dumps({"tool": event["name"]})}

                elif kind == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    if chunk and hasattr(chunk, "content") and isinstance(chunk.content, str):
                        yield {"event": "thinking", "data": json.dumps({"text": chunk.content})}

                elif kind == "on_interrupt":
                    interrupt_value = event["data"].get("value", {})
                    plan = interrupt_value.get("plan") if isinstance(interrupt_value, dict) else None
                    if plan is not None:
                        plan_sent = True
                        yield {"event": "plan", "data": json.dumps(plan)}

        except Exception as e:
            yield {"event": "error", "data": json.dumps({"message": str(e)})}

        # Fallback: on_interrupt may not surface in astream_events in all LangGraph versions.
        # After the stream ends the graph is paused and state is checkpointed, so read it directly.
        if not plan_sent:
            try:
                snapshot = await _graph.aget_state(config)
                plan = snapshot.values.get("plan_json")
                if plan:
                    yield {"event": "plan", "data": json.dumps(plan)}
                else:
                    yield {"event": "error", "data": json.dumps({"message": "Plan generation failed — the model did not return valid JSON. Please try again."})}
            except Exception as e:
                yield {"event": "error", "data": json.dumps({"message": str(e)})}

    return EventSourceResponse(event_stream())


@app.post("/api/approve")
async def resume_plan(req: ApproveRequest):
    config = {"configurable": {"thread_id": req.thread_id}}

    update = {
        "plan_approved": req.decision == "approve",
        "revision_feedback": req.feedback if req.decision == "revise" else None,
    }
    # Clear messages and reset round counter on revision so plan_node rebuilds fresh
    if req.decision == "revise":
        update["messages"] = []
        update["tool_rounds"] = 0

    await _graph.aupdate_state(config, update)

    async def event_stream():
        try:
            async for event in _graph.astream_events(None, config=config, version="v2"):
                kind = event["event"]

                if kind == "on_tool_start":
                    yield {"event": "progress", "data": json.dumps({"tool": event["name"]})}

                elif kind == "on_interrupt":
                    interrupt_value = event["data"].get("value", {})
                    plan = interrupt_value.get("plan") if isinstance(interrupt_value, dict) else None
                    if plan is not None:
                        yield {"event": "plan", "data": json.dumps(plan)}
                    else:
                        yield {"event": "error", "data": json.dumps({"message": "Plan generation failed — the model did not return valid JSON. Please try again."})}

                elif kind == "on_chain_end" and event.get("name") == "create_events":
                    output = event["data"].get("output", {})
                    event_ids = output.get("calendar_event_ids", [])
                    yield {"event": "done", "data": json.dumps({"event_count": len(event_ids)})}

        except Exception as e:
            yield {"event": "error", "data": json.dumps({"message": str(e)})}

    return EventSourceResponse(event_stream())


# ── Serve frontend ─────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return RedirectResponse("/static/index.html")
