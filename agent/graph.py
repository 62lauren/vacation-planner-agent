import json
import os
from pathlib import Path
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import interrupt

from agent.state import VacationState
from agent.prompts import SYSTEM_PROMPT, build_user_message
from tools.calendar_writer import create_trip_events

_ROOT = Path(__file__).parent.parent

MCP_CONFIG = {
    "google_calendar": {
        "command": "python3",
        "args": [str(_ROOT / "mcp_servers" / "google_calendar_server.py")],
        "transport": "stdio",
    },
    "google_maps": {
        "command": "python3",
        "args": [str(_ROOT / "mcp_servers" / "google_maps_server.py")],
        "transport": "stdio",
    },
    "tripadvisor": {
        "command": "python3",
        "args": [str(_ROOT / "mcp_servers" / "tripadvisor_server.py")],
        "transport": "stdio",
    },
}


async def build_graph(tools: list[BaseTool]):

    llm = ChatAnthropic(model="claude-sonnet-4-6").bind_tools(tools)
    llm_final = ChatAnthropic(model="claude-sonnet-4-6")  # no tools — forces plan output

    def plan_node(state: VacationState):
        msgs = list(state["messages"])
        tool_rounds = state.get("tool_rounds", 0)

        if not msgs or not any(isinstance(m, SystemMessage) for m in msgs):
            user_msg = build_user_message(
                state["user_prompt"],
                state.get("revision_feedback"),
            )
            msgs = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_msg)]

        if tool_rounds >= 2:
            msgs = msgs + [HumanMessage(content="Research complete. Output ONLY the raw JSON object — no markdown, no code fences, no explanation. Start your response with { and end with }.")]
            response = llm_final.invoke(msgs)
        else:
            response = llm.invoke(msgs)

        plan_json = state.get("plan_json")
        new_tool_rounds = tool_rounds

        if response.tool_calls:
            new_tool_rounds = tool_rounds + 1
        else:
            # content can be a string or a list of blocks (Anthropic returns either)
            if isinstance(response.content, str):
                text = response.content
            elif isinstance(response.content, list):
                text = " ".join(
                    (b.get("text", "") if isinstance(b, dict) else getattr(b, "text", ""))
                    for b in response.content
                    if (isinstance(b, dict) and b.get("type") == "text") or hasattr(b, "text")
                )
            else:
                text = ""

            try:
                start = text.find("{")
                end = text.rfind("}") + 1
                if start != -1 and end > start:
                    plan_json = json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

        return {
            "messages": [response],
            "plan_json": plan_json,
            "tool_rounds": new_tool_rounds,
            "revision_feedback": None,  # clear so approve_node re-interrupts after revision
        }

    def approve_node(state: VacationState):
        # Only interrupt when plan hasn't been decided yet
        if not state.get("plan_approved") and state.get("revision_feedback") is None:
            interrupt({"plan": state["plan_json"]})

    def create_events_node(state: VacationState):
        plan = state["plan_json"]
        event_ids = create_trip_events(plan)
        return {"calendar_event_ids": event_ids}

    def route_after_approve(state: VacationState):
        if state.get("plan_approved"):
            return "create_events"
        # Reset messages for revision so plan_node rebuilds with feedback
        return "plan"

    builder = StateGraph(VacationState)
    builder.add_node("plan", plan_node)
    builder.add_node("tools", ToolNode(tools))
    builder.add_node("approve", approve_node)
    builder.add_node("create_events", create_events_node)

    builder.add_edge(START, "plan")
    builder.add_conditional_edges("plan", tools_condition, {"tools": "tools", END: "approve"})
    builder.add_edge("tools", "plan")
    builder.add_conditional_edges("approve", route_after_approve, {
        "create_events": "create_events",
        "plan": "plan",
    })
    builder.add_edge("create_events", END)

    return builder.compile(
        checkpointer=MemorySaver(),
    )
