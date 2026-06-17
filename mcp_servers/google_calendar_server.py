#!/usr/bin/env python3
"""MCP server exposing Google Calendar read tools."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta
from mcp.server.fastmcp import FastMCP
from googleapiclient.discovery import build
from tools.oauth import load_credentials

mcp = FastMCP("google-calendar")


def _calendar_service():
    creds = load_credentials()
    if not creds:
        raise RuntimeError("Google Calendar not authenticated. Visit /api/auth/start in the web UI.")
    return build("calendar", "v3", credentials=creds)


@mcp.tool()
def list_calendar_events(days_ahead: int = 180) -> list[dict]:
    """Return all calendar events in the next N days as a list of {summary, start, end}."""
    service = _calendar_service()
    now = date.today()
    time_min = f"{now.isoformat()}T00:00:00Z"
    time_max = f"{(now + timedelta(days=days_ahead)).isoformat()}T23:59:59Z"

    result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
        maxResults=500,
    ).execute()

    events = []
    for item in result.get("items", []):
        start = item["start"].get("date") or item["start"].get("dateTime", "")[:10]
        end = item["end"].get("date") or item["end"].get("dateTime", "")[:10]
        events.append({"summary": item.get("summary", "(no title)"), "start": start, "end": end})
    return events


@mcp.tool()
def find_free_windows(min_days: int = 5, max_days: int = 14) -> list[dict]:
    """Return free date windows (no calendar events) of length between min_days and max_days.

    Returns a list of {start, end, duration_days} sorted by start date.
    Looks 180 days ahead.
    """
    events = list_calendar_events(days_ahead=180)

    blocked: set[date] = set()
    for ev in events:
        try:
            s = date.fromisoformat(ev["start"])
            e = date.fromisoformat(ev["end"])
        except ValueError:
            continue
        cur = s
        while cur <= e:
            blocked.add(cur)
            cur += timedelta(days=1)

    windows = []
    today = date.today()
    streak_start: date | None = None
    streak_len = 0

    for i in range(180):
        d = today + timedelta(days=i)
        if d not in blocked:
            if streak_start is None:
                streak_start = d
            streak_len += 1
        else:
            if streak_start and min_days <= streak_len <= max_days:
                windows.append({
                    "start": streak_start.isoformat(),
                    "end": (streak_start + timedelta(days=streak_len - 1)).isoformat(),
                    "duration_days": streak_len,
                })
            streak_start = None
            streak_len = 0

    if streak_start and min_days <= streak_len <= max_days:
        windows.append({
            "start": streak_start.isoformat(),
            "end": (streak_start + timedelta(days=streak_len - 1)).isoformat(),
            "duration_days": streak_len,
        })

    return windows


if __name__ == "__main__":
    mcp.run(transport="stdio")
