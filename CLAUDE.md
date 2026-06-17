# Vacation Planner Agent
A travel planning assistant that builds day-by-day itineraries from a natural language prompt, presents the plan for approval, and adds confirmed trips to Google Calendar.

## Stack
- **Agent framework:** LangGraph (custom graph with MemorySaver checkpointing)
- **LLM:** Claude claude-sonnet-4-6 via langchain-anthropic
- **MCP servers:** Google Maps, TripAdvisor, Google Calendar (stdio, bridged via langchain-mcp-adapters)
- **Backend:** FastAPI with SSE streaming
- **Frontend:** Vanilla JS + SSE (no build step)

## Project Structure
```
vacation-planner-agent/
├── CLAUDE.md
├── .env                        ← API keys (not committed)
├── .env.example
├── requirements.txt
├── main.py                     ← FastAPI app, SSE endpoints, OAuth flow
├── agent/
│   ├── graph.py                ← LangGraph graph definition
│   ├── prompts.py              ← system prompt + tool call rules
│   └── state.py                ← VacationState TypedDict
├── mcp_servers/
│   ├── google_maps_server.py   ← search_places, get_travel_distances
│   ├── tripadvisor_server.py   ← search_tripadvisor_locations, get_reviews
│   └── google_calendar_server.py ← find_free_windows
├── tools/
│   ├── calendar_writer.py      ← creates Google Calendar events from approved plan
│   └── oauth.py                ← Google OAuth helpers
└── static/                     ← index.html, style.css, app.js
```

## Setup
```bash
pip install -r requirements.txt
# Add all keys to .env (see .env.example)
# Complete Google OAuth at http://localhost:8000/api/auth/start
uvicorn main:app --reload
```
Then open `http://localhost:8000`.

## Environment Variables
| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Claude API |
| `GOOGLE_MAPS_API_KEY` | Places + Distance Matrix |
| `TRIPADVISOR_API_KEY` | Attractions + reviews |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth for Google Calendar |

## Tools
- **`search_places`** — Google Maps nearby search; use only for `tourist_attraction` type, top 2 cities max
- **`get_travel_distances`** — Distance Matrix between city-to-city legs only
- **`find_free_windows`** — reads the user's Google Calendar for available date ranges
- **`search_tripadvisor_locations`** — attractions/restaurants at a destination; **call at most once per run** (rate-limited free tier)
- **`get_reviews`** — TripAdvisor reviews for a location ID; at most 2 locations per run

The agent has **no flight search API and no hotel booking API**. Flights and hotels must come from model knowledge.

## Tool Call Budget
The system prompt enforces a hard 2-round limit on tool calls, with all calls in a round issued in parallel. `graph.py` tracks this via a `tool_rounds` counter and switches to a tools-free LLM after round 2 to force JSON output. Do not loosen this — TripAdvisor's free tier rate-limits quickly.

## Approval Flow
After the plan is generated, the graph pauses at `approve_node` via `interrupt()` and streams the plan JSON to the frontend. The user approves or requests a revision:
- **Approve** → events are written to Google Calendar
- **Revise** → feedback is passed back into the planning prompt and a new plan is generated

`interrupt_before=["approve"]` must **not** be added to `builder.compile()` — it fires before the node runs, which prevents `interrupt()` from ever executing and the plan never reaches the frontend.
