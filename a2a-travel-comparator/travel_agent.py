"""
Travel Agent — A2A server on port :5003.
Reads travel_data.json and exposes two skills:

  compare_travel_costs({cities, origin, travel_dates, duration_nights})
    → sorted list of {city, flight, hotel_per_night_adjusted,
                      total_estimated_cost, travel_time_hours,
                      event_warnings, peak_season}

  check_events_impact({city, travel_dates})
    → {city, travel_dates, events, high_impact_count}

Round 2 of the negotiation loop calls check_events_impact to re-check a
specific city without re-running the full cost model.
"""

import json
import re
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from a2a_protocol import AgentCard, AgentSkill, A2ATask, A2AResult

PORT = 5003
HOST = "0.0.0.0"
DATA_FILE = Path(__file__).parent / "travel_data.json"

# ---------------------------------------------------------------------------
# Data — loaded once at startup
# ---------------------------------------------------------------------------

travel_data: dict[str, Any] = {}


def _load_data() -> None:
    global travel_data
    with open(DATA_FILE, encoding="utf-8") as f:
        travel_data = json.load(f)
    print(f"  Travel data loaded: {list(travel_data.keys())}")

# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _parse_date(s: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_date_range(range_str: str) -> tuple[date | None, date | None]:
    """Parse 'YYYY-MM-DD to YYYY-MM-DD' into (start, end)."""
    parts = re.split(r"\s+to\s+", range_str.strip(), maxsplit=1)
    if len(parts) == 2:
        return _parse_date(parts[0]), _parse_date(parts[1])
    d = _parse_date(range_str.strip())
    return d, d


def _overlaps(event_range: str, travel_start: date | None, travel_end: date | None) -> bool:
    if travel_start is None or travel_end is None:
        return False
    ev_start, ev_end = _parse_date_range(event_range)
    if ev_start is None or ev_end is None:
        return False
    return ev_start <= travel_end and ev_end >= travel_start


def _in_peak_season(city_data: dict, travel_dates: str) -> bool:
    """Check if travel start month falls within the city's peak season range."""
    peak = city_data.get("peak_season", "")
    if not peak or not travel_dates:
        return False
    travel_start, _ = _parse_date_range(travel_dates)
    if not travel_start:
        return False
    month_abbr = travel_start.strftime("%b")   # e.g. "Jun"
    month_full = travel_start.strftime("%B")   # e.g. "June"
    return month_abbr in peak or month_full in peak

# ---------------------------------------------------------------------------
# Skill: compare_travel_costs
# ---------------------------------------------------------------------------

async def _compare_travel_costs(params: dict[str, Any]) -> list[dict]:
    """
    params:
      cities          list[str]  — city names to compare
      origin          str        — departure city (one of the 5 origin cities)
      travel_dates    str        — "YYYY-MM-DD to YYYY-MM-DD"
      duration_nights int        — length of stay
    """
    cities: list[str] = params.get("cities", [])
    origin: str       = params.get("origin", "New York")
    travel_dates: str = params.get("travel_dates", "")
    duration_nights   = int(params.get("duration_nights", 3))

    travel_start, travel_end = _parse_date_range(travel_dates) if travel_dates else (None, None)

    results = []
    for city_name in cities:
        city = travel_data.get(city_name)
        if not city:
            continue

        flight_cost   = city["flights"].get(origin, 0)
        travel_time   = city["travel_time_hours"].get(origin, 0)
        base_hotel    = city["avg_hotel_per_night"]
        surcharge_pct = city["peak_season_surcharge_pct"]

        in_peak       = _in_peak_season(city, travel_dates) if travel_dates else False
        hotel_adj     = round(base_hotel * (1 + surcharge_pct / 100), 2) if in_peak else float(base_hotel)
        total_cost    = round(flight_cost + hotel_adj * duration_nights, 2)

        event_warnings = []
        for event in city.get("upcoming_events", []):
            if _overlaps(event["date_range"], travel_start, travel_end):
                event_warnings.append({
                    "name":        event["name"],
                    "impact":      event["impact"],
                    "description": event["description"],
                })

        results.append({
            "city":                    city_name,
            "flight":                  flight_cost,
            "hotel_per_night_adjusted": hotel_adj,
            "total_estimated_cost":    total_cost,
            "travel_time_hours":       travel_time,
            "duration_nights":         duration_nights,
            "peak_season":             in_peak,
            "event_warnings":          event_warnings,
        })

    results.sort(key=lambda x: x["total_estimated_cost"])
    return results

