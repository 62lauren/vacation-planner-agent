from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages


class VacationState(TypedDict):
    messages: Annotated[list, add_messages]
    user_prompt: str
    revision_feedback: str | None
    plan_json: dict | None
    plan_approved: bool
    calendar_event_ids: list[str]
    tool_rounds: int
