# AI MCP and Skills

A hands-on demonstration of the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) with two learning tiers — start with the **basic** pair to understand MCP tools, then move to the **advanced** pair to explore all three MCP primitives (Tools, Resources, and Prompts/Skills).

## Project Structure

```
ai-mcp-and-skills/
├── weather/                 # BASIC server: two tools only (get_alerts, get_forecast)
│   ├── weather.py
│   └── pyproject.toml
├── mcp-client/              # BASIC client: simple free-form chat shell
│   ├── client.py
│   ├── .env.example
│   └── pyproject.toml
├── weather-skills/          # ADVANCED server: tools + resources + prompt skills
│   ├── weather_server.py
│   ├── state_codes.json
│   └── pyproject.toml
├── skills-client/           # ADVANCED client: full MCP primitive explorer
│   ├── client.py
│   ├── .env.example
│   └── pyproject.toml
└── test_openai.py           # Smoke-test for OpenAI API connectivity
```

---

## Tier 1 — Basic

A minimal MCP server + client. Good starting point for understanding how MCP tools work.

### `weather/` — Basic MCP Server

An MCP server backed by the free [National Weather Service API](https://api.weather.gov) exposing two tools:

| Tool | Description |
|------|-------------|
| `get_alerts` | Active weather alerts for a US state (two-letter code) |
| `get_forecast` | 5-period forecast for a lat/lon coordinate |

### `mcp-client/` — Basic MCP Client

A minimal chat shell. Type any question and GPT-4o automatically calls MCP tools as needed. No slash commands — just plain queries.

**Setup & run:**

```bash
cd weather
uv sync

cd ../mcp-client
uv sync
cp .env.example .env   # add your OPENAI_API_KEY

uv run python client.py ../weather/weather.py
```

**Example:**

```
Connected to server with tools: ['get_alerts', 'get_forecast']

Query: Are there any weather alerts in Florida?
  -> Calling tool: get_alerts({'state': 'FL'})

Active alerts for FL: ...
```

---

## Tier 2 — Advanced

Extends the basic pair with MCP Resources and Prompts (Skills), plus a feature-rich client that lets you explore all three primitives interactively.

### `weather-skills/` — Advanced MCP Server

All three MCP primitive types:

| Primitive | Name | Description |
|-----------|------|-------------|
| **Tool** | `get_alerts` | Active weather alerts for a US state |
| **Tool** | `get_forecast` | 5-period forecast for a lat/lon coordinate |
| **Resource** | `weather://state-codes` | JSON map of state abbreviations → full names |
| **Resource** | `weather://alert-severity-guide` | NWS severity levels and recommended actions |
| **Prompt** | `outdoor_event_readiness` | Advises whether an outdoor event is safe to hold |
| **Prompt** | `severe_weather_briefing` | Structured emergency briefing for a US state |
| **Prompt** | `multi_day_trip_planner` | Weather-optimized itinerary for multiple destinations |

### `skills-client/` — Advanced MCP Client

An interactive CLI shell that discovers and exercises all MCP primitives.

| Command | Description |
|---------|-------------|
| `/tools` | List available MCP tools |
| `/resources` | List available MCP resources |
| `/resource <uri>` | Read a specific resource (e.g. `weather://state-codes`) |
| `/skills` | List available prompts/skills |
| `/skill <name>` | Invoke a skill interactively (prompts for arguments) |
| `quit` | Exit |

Any other input is treated as a free-form query sent to GPT-4o with all server tools available.

**Setup & run:**

```bash
cd weather-skills
uv sync

cd ../skills-client
uv sync
cp .env.example .env   # add your OPENAI_API_KEY

uv run python client.py ../weather-skills/weather_server.py
```

**Example:**

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

---

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager
- OpenAI API key

## Testing OpenAI Connectivity

```bash
# from the repo root (requires OPENAI_API_KEY in .env)
python test_openai.py
```

## How It Works

```
┌────────────┐   stdio/MCP   ┌───────────────┐
│   client   │ ◄───────────► │    server     │
│ (OpenAI)   │               │  (NWS API)    │
└────────────┘               └───────────────┘
      │
      │  OpenAI API (GPT-4o)
      ▼
 Tool calls ↔ MCP tool calls bridged automatically
```

1. The client launches the server as a subprocess and connects over stdin/stdout.
2. It discovers tools (and optionally resources/prompts) via MCP initialization.
3. User queries are sent to GPT-4o; any tool calls are routed back through the MCP session.
4. For skills (advanced), the prompt template is fetched from the server and injected as the system/user message.

## Dependencies

| Package | Used in | Purpose |
|---------|---------|---------|
| `mcp[cli]` | weather, weather-skills | MCP server framework (FastMCP) |
| `httpx` | weather, weather-skills | Async HTTP client for NWS API |
| `mcp` | mcp-client, skills-client | MCP client session |
| `openai` | mcp-client, skills-client | GPT-4o chat completions + tool use |
| `python-dotenv` | mcp-client, skills-client | Load `.env` for API key |