# ---------------------------------------------------------------------------
# Skill: check_events_impact
# ---------------------------------------------------------------------------

async def _check_events_impact(params: dict[str, Any]) -> dict:
    """
    params:
      city          str — city name
      travel_dates  str — "YYYY-MM-DD to YYYY-MM-DD"

    Used by Round 2 to probe a specific city for event conflicts without
    re-running the full cost model.
    """
    city_name:    str = params.get("city", "")
    travel_dates: str = params.get("travel_dates", "")

    city = travel_data.get(city_name)
    if not city:
        return {"city": city_name, "events": [], "error": f"City '{city_name}' not found in travel data"}

    travel_start, travel_end = _parse_date_range(travel_dates) if travel_dates else (None, None)

    overlapping = [
        event for event in city.get("upcoming_events", [])
        if _overlaps(event["date_range"], travel_start, travel_end)
    ] if travel_dates else list(city.get("upcoming_events", []))

    return {
        "city":              city_name,
        "travel_dates":      travel_dates,
        "events":            overlapping,
        "high_impact_count": sum(1 for e in overlapping if e["impact"] == "High"),
        "medium_impact_count": sum(1 for e in overlapping if e["impact"] == "Medium"),
    }

# ---------------------------------------------------------------------------
# Skill dispatch table
# ---------------------------------------------------------------------------

_HANDLERS = {
    "compare_travel_costs":  _compare_travel_costs,
    "check_events_impact":   _check_events_impact,
}

# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------

AGENT_CARD = AgentCard(
    name="Travel Advisor Agent",
    description=(
        "Provides flight costs, hotel rates, travel times, and event impact "
        "analysis for US travel destinations. Reads from curated city data."
    ),
    url=f"http://localhost:{PORT}",
    skills=[
        AgentSkill(
            name="compare_travel_costs",
            description="Compare flight + hotel costs across multiple cities for a given origin and travel window.",
            input_schema={
                "type": "object",
                "properties": {
                    "cities":          {"type": "array",  "items": {"type": "string"}, "description": "List of city names"},
                    "origin":          {"type": "string", "description": "Departure city (New York / Los Angeles / Chicago / Dallas / Atlanta)"},
                    "travel_dates":    {"type": "string", "description": "Date range: 'YYYY-MM-DD to YYYY-MM-DD'"},
                    "duration_nights": {"type": "integer","description": "Number of nights"},
                },
                "required": ["cities", "origin"],
            },
        ),
        AgentSkill(
            name="check_events_impact",
            description="Check which upcoming events overlap with travel dates for a single city.",
            input_schema={
                "type": "object",
                "properties": {
                    "city":         {"type": "string", "description": "City name"},
                    "travel_dates": {"type": "string", "description": "Date range: 'YYYY-MM-DD to YYYY-MM-DD'"},
                },
                "required": ["city"],
            },
        ),
    ],
)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"\nTravel Agent starting on port {PORT}...")
    _load_data()
    yield


app = FastAPI(title="Travel Advisor Agent", lifespan=lifespan)


@app.get("/.well-known/agent.json")
async def agent_card() -> JSONResponse:
    return JSONResponse(AGENT_CARD.model_dump())


@app.post("/")
async def dispatch(task: A2ATask) -> A2AResult:
    handler = _HANDLERS.get(task.skill)
    if not handler:
        raise HTTPException(status_code=404, detail=f"Unknown skill: {task.skill}")
    try:
        output = await handler(task.params)
        return A2AResult(task_id=task.task_id, skill=task.skill, status="success", output=output)
    except Exception as exc:
        return A2AResult(task_id=task.task_id, skill=task.skill, status="error", error=str(exc))


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
