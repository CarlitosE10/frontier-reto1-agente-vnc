"""Trazas por tarea y logs del servidor en JSON (plan, T11)."""

import json
import logging
import logging.config
import sys
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image
from uvicorn.config import LOGGING_CONFIG

from app import tracing
from app.agent import summary
from app.models import (
    Click,
    Desktop,
    Effect,
    ErrorCode,
    GateDecision,
    TaskRequest,
    TypeText,
)
from app.tracing import JsonFormatter, Trace, configure_logging

PASSWORD = "clave-del-escritorio"
TOKEN = "ftr_token-de-prueba"


def stand_in_sanitize(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, "[oculto]")
    return text


@pytest.fixture(autouse=True)
def sanitize_stand_in(monkeypatch):
    """`sanitize` se construye en T07, en otra rama. Mientras no esté aquí, lo reemplaza un doble
    mínimo; cuando llegue, las pruebas usan el real sin cambios."""
    try:
        summary.sanitize("", [])
    except NotImplementedError:
        monkeypatch.setattr(tracing, "sanitize", stand_in_sanitize)


def test_writes_and_reads_steps_in_the_task_folder(tmp_path):
    trace = Trace("tarea-1", tmp_path, secrets=[PASSWORD])
    action = Click(
        observacion="Lista de clientes de Papelería Los Andes",
        x=120,
        y=48,
        objetivo="Nuevo cliente",
        efecto=Effect.NAVEGAR,
    )
    decision = GateDecision(
        outcome="block", reason="Hay dos Ana Torres", checks={"registro_correcto": False}
    )

    trace.step(
        paso=1,
        captura=str(tmp_path / "tarea-1" / "001-paso-1.png"),
        accion=action,
        observacion=action.observacion,
        verificacion=decision,
        diff_pct=12.5,
        latencias={"vlm_s": 1.8, "verificacion_s": 2.1, "vnc_s": 0.2},
        cost_usd=0.0012,
        error_code=ErrorCode.GATE_BLOCKED,
    )
    trace.step(paso=2, error_code=None)

    assert (tmp_path / "tarea-1" / "trace.jsonl").is_file()
    first, second = trace.read()
    datetime.fromisoformat(first["ts"])
    assert 0 <= first["elapsed_s"] <= second["elapsed_s"]
    assert first["paso"] == 1
    assert first["accion"]["kind"] == "click"
    assert (first["accion"]["x"], first["accion"]["efecto"]) == (120, "navegar")
    assert first["observacion"] == "Lista de clientes de Papelería Los Andes"
    assert first["verificacion"] == {
        "outcome": "block",
        "reason": "Hay dos Ana Torres",
        "checks": {"registro_correcto": False},
    }
    assert first["diff_pct"] == 12.5
    assert first["latencias"]["vlm_s"] == 1.8
    assert first["cost_usd"] == 0.0012
    assert first["error_code"] == "GATE_BLOCKED"
    assert (second["paso"], second["error_code"]) == (2, None)


def test_injected_password_never_reaches_the_files(tmp_path):
    trace = Trace("tarea-2", tmp_path, secrets=[PASSWORD, TOKEN, ""])
    request = TaskRequest(
        tarea=f"Cambia la clave a {PASSWORD}",
        escritorio=Desktop(url="wss://escritorio.example/websockify", password=PASSWORD),
    )

    trace.step(
        observacion=f"El campo muestra {PASSWORD}",
        accion=TypeText(observacion="Formulario", texto=PASSWORD, campo="Contraseña"),
        evidencia=[f"fila con {PASSWORD}", {"nota": f"token {TOKEN}"}],
        peticion=request,
        **{f"campo_{PASSWORD}": "valor"},
    )
    path = trace.screenshot(Image.new("RGB", (32, 20), "white"), f"login {PASSWORD}")

    files = list((tmp_path / "tarea-2").iterdir())
    assert len(files) == 2
    for file in files:
        assert PASSWORD not in file.name
        assert PASSWORD.encode() not in file.read_bytes()
        assert TOKEN.encode() not in file.read_bytes()
    assert PASSWORD not in path
    # Se tapa el secreto, no el resto del paso.
    (step,) = trace.read()
    assert step["accion"]["campo"] == "Contraseña"
    assert step["peticion"]["escritorio"]["url"] == "wss://escritorio.example/websockify"


