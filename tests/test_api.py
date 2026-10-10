"""API y ejecutor (plan, T10): contrato HTTP exacto, autenticación, candado por escritorio y
presupuesto, con un agente simulado en lugar de `run_agent`."""

import asyncio
import time

import httpx
import pytest
from fastapi import FastAPI

from app import api, tasks
from app.agent import summary
from app.api import router
from app.config import Settings
from app.models import AgentResult, ErrorCode, TaskStatus
from app.tasks import TaskRunner
from app.vnc.client import DesktopError, DesktopSession
from tests.fakes import FakeDesktop, write_screen

TOKEN = "ftr_token-de-prueba"
OPENROUTER_KEY = "sk-or-llave-de-prueba"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PASSWORD = "clave-del-escritorio"
DESKTOP = "wss://escritorio-1.example/websockify"
OTHER_DESKTOP = "wss://escritorio-2.example/websockify"


def task_body(url: str = DESKTOP) -> dict:
    return {
        "tarea": "Registra al cliente Papelería Los Andes, NIT 901234567.",
        "escritorio": {"url": url, "password": PASSWORD},
    }


# --- Dobles de T07 -------------------------------------------------------------------------------
# `sanitize` y `build_summary` se construyen en otra rama. Mientras su código no esté aquí, estos
# dobles mínimos ocupan su lugar; cuando llegue, las pruebas usan el real sin cambios.


def stand_in_sanitize(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, "[oculto]")
    return text


def stand_in_build_summary(result, error_code: ErrorCode | None) -> str:
    return f"La tarea no se completó ({error_code.value if error_code else 'sin código'})."


def _pending(function, *args) -> bool:
    try:
        function(*args)
    except NotImplementedError:
        return True
    return False


@pytest.fixture(autouse=True)
def summary_stand_ins(monkeypatch):
    if _pending(summary.sanitize, "", []):
        monkeypatch.setattr(api, "sanitize", stand_in_sanitize)
    if _pending(summary.build_summary, None, ErrorCode.CANCELLED):
        monkeypatch.setattr(tasks, "build_summary", stand_in_build_summary)


# --- Agentes simulados (misma firma que run_agent) -----------------------------------------------


async def finishing_agent(record, desktop_factory, llm, gate, trace, cancel, settings):
    return AgentResult(status=TaskStatus.TERMINADA, summary="Listo.", cost_usd=0.01, steps=3)


def raising_agent(error: Exception):
    async def agent(record, desktop_factory, llm, gate, trace, cancel, settings):
        raise error

    return agent


class ClickingAgent:
    """Abre un `FakeDesktop` por tarea y hace clic cada 10 ms hasta que `release` lo deja terminar.

    Anota en `events` cuándo conecta y desconecta cada tarea, y en `status_on_disconnect` el
    estado publicado en el momento de desconectarse. Tarda `stop_s` en detenerse.
    """

    def __init__(self, screens, stop_s: float = 0.0):
        self.screens = screens
        self.stop_s = stop_s
        self.release = asyncio.Event()
        self.desktops: dict[str, FakeDesktop] = {}
        self.cancels: dict[str, asyncio.Event] = {}
        self.events: list[tuple[str, str]] = []
        self.status_on_disconnect: dict[str, TaskStatus] = {}

    async def __call__(self, record, desktop_factory, llm, gate, trace, cancel, settings):
        desktop = self.desktops[record.id] = FakeDesktop(self.screens)
        self.cancels[record.id] = cancel
        try:
            async with desktop:
                self.events.append(("conecta", record.id))
                while not self.release.is_set():
                    await desktop.click(10, 10)
                    await asyncio.sleep(0.01)
        finally:
            await asyncio.sleep(self.stop_s)
            self.events.append(("desconecta", record.id))
            self.status_on_disconnect[record.id] = record.status
        return AgentResult(status=TaskStatus.TERMINADA, summary="Listo.", cost_usd=0.02, steps=3)

    def connected(self, task_id: str) -> bool:
        return ("conecta", task_id) in self.events


# --- Utilidades ----------------------------------------------------------------------------------


def make_settings(tmp_path, **overrides) -> Settings:
    return Settings(
        _env_file=None,
        team_token=TOKEN,
        openrouter_api_key=OPENROUTER_KEY,
        trace_dir=tmp_path / "traces",
        **overrides,
    )


@pytest.fixture
async def make_client(tmp_path):
    """`await make_client(agent, **settings)` da un cliente HTTP contra la app con ese agente."""
    clients: list[httpx.AsyncClient] = []

    async def make(agent, **overrides) -> httpx.AsyncClient:
        app = FastAPI()
        app.include_router(router)
        settings = make_settings(tmp_path, **overrides)
        app.state.runner = TaskRunner(settings, agent=agent, timeout_margin_s=0)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agente")
        clients.append(client)
        return client

    yield make

    for client in clients:
        await client.aclose()
    # Tareas que la prueba dejó corriendo.
    pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


