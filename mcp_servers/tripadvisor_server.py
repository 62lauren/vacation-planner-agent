#!/usr/bin/env python3
"""MCP server exposing TripAdvisor Content API tools with response caching."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import hashlib
from pathlib import Path
import requests
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv()
mcp = FastMCP("tripadvisor")

CACHE_PATH = Path.home() / ".vacation_planner_cache.json"
BASE_URL = "https://api.content.tripadvisor.com/api/v1"


def _api_key() -> str:
    return os.environ["TRIPADVISOR_API_KEY"]


def _cache_get(key: str):
    if CACHE_PATH.exists():
        data = json.loads(CACHE_PATH.read_text())
        return data.get(key)
    return None


def _cache_set(key: str, value) -> None:
    data = {}
    if CACHE_PATH.exists():
        data = json.loads(CACHE_PATH.read_text())
    data[key] = value
    CACHE_PATH.write_text(json.dumps(data))


def _cache_key(*parts) -> str:
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()


def _get(path: str, params: dict) -> dict:
    params = {**params, "key": _api_key(), "language": "en"}
    ck = _cache_key(path, json.dumps(params, sort_keys=True))
    cached = _cache_get(ck)
    if cached is not None:
        return cached
    resp = requests.get(f"{BASE_URL}{path}", params=params, timeout=15)
    resp.raise_for_status()
    result = resp.json()
    _cache_set(ck, result)
    return result


@mcp.tool()
def search_tripadvisor_locations(destination: str, category: str = "attractions", limit: int = 10) -> list[dict]:
    """Search TripAdvisor for locations at a destination.

    Args:
        destination: City or area name (e.g., "Tokyo")
        category: One of: attractions, restaurants, hotels, geos
        limit: Max results to return (max 10)

    Returns list of {location_id, name, address, rating, num_reviews, ranking_data}.
    """
    data = _get("/location/search", {
        "searchQuery": destination,
        "category": category,
        "limit": min(limit, 10),
    })

    results = []
    for loc in data.get("data", []):
        results.append({
            "location_id": loc.get("location_id"),
            "name": loc.get("name"),
            "address": loc.get("address_obj", {}).get("address_string", ""),
            "rating": loc.get("rating"),
            "num_reviews": loc.get("num_reviews"),
            "ranking_data": loc.get("ranking_data", {}),
        })
    return results


@mcp.tool()
def get_reviews(location_id: str, limit: int = 5) -> list[dict]:
    """Fetch recent TripAdvisor reviews for a location.

    Args:
        location_id: TripAdvisor location ID (from search_tripadvisor_locations)
        limit: Number of reviews to fetch (max 5)

    Returns list of {rating, title, text, published_date, author}.
    """
    data = _get(f"/location/{location_id}/reviews", {"limit": min(limit, 5)})

    reviews = []
    for rev in data.get("data", []):
        reviews.append({
            "rating": rev.get("rating"),
            "title": rev.get("title"),
            "text": rev.get("text", "")[:500],
            "published_date": rev.get("published_date", "")[:10],
            "author": rev.get("user", {}).get("username", "anonymous"),
        })
    return reviews


if __name__ == "__main__":
    mcp.run(transport="stdio")
