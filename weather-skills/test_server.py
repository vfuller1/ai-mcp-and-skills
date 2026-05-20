"""
Quick integration test for weather_server.py — exercises all MCP primitives.
Run with: uv run python test_server.py
"""

import asyncio
import sys
sys.stdout.reconfigure(encoding="utf-8")
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SERVER_SCRIPT = str(__file__).replace("test_server.py", "weather_server.py")


def ok(label: str):
    print(f"  [PASS] {label}")


def fail(label: str, err):
    print(f"  [FAIL] {label}: {err}")


async def run_tests():
    params = StdioServerParameters(command=sys.executable, args=[SERVER_SCRIPT])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("\n=== MCP server initialized ===\n")

            # --- Tools ---
            tools_resp = await session.list_tools()
            tool_names = [t.name for t in tools_resp.tools]
            print(f"Tools found: {tool_names}")
            assert "get_alerts" in tool_names and "get_forecast" in tool_names
            ok("list_tools")

            # get_alerts
            try:
                result = await session.call_tool("get_alerts", {"state": "CA"})
                text = result.content[0].text
                assert "CA" in text or "No active" in text
                ok(f"get_alerts(CA) → {text[:80].strip()}...")
            except Exception as e:
                fail("get_alerts(CA)", e)

            # get_forecast (Austin, TX)
            try:
                result = await session.call_tool(
                    "get_forecast", {"latitude": 30.27, "longitude": -97.74}
                )
                text = result.content[0].text
                assert "Forecast" in text or "Temperature" in text
                ok(f"get_forecast(Austin TX) → {text[:80].strip()}...")
            except Exception as e:
                fail("get_forecast(Austin TX)", e)

            # get_forecast — invalid coords (ocean, should error gracefully)
            try:
                result = await session.call_tool(
                    "get_forecast", {"latitude": 0.0, "longitude": 0.0}
                )
                # NWS 404s for non-US coords; the server may raise or return error text
                fail("get_forecast(0,0) expected error but got", result.content[0].text[:60])
            except Exception:
                ok("get_forecast(0,0) raises for non-US coordinates (expected)")

            # --- Resources ---
            resources_resp = await session.list_resources()
            resource_uris = [str(r.uri) for r in resources_resp.resources]
            print(f"\nResources found: {resource_uris}")
            assert "weather://state-codes" in resource_uris
            assert "weather://alert-severity-guide" in resource_uris
            ok("list_resources")

            try:
                res = await session.read_resource("weather://state-codes")
                import json
                codes = json.loads(res.contents[0].text)
                assert codes.get("CA") == "California"
                ok(f"read state-codes → CA={codes['CA']}, TX={codes.get('TX')}")
            except Exception as e:
                fail("read weather://state-codes", e)

            try:
                res = await session.read_resource("weather://alert-severity-guide")
                guide = json.loads(res.contents[0].text)
                assert "severity_levels" in guide
                ok(f"read alert-severity-guide → {len(guide['severity_levels'])} levels")
            except Exception as e:
                fail("read weather://alert-severity-guide", e)

            # --- Prompts (Skills) ---
            prompts_resp = await session.list_prompts()
            prompt_names = [p.name for p in prompts_resp.prompts]
            print(f"\nPrompts found: {prompt_names}")
            expected = {"outdoor_event_readiness", "severe_weather_briefing", "multi_day_trip_planner"}
            assert expected.issubset(set(prompt_names))
            ok("list_prompts")

            try:
                p = await session.get_prompt(
                    "outdoor_event_readiness",
                    {"location": "Austin, TX", "date": "2025-07-04", "event_type": "concert"},
                )
                text = p.messages[0].content.text
                assert "get_alerts" in text and "get_forecast" in text
                ok(f"get_prompt outdoor_event_readiness → {text[:80].strip()}...")
            except Exception as e:
                fail("get_prompt outdoor_event_readiness", e)

            try:
                p = await session.get_prompt("severe_weather_briefing", {"state": "TX"})
                text = p.messages[0].content.text
                assert "TX" in text
                ok(f"get_prompt severe_weather_briefing → {text[:80].strip()}...")
            except Exception as e:
                fail("get_prompt severe_weather_briefing", e)

            try:
                p = await session.get_prompt(
                    "multi_day_trip_planner",
                    {"destinations": "Austin TX, Denver CO"},
                )
                text = p.messages[0].content.text
                assert "get_forecast" in text
                ok(f"get_prompt multi_day_trip_planner → {text[:80].strip()}...")
            except Exception as e:
                fail("get_prompt multi_day_trip_planner", e)

    print("\n=== All tests complete ===\n")


if __name__ == "__main__":
    asyncio.run(run_tests())
