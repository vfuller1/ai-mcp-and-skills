"""
Travel Coordinator — OpenAI-driven orchestrator with 3-round negotiation.

Usage (agents must already be running):
  python travel_coordinator.py

Example query:
  "Compare Austin, Nashville, and Denver from Chicago for 5 nights in June 2026"

3-Round negotiation:
  Round 1 — Parallel Assessment  : asyncio.gather(N weather tasks + 1 travel task)
  Round 2 — Conflict Detection   : fires only when weather/cost disagree or events flagged
  Round 3 — Final Synthesis      : Winner + comparison table + eliminated cities + tips
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import AsyncOpenAI

from a2a_protocol import A2AClient

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

WEATHER_AGENT_URL = "http://localhost:5001"
TRAVEL_AGENT_URL  = "http://localhost:5003"

# City metadata for lat/lon/state — loaded once at import time
_DATA_FILE = Path(__file__).parent / "travel_data.json"
with open(_DATA_FILE, encoding="utf-8") as _f:
    _CITY_DATA: dict[str, Any] = json.load(_f)

KNOWN_CITIES   = list(_CITY_DATA.keys())
KNOWN_ORIGINS  = ["New York", "Los Angeles", "Chicago", "Dallas", "Atlanta"]

# ---------------------------------------------------------------------------
# TravelCoordinator
# ---------------------------------------------------------------------------

class TravelCoordinator:

    def __init__(self):
        self.openai         = AsyncOpenAI()
        self.weather_client = A2AClient(WEATHER_AGENT_URL)
        self.travel_client  = A2AClient(TRAVEL_AGENT_URL)

    # -----------------------------------------------------------------------
    # Query parsing
    # -----------------------------------------------------------------------

    async def _parse_query(self, query: str) -> dict[str, Any]:
        """Extract structured parameters from a natural-language query."""
        resp = await self.openai.chat.completions.create(
            model="gpt-4o",
            max_tokens=300,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract travel planning parameters from the user query. "
                        "Return ONLY a JSON object with these fields:\n"
                        f"  cities: list of city names — must match from: {KNOWN_CITIES}\n"
                        f"  origin: departure city — one of: {KNOWN_ORIGINS} (default: 'New York')\n"
                        "  travel_dates: 'YYYY-MM-DD to YYYY-MM-DD' — infer from context; "
                        "if year not mentioned assume 2026; if vague use next month\n"
                        "  duration_nights: integer (default: 4)\n"
                        "Return ONLY valid JSON, no markdown fences."
                    ),
                },
                {"role": "user", "content": query},
            ],
        )
        return json.loads(resp.choices[0].message.content)

    # -----------------------------------------------------------------------
    # Round 1: Parallel Assessment
    # -----------------------------------------------------------------------

    async def _round1_assess(
        self,
        cities: list[str],
        origin: str,
        travel_dates: str,
        duration_nights: int,
    ) -> dict[str, Any]:
        """Fan out N weather tasks + 1 travel task simultaneously."""

        valid = [c for c in cities if c in _CITY_DATA]
        print(f"\n  Sending {len(valid)} weather tasks + 1 travel task in parallel...")

        weather_tasks = [
            self.weather_client.call("assess_city_weather", {
                "city":         city,
                "state":        _CITY_DATA[city]["state"],
                "latitude":     _CITY_DATA[city]["latitude"],
                "longitude":    _CITY_DATA[city]["longitude"],
                "travel_dates": travel_dates,
            })
            for city in valid
        ]

        travel_task = self.travel_client.call("compare_travel_costs", {
            "cities":          valid,
            "origin":          origin,
            "travel_dates":    travel_dates,
            "duration_nights": duration_nights,
        })

        # All tasks fire simultaneously — weather and travel agents run in parallel
        all_results = await asyncio.gather(*weather_tasks, travel_task)

        weather_results: list[dict] = []
        for i, city in enumerate(valid):
            r = all_results[i]
            if r.status == "success":
                weather_results.append(r.output)
            else:
                weather_results.append({"city": city, "verdict": "UNKNOWN", "error": r.error})

        travel_r = all_results[-1]
        cost_results: list[dict] = travel_r.output if travel_r.status == "success" else []

        return {"weather": weather_results, "costs": cost_results}

    # -----------------------------------------------------------------------
    # Round 2: Conflict Detection
    # -----------------------------------------------------------------------

    async def _round2_conflicts(
        self,
        round1: dict[str, Any],
        travel_dates: str,
    ) -> dict[str, Any]:
        """
        Ask OpenAI to identify mismatches between weather and cost rankings.
        Fire targeted check_events_impact calls only for flagged cities —
        avoids re-running the full cost model.
        """
        resp = await self.openai.chat.completions.create(
            model="gpt-4o",
            max_tokens=600,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        "You are a travel conflict analyst. Identify conflicts between "
                        "weather verdicts and cost rankings:\n\n"
                        f"Weather assessments:\n{json.dumps(round1['weather'], indent=2)}\n\n"
                        f"Cost rankings (cheapest first):\n{json.dumps(round1['costs'], indent=2)}\n\n"
                        "Flag:\n"
                        "- Cities with NO-GO weather that rank well on cost\n"
                        "- Cities where cheapest option has CAUTION/NO-GO weather\n"
                        "- Cities with High-impact events already flagged in cost data\n"
                        "- Cities that need deeper event investigation\n\n"
                        "Return JSON with exactly these keys:\n"
                        '  "conflicts": [list of plain-English conflict strings]\n'
                        '  "cities_needing_event_check": [list of city name strings]\n'
                        "Return ONLY valid JSON."
                    ),
                }
            ],
        )
        conflict_data = json.loads(resp.choices[0].message.content)

        event_checks: dict[str, Any] = {}
        cities_to_check: list[str] = conflict_data.get("cities_needing_event_check", [])

        if cities_to_check:
            print(f"\n  Round 2 firing targeted event checks: {cities_to_check}")
            check_tasks = [
                self.travel_client.call("check_events_impact", {
                    "city":         city,
                    "travel_dates": travel_dates,
                })
                for city in cities_to_check
            ]
            check_results = await asyncio.gather(*check_tasks)
            for city, result in zip(cities_to_check, check_results):
                if result.status == "success":
                    event_checks[city] = result.output

        return {
            "conflicts":    conflict_data.get("conflicts", []),
            "event_checks": event_checks,
        }

    # -----------------------------------------------------------------------
    # Round 3: Final Synthesis
    # -----------------------------------------------------------------------

    async def _round3_synthesize(
        self,
        query: str,
        params: dict[str, Any],
        round1: dict[str, Any],
        round2: dict[str, Any],
    ) -> str:
        resp = await self.openai.chat.completions.create(
            model="gpt-4o",
            max_tokens=1400,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"You are a travel advisor. The user asked: \"{query}\"\n\n"
                        f"Parsed parameters: {json.dumps(params, indent=2)}\n\n"
                        "Round 1 — Weather assessments:\n"
                        f"{json.dumps(round1['weather'], indent=2)}\n\n"
                        "Round 1 — Cost rankings (sorted cheapest first):\n"
                        f"{json.dumps(round1['costs'], indent=2)}\n\n"
                        "Round 2 — Conflicts detected:\n"
                        f"{json.dumps(round2['conflicts'], indent=2)}\n\n"
                        "Round 2 — Targeted event checks:\n"
                        f"{json.dumps(round2['event_checks'], indent=2)}\n\n"
                        "Produce a structured travel recommendation in this exact format:\n\n"
                        "## Travel Recommendation\n"
                        "**Winner: <City>** — one sentence explaining why.\n\n"
                        "### City Comparison\n"
                        "| City | Weather | Total Cost | Travel Time | Active Alerts | Events | Verdict |\n"
                        "|------|---------|------------|-------------|---------------|--------|---------|\n"
                        "(one row per city)\n\n"
                        "### Eliminated Cities\n"
                        "(bullet list — city and the specific reason it was ruled out)\n\n"
                        "### Travel Tips for <Winner>\n"
                        "(3–5 practical tips based on weather, events, and logistics)\n"
                    ),
                }
            ],
        )
        return resp.choices[0].message.content

    # -----------------------------------------------------------------------
    # Main negotiation entry point
    # -----------------------------------------------------------------------

    async def negotiate(self, query: str) -> str:
        # --- Round 1 ---
        print("\n" + "=" * 60)
        print("Round 1: Initial Parallel Assessment")
        print("=" * 60)

        params          = await self._parse_query(query)
        cities          = params.get("cities", [])
        origin          = params.get("origin", "New York")
        travel_dates    = params.get("travel_dates", "")
        duration_nights = int(params.get("duration_nights", 4))

        valid_cities = [c for c in cities if c in _CITY_DATA]
        if not valid_cities:
            return (
                "No recognized cities found.\n"
                f"Available cities: {', '.join(KNOWN_CITIES)}"
            )

        print(f"  Cities:  {valid_cities}")
        print(f"  Origin:  {origin}")
        print(f"  Dates:   {travel_dates}")
        print(f"  Nights:  {duration_nights}")

        round1 = await self._round1_assess(valid_cities, origin, travel_dates, duration_nights)

        print("\n  Weather verdicts:", {w["city"]: w.get("verdict") for w in round1["weather"]})
        print("  Cost ranking:    ", [c["city"] for c in round1["costs"]])

        # --- Round 2 ---
        print("\n" + "=" * 60)
        print("Round 2: Conflict Detection")
        print("=" * 60)

        round2 = await self._round2_conflicts(round1, travel_dates)

        if round2["conflicts"]:
            print(f"  {len(round2['conflicts'])} conflict(s) found:")
            for conflict in round2["conflicts"]:
                print(f"    • {conflict}")
        else:
            print("  No conflicts detected — proceeding to synthesis.")

        # --- Round 3 ---
        print("\n" + "=" * 60)
        print("Round 3: Final Synthesis")
        print("=" * 60)

        return await self._round3_synthesize(query, params, round1, round2)

    # -----------------------------------------------------------------------
    # Interactive loop
    # -----------------------------------------------------------------------

    async def run(self) -> None:
        print("\nTravel Weather Comparator")
        print("-" * 60)
        print("Compare destinations by live weather + cost + events.")
        print(f"Cities:  {', '.join(KNOWN_CITIES)}")
        print(f"Origins: {', '.join(KNOWN_ORIGINS)}")
        print("-" * 60)
        print("Example: Compare Austin, Nashville, and Denver from Chicago for 5 nights in June 2026")
        print("Type 'quit' to exit.\n")

        while True:
            try:
                query = input("Query: ").strip()
                if not query:
                    continue
                if query.lower() == "quit":
                    break
                result = await self.negotiate(query)
                print(f"\n{result}\n")
            except KeyboardInterrupt:
                break
            except Exception as exc:
                print(f"\nError: {exc}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    coordinator = TravelCoordinator()
    await coordinator.run()


if __name__ == "__main__":
    asyncio.run(main())
