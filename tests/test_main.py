"""La app arranca con su ejecutor: lo que revisa el health check del despliegue (T14)."""

import httpx
import pytest

from app import main


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # sin el .env de quien corre las pruebas
    monkeypatch.setenv("TEAM_TOKEN", "ftr_prueba")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-prueba")
    monkeypatch.setattr(main, "configure_logging", lambda: None)  # no tocar los logs de pytest


async def test_health_and_auth_once_the_app_started(env):
    transport = httpx.ASGITransport(app=main.app)
    async with (
        main.lifespan(main.app),
        httpx.AsyncClient(transport=transport, base_url="http://agente") as client,
    ):
        health = await client.get("/health")
        assert (health.status_code, health.json()) == (200, {"ok": True})
        assert (await client.post("/tasks")).status_code == 401
        wrong = await client.post("/tasks", headers={"Authorization": "Bearer otro"})
        assert wrong.status_code == 401


async def test_the_app_does_not_start_without_its_secrets(env, monkeypatch):
    monkeypatch.delenv("TEAM_TOKEN")
    with pytest.raises(Exception, match="team_token"):
        async with main.lifespan(main.app):
            pass