def test_screenshots_are_numbered_pngs(tmp_path):
    trace = Trace("tarea-3", tmp_path, secrets=[])

    first = trace.screenshot(Image.new("RGB", (1280, 800), "white"), "Búsqueda: Ana Torres")
    second = trace.screenshot(Image.new("RGB", (1280, 800), "gray"), "¿?")

    assert Path(first) == tmp_path / "tarea-3" / "001-busqueda-ana-torres.png"
    assert Path(second).name == "002-captura.png"
    with Image.open(first) as image:
        assert (image.format, image.size) == ("PNG", (1280, 800))


def test_reading_a_trace_without_steps(tmp_path):
    trace = Trace("tarea-4", tmp_path, secrets=[])
    assert trace.read() == []
    assert not (tmp_path / "tarea-4").exists()


def test_reading_skips_a_half_written_line(tmp_path):
    trace = Trace("tarea-5", tmp_path, secrets=[])
    trace.step(paso=1)
    with (tmp_path / "tarea-5" / "trace.jsonl").open("a", encoding="utf-8") as file:
        file.write('{"paso": 2, "acci')

    assert [step["paso"] for step in trace.read()] == [1]


# --- Logs del servidor ---------------------------------------------------------------------------


def make_record(msg: str, *args, exc_info=None, **extra) -> logging.LogRecord:
    record = logging.LogRecord("app.tasks", logging.INFO, __file__, 1, msg, args, exc_info)
    record.__dict__.update(extra)
    return record


def test_json_formatter_writes_one_object_per_record():
    line = JsonFormatter().format(make_record("tarea %s", "recibida", task_id="abc"))

    entry = json.loads(line)
    assert set(entry) == {"ts", "level", "logger", "msg", "task_id"}
    assert (entry["level"], entry["logger"]) == ("INFO", "app.tasks")
    assert (entry["msg"], entry["task_id"]) == ("tarea recibida", "abc")
    datetime.fromisoformat(entry["ts"])


def test_json_formatter_includes_the_exception():
    try:
        raise ValueError("algo falló")
    except ValueError:
        record = make_record("el agente falló", exc_info=sys.exc_info())

    entry = json.loads(JsonFormatter().format(record))
    assert "ValueError: algo falló" in entry["exc"]


@pytest.fixture
def restore_logging():
    names = ["", "uvicorn", "uvicorn.error", "uvicorn.access"]
    saved = {}
    for name in names:
        logger = logging.getLogger(name)
        saved[name] = (logger.handlers[:], logger.level, logger.propagate)
    yield
    for name, (handlers, level, propagate) in saved.items():
        logger = logging.getLogger(name)
        logger.handlers = handlers
        logger.setLevel(level)
        logger.propagate = propagate


def test_server_logs_come_out_as_json(restore_logging, capsys):
    logging.config.dictConfig(LOGGING_CONFIG)  # lo que uvicorn instala al arrancar
    configure_logging()

    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "POST", "/tasks", "1.1", 200
    )
    logging.getLogger("uvicorn.error").info("Application startup complete.")
    logging.getLogger("app.tasks").info("tarea recibida", extra={"task_id": "abc"})

    entries = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [entry["logger"] for entry in entries] == [
        "uvicorn.access",
        "uvicorn.error",
        "app.tasks",
    ]
    assert entries[0]["msg"] == '127.0.0.1:5000 - "POST /tasks HTTP/1.1" 200'
    assert entries[2]["task_id"] == "abc"
