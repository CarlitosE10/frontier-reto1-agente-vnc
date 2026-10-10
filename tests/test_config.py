"""`Settings` y `EvalSettings` leen exactamente las variables de `.env.example` (plan, 2.1)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import EvalSettings, Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"

# Tabla de la sección 2.1 del plan.
EXPECTED_DEFAULTS = {
    "vlm_model": "anthropic/claude-haiku-5.5",
    "vlm_coord_mode": "pixels",
    "vlm_reasoning_effort": "low",
    "verify_enabled": True,
    "task_time_budget_s": 270,
    "task_max_steps": 40,
    "task_max_cost_usd": 0.15,
    "click_hold_ms": 150,
    "double_click_hold_ms": 120,
    "change_timeout_s": 1.2,
    "stable_interval_s": 0.25,
    "stable_timeout_s": 1.5,
    "diff_min_pixels": 50,
    "irreversible_keywords": [
        "guardar",
        "aplicar",
        "grabar",
        "crear",
        "registrar",
        "actualizar",
        "aceptar",
        "confirmar",
        "sí",
        "eliminar",
        "borrar",
        "anular",
        "exportar",
        "descargar",
        "generar",
        "procesar",
        "aprobar",
        "finalizar",
        "enviar",
    ],
    "history_steps": 10,
    "evidence_screens": 5,
    "trace_dir": Path("traces"),
}


def example_variables() -> set[str]:
    names = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.add(line.partition("=")[0].strip())
    return names


def field_variables(model: type[Settings] | type[EvalSettings]) -> set[str]:
    return {name.upper() for name in model.model_fields}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Las pruebas no dependen de las variables de quien las corre, ni de su .env."""
    for name in example_variables() | field_variables(Settings) | field_variables(EvalSettings):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def secrets_env(monkeypatch):
    monkeypatch.setenv("TEAM_TOKEN", "ftr_prueba")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-prueba")


def test_env_example_lists_exactly_the_settings_variables():
    assert example_variables() == field_variables(Settings) | field_variables(EvalSettings)


def test_defaults_follow_the_plan_table():
    settings = Settings(_env_file=None, team_token="t", openrouter_api_key="k")
    assert settings.model_dump(exclude={"team_token", "openrouter_api_key"}) == EXPECTED_DEFAULTS


def test_env_example_values_match_the_defaults(secrets_env):
    from_example = Settings(_env_file=ENV_EXAMPLE)
    assert from_example.model_dump() == Settings(_env_file=None).model_dump()


def test_secrets_are_required_and_empty_counts_as_missing():
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=ENV_EXAMPLE)
    missing = {e["loc"][0] for e in error.value.errors() if e["type"] == "missing"}
    assert missing == {"team_token", "openrouter_api_key"}


def test_environment_overrides_and_keyword_parsing(secrets_env, monkeypatch):
    monkeypatch.setenv("VLM_MODEL", "qwen/qwen3.7-plus")
    monkeypatch.setenv("VLM_COORD_MODE", "norm1000")
    monkeypatch.setenv("VERIFY_ENABLED", "false")
    monkeypatch.setenv("TASK_MAX_STEPS", "12")
    monkeypatch.setenv("IRREVERSIBLE_KEYWORDS", " Guardar, sí ,,Exportar ")

    settings = Settings(_env_file=None)

    assert settings.vlm_model == "qwen/qwen3.7-plus"
    assert settings.vlm_coord_mode == "norm1000"
    assert settings.verify_enabled is False
    assert settings.task_max_steps == 12
    assert settings.irreversible_keywords == ["guardar", "sí", "exportar"]


@pytest.mark.parametrize(
    ("name", "value"),
    [("VLM_COORD_MODE", "grid"), ("TASK_MAX_STEPS", "0"), ("CHANGE_TIMEOUT_S", "-1")],
)
def test_invalid_values_are_rejected(secrets_env, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_secrets_do_not_show_in_repr(secrets_env):
    settings = Settings(_env_file=None)
    assert "ftr_prueba" not in repr(settings)
    assert "sk-or-prueba" not in repr(settings)
    assert settings.team_token.get_secret_value() == "ftr_prueba"


def test_eval_settings(monkeypatch):
    with pytest.raises(ValidationError):
        EvalSettings(_env_file=ENV_EXAMPLE)

    monkeypatch.setenv("EVAL_DESKTOP_PASSWORD", "clave")
    monkeypatch.setenv("EVAL_DESKTOP_TOKEN", "token-escritorio")
    monkeypatch.setenv("AGENT_TOKEN", "ftr_prueba")
    settings = EvalSettings(_env_file=ENV_EXAMPLE)

    assert settings.eval_desktop_url == "wss://<tu-escritorio>/websockify"
    assert settings.agent_url == "http://localhost:8000"
    assert "clave" not in repr(settings)
