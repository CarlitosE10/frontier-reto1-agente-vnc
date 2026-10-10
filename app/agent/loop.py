"""Ciclo del agente (se implementa en T09)."""

import asyncio
from collections.abc import Callable

from app.agent.gate import Gate
from app.config import Settings
from app.llm.openrouter import OpenRouterClient
from app.models import AgentResult, TaskRecord
from app.tracing import Trace
from app.vnc.client import DesktopSession


async def run_agent(
    record: TaskRecord,
    desktop_factory: Callable[[], DesktopSession],
    llm: OpenRouterClient,
    gate: Gate,
    trace: Trace,
    cancel: asyncio.Event,
    settings: Settings,
) -> AgentResult:
    raise NotImplementedError