@pytest.fixture
def screens(tmp_path):
    return [write_screen(tmp_path / "pantalla.png", "white")]


async def submit(client: httpx.AsyncClient, url: str = DESKTOP) -> str:
    response = await client.post("/tasks", json=task_body(url), headers=AUTH)
    assert response.status_code == 200
    return response.json()["task_id"]


async def status_of(client: httpx.AsyncClient, task_id: str) -> dict:
    response = await client.get(f"/tasks/{task_id}", headers=AUTH)
    assert response.status_code == 200
    return response.json()


async def final_status(client: httpx.AsyncClient, task_id: str, timeout: float = 2.0) -> dict:
    async with asyncio.timeout(timeout):
        while (body := await status_of(client, task_id))["estado"] == "en_curso":
            await asyncio.sleep(0.005)
    return body


async def wait_until(condition, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.005)


# --- Contrato ------------------------------------------------------------------------------------


async def test_health_needs_no_token(make_client):
    client = await make_client(finishing_agent)
    response = await client.get("/health")
    assert (response.status_code, response.json()) == (200, {"ok": True})


async def test_health_is_503_while_the_app_has_no_runner():
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://a") as c:
        response = await c.get("/health")
    assert (response.status_code, response.json()) == (503, {"ok": False})


async def test_post_answers_only_the_task_id_without_waiting_for_the_desktop(make_client):
    async def slow_agent(record, desktop_factory, llm, gate, trace, cancel, settings):
        await asyncio.sleep(5)  # conectar por VNC tarda; POST /tasks no lo espera

    client = await make_client(slow_agent)

    started = time.perf_counter()
    response = await client.post("/tasks", json=task_body(), headers=AUTH)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.2
    assert response.status_code == 200
    assert list(response.json()) == ["task_id"]
    assert isinstance(response.json()["task_id"], str)


async def test_get_answers_exactly_estado_and_resumen(make_client):
    progressed, gate_open = asyncio.Event(), asyncio.Event()

    async def agent(record, desktop_factory, llm, gate, trace, cancel, settings):
        record.progress = "Paso 3: buscando el cliente"
        progressed.set()
        await gate_open.wait()
        return AgentResult(
            status=TaskStatus.TERMINADA, summary="Cliente registrado.", cost_usd=0.01, steps=3
        )

    client = await make_client(agent)
    task_id = await submit(client)

    await progressed.wait()
    assert await status_of(client, task_id) == {
        "estado": "en_curso",
        "resumen": "Paso 3: buscando el cliente",
    }

    gate_open.set()
    assert await final_status(client, task_id) == {
        "estado": "terminada",
        "resumen": "Cliente registrado.",
    }


async def test_resumen_never_shows_secrets(make_client):
    progressed, gate_open = asyncio.Event(), asyncio.Event()

    async def leaky_agent(record, desktop_factory, llm, gate, trace, cancel, settings):
        record.progress = f"Paso 1: la clave es {PASSWORD} y el token {TOKEN}"
        progressed.set()
        await gate_open.wait()
        return AgentResult(
            status=TaskStatus.FALLIDA,
            summary=f"No se pudo. Clave {PASSWORD}, llave {OPENROUTER_KEY}.",
            cost_usd=0.0,
            steps=1,
        )

    client = await make_client(leaky_agent)
    task_id = await submit(client)
    await progressed.wait()

    running = (await status_of(client, task_id))["resumen"]
    gate_open.set()
    final = (await final_status(client, task_id))["resumen"]

    for text in (running, final):
        assert PASSWORD not in text
        assert TOKEN not in text
        assert OPENROUTER_KEY not in text


async def test_agent_receives_the_task_and_its_own_desktop_factory(make_client):
    received = {}

    async def agent(record, desktop_factory, llm, gate, trace, cancel, settings):
        received.update(record=record, desktop=desktop_factory(), trace=trace, settings=settings)
        return AgentResult(status=TaskStatus.TERMINADA, summary="Listo.", cost_usd=0.0, steps=0)

    client = await make_client(agent)
    task_id = await submit(client)
    await final_status(client, task_id)

    assert received["record"].id == task_id
    assert received["record"].request.escritorio.url == DESKTOP
    assert isinstance(received["desktop"], DesktopSession)  # creada, no conectada
    assert received["trace"].task_id == task_id
    assert received["settings"].team_token.get_secret_value() == TOKEN


# --- Autenticación y errores ---------------------------------------------------------------------

BAD_AUTH = {
    "sin header": {},
    "token equivocado": {"Authorization": "Bearer ftr_otro"},
    "esquema Basic": {"Authorization": f"Basic {TOKEN}"},
    "token vacío": {"Authorization": "Bearer "},
    "token no ASCII": {"Authorization": "Bearer contraseña".encode()},
}


