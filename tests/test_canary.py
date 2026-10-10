"""Canario (T17): una tarea de solo lectura que registra una alerta si no sale bien."""

import asyncio
import logging

import pytest

from app import canary, main
from app.config import Settings
from app.models import AgentResult, ErrorCode, TaskStatus
from app.tasks import TaskRunner
from app.vnc.client import DesktopError

PASSWORD = "clave-del-canario"


def make_settings(tmp_path, **overrides) -> Settings:
    values = {
        "team_token": "ftr_prueba",
        "openrouter_api_key": "sk-or-prueba",
        "trace_dir": tmp_path / "traces",
        "canary_interval_s": 900,
        "canary_desktop_url": "wss://escritorio-propio.example/websockify",
        "canary_desktop_password": PASSWORD,
        "canary_task": "¿En qué ciudad está el cliente Distribuciones El Faro?",
        "canary_expected": "respuesta: Bogotá",
    }
    return Settings(_env_file=None, **{**values, **overrides})


def answering(summary: str):
    async def agent(record, desktop_factory, llm, gate, trace, cancel, settings):
        return AgentResult(status=TaskStatus.TERMINADA, summary=summary, cost_usd=0.01, steps=5)

    return agent


def raising(error: Exception):
    async def agent(record, desktop_factory, llm, gate, trace, cancel, settings):
        raise error

    return agent


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch):
    monkeypatch.setattr(canary, "POLL_S", 0.005)


async def run_once(settings: Settings, agent) -> canary.CanaryResult:
    runner = TaskRunner(settings, agent=agent, timeout_margin_s=0)
    try:
        return await canary.canary_once(runner, settings)
    finally:
        await runner.aclose()


async def test_a_healthy_run_is_logged_as_ok(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="app.canary")
    settings = make_settings(tmp_path)

    result = await run_once(settings, answering("respuesta: Bogotá\nLa ficha CL-0007 dice Bogotá."))

    assert result.ok
    assert result.status is TaskStatus.TERMINADA
    assert "canario ok" in caplog.text
    assert "ALERTA" not in caplog.text


async def test_a_wrong_password_raises_an_alert_with_vnc_auth_failed(tmp_path, caplog):
    """La falla simulada de T17: contraseña equivocada."""
    settings = make_settings(tmp_path)
    error = DesktopError(ErrorCode.VNC_AUTH_FAILED, f"rechazada: {PASSWORD}")

    result = await run_once(settings, raising(error))

    assert not result.ok
    assert result.error_code is ErrorCode.VNC_AUTH_FAILED
    [alert] = [r for r in caplog.records if r.getMessage() == "ALERTA canario"]
    assert alert.levelno == logging.ERROR
    assert alert.error_code == "VNC_AUTH_FAILED"
    assert PASSWORD not in caplog.text
    assert PASSWORD not in result.summary


async def test_an_answer_without_the_expected_text_is_an_alert(tmp_path, caplog):
    settings = make_settings(tmp_path)

    result = await run_once(settings, answering("respuesta: Medellín"))

    assert not result.ok
    assert result.status is TaskStatus.TERMINADA
    assert "ALERTA canario" in caplog.text


@pytest.mark.parametrize(
    "overrides",
    [{"canary_interval_s": 0}, {"canary_desktop_url": ""}, {"canary_task": ""}],
    ids=["intervalo 0", "sin escritorio", "sin tarea"],
)
def test_the_canary_is_off_unless_fully_configured(tmp_path, overrides):
    assert canary.enabled(make_settings(tmp_path))
    assert not canary.enabled(make_settings(tmp_path, **overrides))


def test_it_is_off_by_default():
    assert not canary.enabled(Settings(_env_file=None, team_token="t", openrouter_api_key="k"))


async def test_the_service_runs_the_canary_only_when_enabled(monkeypatch, tmp_path):
    started, cancelled = [], []

    async def fake_run_canary(runner, settings):
        started.append(runner)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(runner)
            raise

    monkeypatch.chdir(tmp_path)  # sin el .env de quien corre las pruebas
    monkeypatch.setattr(main, "configure_logging", lambda: None)
    monkeypatch.setattr(canary, "run_canary", fake_run_canary)
    monkeypatch.setenv("TEAM_TOKEN", "ftr_prueba")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-prueba")

    async with main.lifespan(main.app):
        await asyncio.sleep(0)
    assert started == []

    monkeypatch.setenv("CANARY_INTERVAL_S", "900")
    monkeypatch.setenv("CANARY_DESKTOP_URL", "wss://escritorio-propio.example/websockify")
    monkeypatch.setenv("CANARY_TASK", "¿En qué ciudad está el cliente Distribuciones El Faro?")
    async with main.lifespan(main.app):
        await asyncio.sleep(0)
    assert len(started) == 1
    assert cancelled == started  # al apagar se cancela
