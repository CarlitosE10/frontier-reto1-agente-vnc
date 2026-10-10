"""Configuración desde variables de entorno (plan, sección 2.1).

Ningún otro módulo lee el entorno: todos reciben un `Settings` (o un `EvalSettings`, en el arnés).
Las variables son exactamente las de `.env.example`.
"""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import NonNegativeInt, PositiveFloat, PositiveInt, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Las variables vacías cuentan como no definidas: toman el valor por defecto o, si son
# obligatorias, fallan al cargar.
_ENV_CONFIG = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    env_ignore_empty=True,
    extra="ignore",
)


class Settings(BaseSettings):
    """Parámetros del agente."""

    model_config = _ENV_CONFIG

    # API y OpenRouter
    team_token: SecretStr
    openrouter_api_key: SecretStr

    # Modelo
    vlm_model: str = "anthropic/claude-haiku-5.5"
    vlm_coord_mode: Literal["pixels", "norm1000"] = "pixels"
    vlm_reasoning_effort: str = "low"
    verify_enabled: bool = True

    # Presupuestos por tarea
    task_time_budget_s: PositiveFloat = 270
    task_max_steps: PositiveInt = 40
    task_max_cost_usd: PositiveFloat = 0.15

    # Interacción con el escritorio
    click_hold_ms: PositiveInt = 150
    double_click_hold_ms: PositiveInt = 120
    change_timeout_s: PositiveFloat = 1.2
    stable_interval_s: PositiveFloat = 0.25
    stable_timeout_s: PositiveFloat = 1.5
    diff_min_pixels: NonNegativeInt = 50
    irreversible_keywords: Annotated[list[str], NoDecode] = [
        "guardar",
        "aplicar",
        "crear",
        "registrar",
        "aceptar",
        "confirmar",
        "sí",
        "eliminar",
        "borrar",
        "anular",
        "exportar",
        "enviar",
    ]

    # Contexto y trazas
    history_steps: NonNegativeInt = 10
    evidence_screens: NonNegativeInt = 5
    trace_dir: Path = Path("./traces")

    @field_validator("irreversible_keywords", mode="before")
    @classmethod
    def _split_keywords(cls, value: object) -> object:
        """`guardar, Crear,,sí` pasa a `["guardar", "crear", "sí"]`."""
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, list):
            return [str(word).strip().lower() for word in value if str(word).strip()]
        return value


class EvalSettings(BaseSettings):
    """Parámetros del arnés de evaluación y de la comparación de modelos (solo en local)."""

    model_config = _ENV_CONFIG

    eval_desktop_url: str
    eval_desktop_password: SecretStr
    eval_desktop_token: SecretStr
    agent_url: str = "http://localhost:8000"
    agent_token: SecretStr
