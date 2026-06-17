#!/usr/bin/env python3
"""MCP server exposing Google Maps Places and Distance Matrix tools."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import googlemaps
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv()
mcp = FastMCP("google-maps")

_client: googlemaps.Client | None = None


def _gmaps() -> googlemaps.Client:
    global _client
    if _client is None:
        api_key = os.environ["GOOGLE_MAPS_API_KEY"]
        _client = googlemaps.Client(key=api_key)
    return _client


@mcp.tool()
def search_places(destination: str, place_type: str, radius_meters: int = 5000) -> list[dict]:
    """Search Google Maps for places near a destination.

    Args:
        destination: City or address to search near (e.g., "Tokyo, Japan")
        place_type: One of: tourist_attraction, restaurant, lodging
        radius_meters: Search radius in meters (default 5000)

    Returns list of {name, address, rating, user_ratings_total, place_id, types}.
    """
    client = _gmaps()

    # Geocode destination to lat/lng
    geo = client.geocode(destination)
    if not geo:
        return []
    location = geo[0]["geometry"]["location"]

    results = client.places_nearby(
        location=location,
        radius=radius_meters,
        type=place_type,
        rank_by="prominence",
    )

    places = []
    for p in results.get("results", [])[:15]:
        places.append({
            "name": p.get("name"),
            "address": p.get("vicinity", ""),
            "rating": p.get("rating"),
            "user_ratings_total": p.get("user_ratings_total"),
            "place_id": p.get("place_id"),
            "types": p.get("types", []),
        })
    return places


@mcp.tool()
def get_travel_distances(origin: str, destinations: list[str], mode: str = "driving") -> list[dict]:
    """Get travel distances and durations between an origin and multiple destinations.

    Args:
        origin: Starting address or place name
        destinations: List of destination addresses or place names
        mode: Transport mode — driving, walking, transit, or bicycling

    Returns list of {from, to, distance_km, duration_min, mode}.
    """
    if not destinations:
        return []

    client = _gmaps()
    matrix = client.distance_matrix(
        origins=[origin],
        destinations=destinations,
        mode=mode,
    )

    rows = matrix.get("rows", [])
    if not rows:
        return []

    results = []
    elements = rows[0].get("elements", [])
    for i, element in enumerate(elements):
        if element.get("status") != "OK":
            results.append({
                "from": origin,
                "to": destinations[i],
                "distance_km": None,
                "duration_min": None,
                "mode": mode,
                "error": element.get("status"),
            })
            continue
        results.append({
            "from": origin,
            "to": destinations[i],
            "distance_km": round(element["distance"]["value"] / 1000, 1),
            "duration_min": round(element["duration"]["value"] / 60),
            "mode": mode,
        })
    return results


if __name__ == "__main__":
    mcp.run(transport="stdio")
