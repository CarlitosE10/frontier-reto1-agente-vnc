"""Crea la app FastAPI. Se arranca con `uv run uvicorn app.main:app`.

Al arrancar se cargan los `Settings` (si falta una variable obligatoria, la app no arranca) y se
arma el `TaskRunner` que usan las rutas. Hasta entonces `/health` responde 503.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import router
from app.config import Settings
from app.tasks import TaskRunner
from app.tracing import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    app.state.runner = TaskRunner(Settings())
    yield


app = FastAPI(title="Agente VNC", lifespan=lifespan)
app.include_router(router)
