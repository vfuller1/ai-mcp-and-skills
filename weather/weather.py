"""
MCP Weather Server - Basic demo with two tools:
  1. get_alerts   - fetches weather alerts for a US state
  2. get_forecast - fetches weather forecast for a lat/long location
"""

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("weather")

NWS_API_BASE = "https://api.weather.gov"
USER_AGENT = "weather-mcp/1.0"


async def _nws_get(url: str) -> dict:
    """Make a request to the NWS API with proper headers."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json"},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()


@mcp.tool()
async def get_alerts(state: str) -> str:
    """Get active weather alerts for a US state.

    Args:
        state: Two-letter US state code (e.g. CA, TX, NY)
    """
    url = f"{NWS_API_BASE}/alerts/active?area={state.upper()}"
    data = await _nws_get(url)

    features = data.get("features", [])
    if not features:
        return f"No active weather alerts for {state.upper()}."

    alerts = []
    for feature in features[:10]:
        props = feature.get("properties", {})
        alerts.append(
            f"Event: {props.get('event', 'Unknown')}\n"
            f"Severity: {props.get('severity', 'Unknown')}\n"
            f"Headline: {props.get('headline', 'No headline')}\n"
            f"Area: {props.get('areaDesc', 'Unknown area')}\n"
        )

    return f"Active alerts for {state.upper()}:\n\n" + "\n---\n".join(alerts)


@mcp.tool()
async def get_forecast(latitude: float, longitude: float) -> str:
    """Get the weather forecast for a location.

    Args:
        latitude: Latitude of the location
        longitude: Longitude of the location
    """
    points_url = f"{NWS_API_BASE}/points/{latitude},{longitude}"
    points_data = await _nws_get(points_url)

    forecast_url = points_data["properties"]["forecast"]
    forecast_data = await _nws_get(forecast_url)

    periods = forecast_data["properties"]["periods"]
    forecasts = []
    for period in periods[:5]:
        forecasts.append(
            f"{period['name']}:\n"
            f"  Temperature: {period['temperature']}{period['temperatureUnit']}\n"
            f"  Wind: {period['windSpeed']} {period['windDirection']}\n"
            f"  Forecast: {period['detailedForecast']}\n"
        )

    return "Forecast:\n\n" + "\n".join(forecasts)


if __name__ == "__main__":
    mcp.run(transport="stdio")
