"""Crea la app FastAPI. Se arranca con `uv run uvicorn app.main:app`."""

from fastapi import FastAPI

from app.api import router

app = FastAPI(title="Agente VNC")
app.include_router(router)
