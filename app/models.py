"""Tipos compartidos entre módulos (plan, sección 2.2)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, SecretStr


class TaskStatus(StrEnum):
    EN_CURSO = "en_curso"
    TERMINADA = "terminada"
    FALLIDA = "fallida"


class ErrorCode(StrEnum):
    VNC_CONNECT_FAILED = "VNC_CONNECT_FAILED"
    VNC_AUTH_FAILED = "VNC_AUTH_FAILED"
    WS_DISCONNECTED = "WS_DISCONNECTED"
    SCREEN_NOT_STABLE = "SCREEN_NOT_STABLE"
    CLICK_NO_EFFECT = "CLICK_NO_EFFECT"
    LOOP_DETECTED = "LOOP_DETECTED"
    VLM_ERROR = "VLM_ERROR"
    GATE_BLOCKED = "GATE_BLOCKED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    CANCELLED = "CANCELLED"


class Effect(StrEnum):
    NAVEGAR = "navegar"
    EDITAR = "editar"
    GUARDAR = "guardar"
    EXPORTAR = "exportar"
    ELIMINAR = "eliminar"


# --- Petición de la API ---


class Desktop(BaseModel):
    url: str
    password: SecretStr


class TaskRequest(BaseModel):
    tarea: str
    escritorio: Desktop


# --- Acciones del VLM ---


class ActionBase(BaseModel):
    observacion: str
    # Solo la trae el primer paso: la fecha que muestra la app, o None si no se ve.
    fecha_app: str | None = None


class Click(ActionBase):
    kind: Literal["click"] = "click"
    x: int
    y: int
    objetivo: str
    efecto: Effect
    double: bool = False


class TypeText(ActionBase):
    kind: Literal["type_text"] = "type_text"
    texto: str
    campo: str


class PressKey(ActionBase):
    kind: Literal["press_key"] = "press_key"
    combinacion: str  # "enter", "tab", "ctrl+a", "esc"


class Scroll(ActionBase):
    kind: Literal["scroll"] = "scroll"
    x: int
    y: int
    direccion: Literal["up", "down"]
    cantidad: int


class Wait(ActionBase):
    kind: Literal["wait"] = "wait"
    segundos: float = Field(ge=0, le=3)


class Candidate(BaseModel):
    nombre: str
    identificador: str


class FinishTask(ActionBase):
    kind: Literal["finish_task"] = "finish_task"
    resumen: str
    respuesta: list[str] | None = None
    evidencia: str


class FailTask(ActionBase):
    kind: Literal["fail_task"] = "fail_task"
    razon: str
    datos_clave: list[str]
    candidatos: list[Candidate] = Field(default_factory=list)


Action = Annotated[
    Click | TypeText | PressKey | Scroll | Wait | FinishTask | FailTask,
    Field(discriminator="kind"),
]


# --- Filtro, tareas y resultado ---


class GateDecision(BaseModel):
    outcome: Literal["approve", "block"]
    reason: str
    checks: dict[str, bool] | None = None


@dataclass
class TaskRecord:
    id: str
    request: TaskRequest
    status: TaskStatus = TaskStatus.EN_CURSO
    summary: str = ""
    progress: str = ""
    cost_usd: float = 0.0
    error_code: ErrorCode | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class AgentResult(BaseModel):
    status: TaskStatus
    summary: str
    error_code: ErrorCode | None = None
    cost_usd: float
    steps: int
