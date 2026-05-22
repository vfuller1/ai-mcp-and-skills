"""
A2A Protocol — base layer for Agent-to-Agent communication.

Provides:
  - Data models: AgentCard, AgentSkill, A2ATask, A2AResult
  - A2AServer: FastAPI-based agent host with auto Agent Card endpoint
  - A2AClient: async HTTP client for calling remote agents
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Callable, Awaitable

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class AgentSkill(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = {}


class AgentCard(BaseModel):
    name: str
    description: str
    version: str = "1.0"
    url: str
    skills: list[AgentSkill] = []


class A2ATask(BaseModel):
    task_id: str = ""
    skill: str
    params: dict[str, Any] = {}

    def model_post_init(self, __context: Any) -> None:
        if not self.task_id:
            self.task_id = str(uuid.uuid4())


class A2AResult(BaseModel):
    task_id: str
    skill: str
    status: str          # "success" | "error"
    output: Any = None
    error: str = ""


# ---------------------------------------------------------------------------
# A2AServer
# ---------------------------------------------------------------------------

SkillHandler = Callable[[dict[str, Any]], Awaitable[Any]]


class A2AServer:
    """
    Hosts an agent over HTTP. Subclasses register skill handlers and call
    run() to start the server.

    Exposes:
      GET  /.well-known/agent.json   → AgentCard
      POST /                          → dispatch skill, return A2AResult
    """

    def __init__(self, card: AgentCard):
        self.card = card
        self._handlers: dict[str, SkillHandler] = {}
        self.app = FastAPI(title=card.name)
        self._register_routes()

    def register_skill(self, name: str, handler: SkillHandler) -> None:
        self._handlers[name] = handler

    def _register_routes(self) -> None:
        card = self.card
        handlers = self._handlers

        @self.app.get("/.well-known/agent.json")
        async def agent_card() -> JSONResponse:
            return JSONResponse(card.model_dump())

        @self.app.post("/")
        async def dispatch(task: A2ATask) -> A2AResult:
            handler = handlers.get(task.skill)
            if handler is None:
                raise HTTPException(status_code=404, detail=f"Unknown skill: {task.skill}")
            try:
                output = await handler(task.params)
                return A2AResult(task_id=task.task_id, skill=task.skill, status="success", output=output)
            except Exception as exc:
                return A2AResult(task_id=task.task_id, skill=task.skill, status="error", error=str(exc))

    def run(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        import uvicorn
        uvicorn.run(self.app, host=host, port=port)


# ---------------------------------------------------------------------------
# A2AClient
# ---------------------------------------------------------------------------

class A2AClient:
    """Async client for calling A2A agents."""

    def __init__(self, base_url: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def get_agent_card(self) -> AgentCard:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/.well-known/agent.json")
            resp.raise_for_status()
            return AgentCard(**resp.json())

    async def call(self, skill: str, params: dict[str, Any] | None = None) -> A2AResult:
        task = A2ATask(skill=skill, params=params or {})
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.base_url + "/", content=task.model_dump_json(), headers={"Content-Type": "application/json"})
            resp.raise_for_status()
            return A2AResult(**resp.json())

    async def call_many(self, calls: list[tuple[str, dict[str, Any]]]) -> list[A2AResult]:
        """Fire multiple skill calls in parallel."""
        tasks = [self.call(skill, params) for skill, params in calls]
        return await asyncio.gather(*tasks)
