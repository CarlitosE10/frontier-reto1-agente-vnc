"""Crea la app FastAPI. Se arranca con `uv run uvicorn app.main:app`.

Aquí se conectan los módulos reales: `Settings`, el cliente de OpenRouter, el ciclo del agente
(`run_agent`) y la sesión VNC (`DesktopSession`), todos dentro del `TaskRunner` que usan las rutas.
Al arrancar se cargan los `Settings` y se revisa el OCR: si falta una variable obligatoria o
Tesseract con `spa`, la app no arranca. Hasta entonces `/health` responde 503. Al apagar se
cancelan las tareas en curso, que se desconectan del escritorio antes de que el proceso termine.
Si CANARY_INTERVAL_S y el escritorio del canario están configurados, el canario (T17) corre en
segundo plano mientras la app está arriba.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import canary
from app.agent.loop import run_agent
from app.api import router
from app.config import Settings
from app.llm.openrouter import OpenRouterClient
from app.perception import ocr
from app.tasks import TaskRunner
from app.tracing import configure_logging
from app.vnc.client import DesktopSession

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = Settings()
    ocr.check_available()
    runner = TaskRunner(
        settings,
        agent=run_agent,
        llm=OpenRouterClient(settings),
        desktop=DesktopSession,
    )
    app.state.runner = runner
    logger.info(
        "agente listo",
        extra={
            "vlm_model": settings.vlm_model,
            "vlm_coord_mode": settings.vlm_coord_mode,
            "verify_enabled": settings.verify_enabled,
            "verify_model": settings.verify_model_effective,
            "task_time_budget_s": settings.task_time_budget_s,
            "task_max_steps": settings.task_max_steps,
            "task_max_cost_usd": settings.task_max_cost_usd,
            "irreversible_keywords": settings.irreversible_keywords,
            "canario_cada_s": settings.canary_interval_s if canary.enabled(settings) else None,
        },
    )
    watch = (
        asyncio.create_task(canary.run_canary(runner, settings))
        if canary.enabled(settings)
        else None
    )
    try:
        yield
    finally:
        if watch is not None:
            watch.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watch
        await runner.aclose()
        logger.info("agente detenido")


app = FastAPI(title="Agente VNC", lifespan=lifespan)
app.include_router(router)
