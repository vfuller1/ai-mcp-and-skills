# AI MCP and Skills

A hands-on demonstration of the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) showing all three MCP primitives — **Tools**, **Resources**, and **Prompts (Skills)** — wired together with an OpenAI GPT-4o client.

## Project Structure

```
ai-mcp-and-skills/
├── weather-skills/          # MCP server: weather data via NWS API
│   ├── weather_server.py
│   ├── state_codes.json
│   └── pyproject.toml
├── skills-client/           # MCP client: interactive chat shell + OpenAI
│   ├── client.py
│   ├── .env.example
│   └── pyproject.toml
└── test_openai.py           # Smoke-test for OpenAI API connectivity
```

## Components

### `weather-skills` — MCP Server

An MCP server backed by the free [National Weather Service API](https://api.weather.gov). It exposes all three MCP primitive types:

| Primitive | Name | Description |
|-----------|------|-------------|
| **Tool** | `get_alerts` | Active weather alerts for a US state (two-letter code) |
| **Tool** | `get_forecast` | 5-period forecast for a lat/lon coordinate |
| **Resource** | `weather://state-codes` | JSON map of state abbreviations → full names |
| **Resource** | `weather://alert-severity-guide` | NWS severity levels and recommended actions |
| **Prompt** | `outdoor_event_readiness` | Advises whether an outdoor event is safe to hold |
| **Prompt** | `severe_weather_briefing` | Structured emergency briefing for a US state |
| **Prompt** | `multi_day_trip_planner` | Weather-optimized itinerary for multiple destinations |

### `skills-client` — MCP Client

An interactive CLI chat shell that connects to any MCP server via stdio, discovers its capabilities, and routes natural-language queries through OpenAI GPT-4o with full tool-call support.

**Interactive commands:**

| Command | Description |
|---------|-------------|
| `/tools` | List available MCP tools |
| `/resources` | List available MCP resources |
| `/resource <uri>` | Read a specific resource (e.g. `weather://state-codes`) |
| `/skills` | List available prompts/skills |
| `/skill <name>` | Invoke a skill interactively (prompts for arguments) |
| `quit` | Exit |

Any other input is treated as a free-form query sent to GPT-4o with all server tools available.

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager
- OpenAI API key

## Setup

**1. Install dependencies for each sub-project:**

```bash
cd weather-skills
uv sync

cd ../skills-client
uv sync
```

**2. Set your OpenAI API key:**

```bash
cp skills-client/.env.example skills-client/.env
# Edit skills-client/.env and add your key:
# OPENAI_API_KEY=sk-...
```

## Running

Start the client and point it at the weather server:

```bash
cd skills-client
uv run python client.py ../weather-skills/weather_server.py
```

The client launches the server as a subprocess, performs MCP initialization, and drops you into the interactive shell.

### Example session

```
--- Connected to MCP Server ---
  Tools:     ['get_alerts', 'get_forecast']
  Resources: ['weather://state-codes', 'weather://alert-severity-guide']
  Skills:    ['outdoor_event_readiness', 'severe_weather_briefing', 'multi_day_trip_planner']
-------------------------------

Query: /skill outdoor_event_readiness
Skill 'outdoor_event_readiness' requires:
  location (required): Austin, TX
  date (required): 2025-07-04
  event_type (required): outdoor concert

Invoking skill 'outdoor_event_readiness'...
  -> Calling tool: get_alerts({'state': 'TX'})
  -> Calling tool: get_forecast({'latitude': 30.27, 'longitude': -97.74})
...
```

## Testing OpenAI Connectivity

```bash
# from the repo root (requires OPENAI_API_KEY in .env)
python test_openai.py
```

## How It Works

```
┌──────────────┐   stdio/MCP   ┌──────────────────────┐
│ skills-client│ ◄───────────► │ weather-skills server │
│  (OpenAI)    │               │  (NWS API)            │
└──────────────┘               └──────────────────────┘
       │
       │  OpenAI API (GPT-4o)
       ▼
  Tool calls ↔ MCP tool calls bridged automatically
```

1. The client connects to the MCP server over stdin/stdout.
2. It discovers tools, resources, and prompts via MCP initialization.
3. When a skill is invoked, the prompt template is fetched from the server and sent to GPT-4o.
4. GPT-4o may request tool calls; the client routes them back through the MCP session to the server.
5. The final response is printed to the terminal.

## Dependencies

| Package | Used in | Purpose |
|---------|---------|---------|
| `mcp[cli]` | weather-skills | MCP server framework (FastMCP) |
| `httpx` | weather-skills | Async HTTP client for NWS API |
| `mcp` | skills-client | MCP client session |
| `openai` | skills-client | GPT-4o chat completions + tool use |
| `python-dotenv` | skills-client | Load `.env` for API key |
