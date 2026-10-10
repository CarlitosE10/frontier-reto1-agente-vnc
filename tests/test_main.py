"""La app arranca con su ejecutor y los módulos reales, y se apaga sin dejar tareas abiertas en
el escritorio.

El arranque es lo que revisa el health check del despliegue (T14).
"""

import asyncio

import httpx
import pytesseract
import pytest

from app import main
from app.llm.openrouter import OpenRouterClient
from app.models import AgentResult, ErrorCode, TaskStatus
from app.vnc.client import DesktopSession

TOKEN = "ftr_prueba"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
DESKTOP = "wss://escritorio.example/websockify"
BODY = {"tarea": "¿Cuántas facturas vencidas hay?", "escritorio": {"url": DESKTOP, "password": "x"}}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # sin el .env de quien corre las pruebas
    monkeypatch.setenv("TEAM_TOKEN", TOKEN)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-prueba")
    monkeypatch.setattr(main, "configure_logging", lambda: None)  # no tocar los logs de pytest


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://agente")


async def wait_until_final(http: httpx.AsyncClient, task_id: str) -> None:
    async with asyncio.timeout(2):
        while (await http.get(f"/tasks/{task_id}", headers=AUTH)).json()["estado"] == "en_curso":
            await asyncio.sleep(0.005)


async def test_health_and_auth_once_the_app_started(env):
    async with main.lifespan(main.app), client() as http:
        health = await http.get("/health")
        assert (health.status_code, health.json()) == (200, {"ok": True})
        assert (await http.post("/tasks")).status_code == 401
        wrong = await http.post("/tasks", headers={"Authorization": "Bearer otro"})
        assert wrong.status_code == 401


async def test_the_agent_gets_the_real_modules(env, monkeypatch):
    received = {}

    async def agent(record, desktop_factory, llm, gate, trace, cancel, settings):
        received.update(desktop=desktop_factory(), llm=llm, gate_llm=gate.llm)
        return AgentResult(status=TaskStatus.TERMINADA, summary="Listo.", cost_usd=0.0, steps=0)

    monkeypatch.setattr(main, "run_agent", agent)
    async with main.lifespan(main.app), client() as http:
        task_id = (await http.post("/tasks", json=BODY, headers=AUTH)).json()["task_id"]
        await wait_until_final(http, task_id)

    assert isinstance(received["desktop"], DesktopSession)  # creada, no conectada
    assert received["desktop"].url == DESKTOP
    assert isinstance(received["llm"], OpenRouterClient)
    assert received["gate_llm"] is received["llm"]  # la verificación usa el mismo cliente


async def test_shutdown_cancels_running_tasks_and_waits_for_them_to_disconnect(env, monkeypatch):
    started, disconnected = asyncio.Event(), asyncio.Event()

    async def agent(record, desktop_factory, llm, gate, trace, cancel, settings):
        started.set()
        try:
            await asyncio.Event().wait()  # una tarea que no termina sola
        finally:
            await asyncio.sleep(0.01)  # desconectarse toma un momento
            disconnected.set()

    closed = []

    async def aclose(self):
        closed.append(self)

    monkeypatch.setattr(main, "run_agent", agent)
    monkeypatch.setattr(OpenRouterClient, "aclose", aclose)
    async with main.lifespan(main.app), client() as http:
        task_id = (await http.post("/tasks", json=BODY, headers=AUTH)).json()["task_id"]
        await asyncio.wait_for(started.wait(), 2)
        runner = main.app.state.runner

    assert disconnected.is_set()
    record = runner.get(task_id)
    assert (record.status, record.error_code) == (TaskStatus.FALLIDA, ErrorCode.CANCELLED)
    assert len(closed) == 1


async def test_the_app_does_not_start_without_its_secrets(env, monkeypatch):
    monkeypatch.delenv("TEAM_TOKEN")
    with pytest.raises(Exception, match="team_token"):
        async with main.lifespan(main.app):
            pass


def without_tesseract(config):
    raise pytesseract.TesseractNotFoundError()


@pytest.mark.parametrize(
    "get_languages, message",
    [(lambda config: ["eng", "osd"], "spa"), (without_tesseract, "instalado")],
    ids=["sin spa", "sin tesseract"],
)
async def test_the_app_does_not_start_without_spanish_ocr(env, monkeypatch, get_languages, message):
    monkeypatch.setattr(pytesseract, "get_languages", get_languages)
    with pytest.raises(RuntimeError, match=message):
        async with main.lifespan(main.app):
            pass
