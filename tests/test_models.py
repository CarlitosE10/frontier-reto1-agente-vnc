"""Tipos compartidos (plan, sección 2.2)."""

from datetime import UTC

import pytest
from pydantic import TypeAdapter, ValidationError

from app.models import (
    Action,
    AgentResult,
    Click,
    Effect,
    ErrorCode,
    FailTask,
    FinishTask,
    PressKey,
    Scroll,
    TaskRecord,
    TaskRequest,
    TaskStatus,
    TypeText,
    Wait,
)

ACTION = TypeAdapter(Action)

REQUEST = {
    "tarea": "Registra al cliente Papelería Los Andes, NIT 901234567.",
    "escritorio": {"url": "wss://escritorio.example/websockify", "password": "clave-secreta"},
}


def test_enum_values():
    assert {s.value for s in TaskStatus} == {"en_curso", "terminada", "fallida"}
    assert {e.value for e in Effect} == {"navegar", "editar", "guardar", "exportar", "eliminar"}
    assert {c.value for c in ErrorCode} == {
        "VNC_CONNECT_FAILED",
        "VNC_AUTH_FAILED",
        "WS_DISCONNECTED",
        "SCREEN_NOT_STABLE",
        "CLICK_NO_EFFECT",
        "LOOP_DETECTED",
        "VLM_ERROR",
        "GATE_BLOCKED",
        "BUDGET_EXHAUSTED",
        "CANCELLED",
    }
    assert all(code.name == code.value for code in ErrorCode)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"kind": "click", "x": 10, "y": 20, "objetivo": "Guardar", "efecto": "guardar"}, Click),
        ({"kind": "type_text", "texto": "Papelería #1", "campo": "Nombre"}, TypeText),
        ({"kind": "press_key", "combinacion": "ctrl+a"}, PressKey),
        ({"kind": "scroll", "x": 1, "y": 2, "direccion": "down", "cantidad": 3}, Scroll),
        ({"kind": "wait", "segundos": 1.5}, Wait),
        ({"kind": "finish_task", "resumen": "Listo", "evidencia": "Total: 45"}, FinishTask),
        ({"kind": "fail_task", "razon": "Homónimos", "datos_clave": ["52345678"]}, FailTask),
    ],
)
def test_action_union_is_discriminated_by_kind(payload, expected):
    action = ACTION.validate_python({**payload, "observacion": "veo la lista de clientes"})
    assert type(action) is expected
    assert action.observacion == "veo la lista de clientes"
    assert action.fecha_app is None


def test_action_defaults():
    click = ACTION.validate_python(
        {
            "kind": "click",
            "x": 1,
            "y": 2,
            "objetivo": "Buscar",
            "efecto": "navegar",
            "observacion": "",
            "fecha_app": "10/10/2026",
        }
    )
    assert click.double is False
    assert click.efecto is Effect.NAVEGAR
    assert click.fecha_app == "10/10/2026"

    finish = FinishTask(observacion="", resumen="", evidencia="")
    assert finish.respuesta is None

    first = FailTask(observacion="", razon="", datos_clave=[])
    second = FailTask(observacion="", razon="", datos_clave=[])
    first.candidatos.append({"nombre": "Ana Torres", "identificador": "52345678"})
    assert second.candidatos == []


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "drag", "observacion": ""},
        {"kind": "wait", "segundos": 3.5, "observacion": ""},
        {"kind": "scroll", "x": 1, "y": 2, "direccion": "left", "cantidad": 1, "observacion": ""},
        {"kind": "click", "x": 1, "y": 2, "objetivo": "", "efecto": "borrar", "observacion": ""},
        {"kind": "type_text", "texto": "hola", "campo": "Nombre"},
    ],
)
def test_invalid_actions_are_rejected(payload):
    with pytest.raises(ValidationError):
        ACTION.validate_python(payload)


def test_task_request_keeps_the_password_secret():
    request = TaskRequest.model_validate(REQUEST)

    assert request.escritorio.password.get_secret_value() == "clave-secreta"
    assert "clave-secreta" not in repr(request)
    assert "clave-secreta" not in request.model_dump_json()


def test_task_record_defaults():
    record = TaskRecord(id="t1", request=TaskRequest.model_validate(REQUEST))

    assert record.status is TaskStatus.EN_CURSO
    assert record.error_code is None
    assert record.cost_usd == 0.0
    assert record.created_at.tzinfo is UTC


def test_agent_result_serializes_enum_values():
    result = AgentResult(
        status=TaskStatus.FALLIDA,
        summary="",
        error_code=ErrorCode.GATE_BLOCKED,
        cost_usd=0.01,
        steps=3,
    )
    assert result.model_dump(mode="json")["status"] == "fallida"
    assert result.model_dump(mode="json")["error_code"] == "GATE_BLOCKED"