@pytest.mark.parametrize("headers", BAD_AUTH.values(), ids=list(BAD_AUTH))
@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/tasks"), ("GET", "/tasks/abc"), ("GET", "/tasks/abc/traza")],
)
async def test_without_a_valid_token_answers_401(make_client, headers, method, path):
    client = await make_client(finishing_agent)
    response = await client.request(method, path, json=task_body(), headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_missing_token_answers_401_even_with_an_invalid_body(make_client):
    client = await make_client(finishing_agent)
    response = await client.post("/tasks", json={"tarea": 1})
    assert response.status_code == 401


@pytest.mark.parametrize("path", ["/tasks/no-existe", "/tasks/no-existe/traza"])
async def test_unknown_task_answers_404(make_client, path):
    client = await make_client(finishing_agent)
    response = await client.get(path, headers=AUTH)
    assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"tarea": "Registra un cliente."},
        {"tarea": "Registra un cliente.", "escritorio": {"url": DESKTOP}},
        {"escritorio": {"url": DESKTOP, "password": PASSWORD}},
    ],
    ids=["vacío", "sin escritorio", "sin contraseña", "sin tarea"],
)
async def test_invalid_body_answers_422(make_client, body):
    client = await make_client(finishing_agent)
    response = await client.post("/tasks", json=body, headers=AUTH)
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (DesktopError(ErrorCode.VNC_AUTH_FAILED), "VNC_AUTH_FAILED"),
        (RuntimeError("falla inesperada"), None),
    ],
    ids=["DesktopError", "excepción cualquiera"],
)
async def test_agent_exception_ends_fallida(make_client, error, code):
    client = await make_client(raising_agent(error))
    task_id = await submit(client)

    body = await final_status(client, task_id)

    assert body["estado"] == "fallida"
    if code:
        assert code in body["resumen"]


# --- Candado por escritorio y presupuesto --------------------------------------------------------


async def test_new_task_on_the_same_desktop_cancels_the_previous_one(make_client, screens):
    agent = ClickingAgent(screens)
    client = await make_client(agent)
    first = await submit(client)
    await wait_until(lambda: agent.connected(first))

    second = await submit(client)
    body = await final_status(client, first)

    assert body["estado"] == "fallida"
    assert "CANCELLED" in body["resumen"]
    assert agent.cancels[first].is_set()
    # La anterior se desconectó antes de publicar su estado y antes de que la nueva conectara.
    assert agent.status_on_disconnect[first] is TaskStatus.EN_CURSO
    await wait_until(lambda: agent.connected(second))
    assert agent.events == [("conecta", first), ("desconecta", first), ("conecta", second)]
    clicks = len(agent.desktops[first].actions)
    await asyncio.sleep(0.05)
    assert len(agent.desktops[first].actions) == clicks

    agent.release.set()
    assert (await final_status(client, second))["estado"] == "terminada"


async def test_task_waiting_for_the_desktop_can_be_replaced_too(make_client, screens):
    # La primera tarda en detenerse, así que la segunda queda esperando el candado.
    agent = ClickingAgent(screens, stop_s=0.2)
    client = await make_client(agent)
    first = await submit(client)
    await wait_until(lambda: agent.connected(first))

    second = await submit(client)
    third = await submit(client)

    for task_id in (first, second):
        body = await final_status(client, task_id)
        assert body["estado"] == "fallida"
        assert "CANCELLED" in body["resumen"]
    await wait_until(lambda: agent.connected(third))
    assert not agent.connected(second)

    agent.release.set()
    assert (await final_status(client, third))["estado"] == "terminada"


async def test_task_on_another_desktop_is_not_cancelled(make_client, screens):
    agent = ClickingAgent(screens)
    client = await make_client(agent)
    first = await submit(client, DESKTOP)
    other = await submit(client, OTHER_DESKTOP)
    await wait_until(lambda: agent.connected(first) and agent.connected(other))

    await submit(client, DESKTOP)
    assert (await final_status(client, first))["estado"] == "fallida"
    assert (await status_of(client, other))["estado"] == "en_curso"

    agent.release.set()
    assert (await final_status(client, other))["estado"] == "terminada"


async def test_timeout_ends_fallida_with_budget_exhausted(make_client, screens):
    agent = ClickingAgent(screens)  # nunca se libera: solo el tope de tiempo lo detiene
    client = await make_client(agent, task_time_budget_s=0.2)
    task_id = await submit(client)

    body = await final_status(client, task_id)

    assert body["estado"] == "fallida"
    assert "BUDGET_EXHAUSTED" in body["resumen"]
    assert agent.cancels[task_id].is_set()
    assert agent.status_on_disconnect[task_id] is TaskStatus.EN_CURSO
    desktop = agent.desktops[task_id]
    assert desktop.connected is False
    clicks = len(desktop.actions)
    await asyncio.sleep(0.05)
    assert len(desktop.actions) == clicks
