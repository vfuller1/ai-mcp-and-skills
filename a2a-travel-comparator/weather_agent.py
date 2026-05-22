"""
Weather Agent — A2A server on port :5001.
Bridges A2A requests → MCP session → weather_server.py → NWS API.

Skill exposed:
  assess_city_weather({city, state, latitude, longitude, travel_dates})
    → {city, verdict, max_temp_f, precipitation_risk, active_alerts,
       alerts_summary, forecast_summary}

Verdict logic:
  NO-GO    — tornado/hurricane/extreme warning OR temp > 105F
  CAUTION  — flood/watch/advisory OR precipitation OR temp 95-105F or <35F
  GO       — no alerts, comfortable temperature range
"""

import asyncio
import re
import sys
from contextlib import asynccontextmanager, AsyncExitStack
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from a2a_protocol import AgentCard, AgentSkill, A2ATask, A2AResult

PORT = 5001
HOST = "0.0.0.0"
WEATHER_SERVER = str(Path(__file__).parent.parent / "weather-skills" / "weather_server.py")

# ---------------------------------------------------------------------------
# MCP bridge — maintains a single live session to weather_server.py
# ---------------------------------------------------------------------------

class WeatherMCPBridge:
    def __init__(self):
        self._exit_stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def connect(self, server_path: str) -> None:
        params = StdioServerParameters(command=sys.executable, args=[server_path], env=None)
        transport = await self._exit_stack.enter_async_context(stdio_client(params))
        stdio, write = transport
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(stdio, write)
        )
        await self._session.initialize()
        tools = (await self._session.list_tools()).tools
        print(f"  MCP connected → {server_path}")
        print(f"  MCP tools available: {[t.name for t in tools]}")

    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        result = await self._session.call_tool(name, args)
        return "".join(c.text for c in result.content if hasattr(c, "text"))

    async def close(self) -> None:
        await self._exit_stack.aclose()


bridge = WeatherMCPBridge()

# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------

_NO_GO_KEYWORDS = [
    "tornado warning", "hurricane warning", "extreme wind warning",
    "blizzard warning", "ice storm warning", "severe thunderstorm warning",
]
_CAUTION_KEYWORDS = [
    "flood", "watch", "advisory", "freeze warning", "heat advisory",
    "wind advisory", "winter storm", "tropical storm",
]


def _derive_verdict(city: str, alerts_text: str, forecast_text: str) -> dict[str, Any]:
    al = alerts_text.lower()
    fc = forecast_text.lower()

    no_go_alert = any(k in al for k in _NO_GO_KEYWORDS)
    caution_alert = any(k in al for k in _CAUTION_KEYWORDS)
    no_alerts = "no active" in al

    temps = [int(t) for t in re.findall(r"temperature[:\s]+(\d+)", fc)]
    max_temp = max(temps, default=72)

    precip_words = ["rain", "snow", "showers", "thunderstorm", "sleet", "precipitation"]
    has_precip = any(w in fc for w in precip_words)

    if no_go_alert or max_temp > 105:
        verdict = "NO-GO"
    elif caution_alert or has_precip or max_temp > 95 or max_temp < 35:
        verdict = "CAUTION"
    else:
        verdict = "GO"

    return {
        "city": city,
        "verdict": verdict,
        "max_temp_f": max_temp,
        "precipitation_risk": has_precip,
        "active_alerts": not no_alerts,
        "alerts_summary": alerts_text[:600],
        "forecast_summary": forecast_text[:800],
    }

# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------

AGENT_CARD = AgentCard(
    name="Weather Agent",
    description=(
        "Assesses city weather conditions via live NWS data for travel planning. "
        "Returns GO / CAUTION / NO-GO verdicts with temperature, precipitation, and alert details."
    ),
    url=f"http://localhost:{PORT}",
    skills=[
        AgentSkill(
            name="assess_city_weather",
            description="Return a GO/CAUTION/NO-GO weather assessment for a city.",
            input_schema={
                "type": "object",
                "properties": {
                    "city":         {"type": "string", "description": "City name"},
                    "state":        {"type": "string", "description": "Two-letter US state code"},
                    "latitude":     {"type": "number", "description": "City latitude"},
                    "longitude":    {"type": "number", "description": "City longitude"},
                    "travel_dates": {"type": "string", "description": "Date range, e.g. '2026-06-01 to 2026-06-07'"},
                },
                "required": ["city", "state", "latitude", "longitude"],
            },
        )
    ],
)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"\nWeather Agent starting on port {PORT}...")
    await bridge.connect(WEATHER_SERVER)
    yield
    await bridge.close()


app = FastAPI(title="Weather Agent", lifespan=lifespan)


@app.get("/.well-known/agent.json")
async def agent_card() -> JSONResponse:
    return JSONResponse(AGENT_CARD.model_dump())


@app.post("/")
async def dispatch(task: A2ATask) -> A2AResult:
    if task.skill != "assess_city_weather":
        raise HTTPException(status_code=404, detail=f"Unknown skill: {task.skill}")

    try:
        p = task.params
        city  = p.get("city", "Unknown")
        state = p.get("state", "")
        lat   = float(p["latitude"])
        lon   = float(p["longitude"])

        # Fan out both MCP tool calls in parallel
        alerts_text, forecast_text = await asyncio.gather(
            bridge.call_tool("get_alerts",  {"state": state}),
            bridge.call_tool("get_forecast", {"latitude": lat, "longitude": lon}),
        )

        output = _derive_verdict(city, alerts_text, forecast_text)
        return A2AResult(task_id=task.task_id, skill=task.skill, status="success", output=output)

    except Exception as exc:
        return A2AResult(task_id=task.task_id, skill=task.skill, status="error", error=str(exc))


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
