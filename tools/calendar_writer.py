from googleapiclient.discovery import build
from tools.oauth import load_credentials

TYPE_COLORS = {
    "hotel": "2",        # sage
    "restaurant": "10",  # basil
    "attraction": "9",   # blueberry
    "transport": "8",    # graphite
}


def create_trip_events(plan: dict) -> list[str]:
    creds = load_credentials()
    service = build("calendar", "v3", credentials=creds)
    event_ids: list[str] = []

    start_date = plan["start_date"]
    end_date_inclusive = plan["end_date"]
    # All-day end date must be day-after for Google Calendar
    from datetime import date, timedelta
    end_dt = date.fromisoformat(end_date_inclusive) + timedelta(days=1)
    end_date_exclusive = end_dt.isoformat()

    # Master spanning event (transparent, so it doesn't block time)
    master = service.events().insert(calendarId="primary", body={
        "summary": f"🌴 {plan['trip_title']}",
        "start": {"date": start_date},
        "end": {"date": end_date_exclusive},
        "transparency": "transparent",
        "colorId": "7",
    }).execute()
    event_ids.append(master["id"])

    total_days = len(plan["days"])
    for day in plan["days"]:
        day_num = day["day"]
        day_date = day["date"]
        theme = day.get("theme", "")

        # All-day banner
        banner = service.events().insert(calendarId="primary", body={
            "summary": f"🗓 Day {day_num}/{total_days}: {theme}",
            "start": {"date": day_date},
            "end": {"date": day_date},
            "colorId": "9",
        }).execute()
        event_ids.append(banner["id"])

        # Timed activities (skip transport-only notes)
        for act in day.get("activities", []):
            act_type = act.get("type", "attraction")
            if act_type == "transport" and not act.get("address"):
                continue
            time_str = act.get("time", "09:00")
            start_iso = f"{day_date}T{time_str}:00"
            # Default 1-hour duration
            from datetime import datetime, timedelta as td
            start_dt = datetime.fromisoformat(start_iso)
            end_dt_act = start_dt + td(hours=1)

            body = {
                "summary": act["name"],
                "location": act.get("address", ""),
                "start": {"dateTime": start_iso, "timeZone": plan.get("timezone", "UTC")},
                "end": {"dateTime": end_dt_act.isoformat(), "timeZone": plan.get("timezone", "UTC")},
                "colorId": TYPE_COLORS.get(act_type, "1"),
            }
            if act.get("notes"):
                body["description"] = act["notes"]

            ev = service.events().insert(calendarId="primary", body=body).execute()
            event_ids.append(ev["id"])

    return event_ids
