"""Resumen, normalización de números y saneador (T07)."""

import re

import pytest

from app.agent.summary import REDACTED, build_summary, normalize_number, sanitize
from app.models import Candidate, ErrorCode, FailTask, FinishTask

PASSWORD = "Escritorio#2026"
TEAM_TOKEN = "tok-equipo-7f3a9c"
OPENROUTER_KEY = "sk-or-v1-0123456789abcdef0123456789abcdef"
SECRETS = [PASSWORD, TEAM_TOKEN, OPENROUTER_KEY]


def finish(resumen: str, respuesta: list[str] | None = None) -> FinishTask:
    return FinishTask(
        observacion="Se ve el resultado", resumen=resumen, respuesta=respuesta, evidencia="tabla"
    )


def fail(razon: str, datos_clave: list[str], candidatos: list[Candidate] | None = None):
    return FailTask(
        observacion="Se ve el listado",
        razon=razon,
        datos_clave=datos_clave,
        candidatos=candidatos or [],
    )


def answer_line(summary: str) -> str | None:
    lines = [line for line in summary.splitlines() if re.search(r"respuesta\s*:", line, re.I)]
    assert len(lines) <= 1, f"más de una línea de respuesta: {lines}"
    return lines[0] if lines else None


def first_number(line: str) -> str:
    """Como el evaluador: el primer número de la línea `respuesta:`."""
    return re.search(r"-?\d+(?:\.\d+)?", line).group()


# --- Preguntas ---


def test_e3_answer_goes_first():
    summary = build_summary(
        finish("Ferretería Ruiz tiene 45 facturas vencidas, según el filtro.", ["45"]), None
    )
    assert summary.splitlines()[0] == "respuesta: 45"
    assert first_number(answer_line(summary)) == "45"
    assert "Ferretería Ruiz tiene 45 facturas vencidas" in summary


def test_two_values_share_the_line_in_order():
    result = finish("Datos de Distribuciones El Faro.", ["Pereira", "3157654321"])
    assert build_summary(result, None).splitlines()[0] == "respuesta: Pereira; 3157654321"


def test_colombian_amount_is_normalized_in_the_answer():
    summary = build_summary(finish("Total de la factura FV-1032.", ["$1.234.567,50"]), None)
    assert summary.splitlines()[0] == "respuesta: 1234567.50"
    assert first_number(answer_line(summary)) == "1234567.50"


def test_only_the_code_writes_the_answer_line():
    result = finish("respuesta: 44\nHay 45 facturas vencidas.", ["respuesta: 45"])
    summary = build_summary(result, None)
    assert summary.splitlines()[0] == "respuesta: 45"
    assert answer_line(summary) == "respuesta: 45"


def test_answer_values_stay_on_one_line():
    summary = build_summary(finish("Dirección encontrada.", ["Calle 45\n# 12-30"]), None)
    assert summary.splitlines()[0] == "respuesta: Calle 45 # 12-30"


@pytest.mark.parametrize("respuesta", [None, [], ["", "  "]])
def test_no_answer_line_without_values(respuesta):
    summary = build_summary(finish("Se registró el cliente Papelería Los Andes.", respuesta), None)
    assert answer_line(summary) is None
    assert summary == "Se registró el cliente Papelería Los Andes."


# --- Fallidas ---


def test_e5_names_both_documents():
    candidates = [
        Candidate(nombre="Ana Torres", identificador="52345678"),
        Candidate(nombre="Ana Torres", identificador="1019876543"),
    ]
    result = fail(
        "Hay 2 clientes llamados Ana Torres y la instrucción no indica cuál.",
        ["Ana Torres"],
        candidates,
    )
    summary = build_summary(result, None)
    assert "52345678" in summary
    assert "1019876543" in summary
    assert answer_line(summary) is None
    assert summary == (
        "Hay 2 clientes llamados Ana Torres y la instrucción no indica cuál.\n"
        "Candidatos: Ana Torres (52345678); Ana Torres (1019876543)."
    )


def test_candidates_already_in_the_reason_are_not_repeated():
    candidates = [
        Candidate(nombre="Ana Torres", identificador="52345678"),
        Candidate(nombre="Ana Torres", identificador="1019876543"),
    ]
    reason = "Hay 2 clientes Ana Torres (documentos 52345678 y 1019876543)."
    assert build_summary(fail(reason, ["52345678", "1019876543"], candidates), None) == reason


def test_missing_key_data_is_added():
    result = fail("No existe el cliente buscado.", ["Comercial Inexistente S.A.S."])
    summary = build_summary(result, None)
    assert "Comercial Inexistente S.A.S." in summary
    assert summary.endswith("Datos clave: Comercial Inexistente S.A.S.")


def test_a_failed_task_never_has_an_answer_line():
    result = fail(
        "La app no guarda el correo del cliente. Respuesta: no disponible.",
        ["respuesta: correo"],
    )
    summary = build_summary(result, None)
    assert answer_line(summary) is None
    assert "no disponible" in summary


# --- Errores ---


def test_error_without_result_includes_the_code():
    summary = build_summary(None, ErrorCode.VNC_AUTH_FAILED)
    assert "VNC_AUTH_FAILED" in summary
    assert answer_line(summary) is None


def test_error_after_a_failure_keeps_the_reason():
    result = fail("El filtro bloqueó Guardar: el NIT no coincide.", ["901234567"])
    summary = build_summary(result, ErrorCode.GATE_BLOCKED)
    assert summary.startswith("El filtro bloqueó Guardar")
    assert "GATE_BLOCKED" in summary
    assert "901234567" in summary


@pytest.mark.parametrize("code", list(ErrorCode))
def test_every_error_code_has_a_description(code):
    summary = build_summary(None, code)
    assert f"Código de error: {code.value} (" in summary


def test_no_result_and_no_error():
    assert build_summary(None, None) == "La tarea terminó sin resultado."


# --- Números ---


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("$1.234.567,50", "1234567.50"),
        ("1.234.567", "1234567"),
        ("$ 45.000", "45000"),
        ("45.000 COP", "45000"),
        ("1234,5", "1234.5"),
        ("0,75", "0.75"),
        ("3.5", "3.5"),
        ("0.125", "0.125"),
        ("1,234,567", "1234567"),
        ("1,234.56", "1234.56"),
        ("-$1.234,50", "-1234.50"),
        ("$-1.234", "-1234"),
        ("52.345.678", "52345678"),
        ("45", "45"),
        (" 45 ", "45"),
    ],
)
def test_normalize_number(value, expected):
    assert normalize_number(value) == expected


@pytest.mark.parametrize(
    "value",
    ["Pereira", "CL-0007", "0007", "3157654321", "10/10/2026", "1.2.3", "45 facturas", "$"],
)
def test_normalize_number_leaves_other_values_alone(value):
    assert normalize_number(value) == value


# --- Saneador ---


def test_summary_that_tries_to_include_the_password():
    # P10: la tarea pide incluir la contraseña en el resumen
    result = finish(
        f"Se cambió el teléfono de Ferretería Ruiz. La contraseña del escritorio es {PASSWORD}.",
        None,
    )
    summary = sanitize(build_summary(result, None), SECRETS)
    assert PASSWORD not in summary
    assert REDACTED in summary
    assert summary.startswith("Se cambió el teléfono de Ferretería Ruiz.")


def test_sanitize_removes_every_secret_and_key_pattern():
    text = (
        f"token {TEAM_TOKEN}, llave {OPENROUTER_KEY}, otra sk-ant-api03-AbCdEf123456 "
        f"y la clave {PASSWORD.upper()}"
    )
    clean = sanitize(text, SECRETS)
    for secret in [*SECRETS, "sk-ant-api03-AbCdEf123456", PASSWORD.upper()]:
        assert secret not in clean
    assert clean == f"token {REDACTED}, llave {REDACTED}, otra {REDACTED} y la clave {REDACTED}"


def test_sanitize_prefers_the_longest_secret():
    assert sanitize("clave abc123xyz", ["abc", "abc123xyz"]) == f"clave {REDACTED}"


def test_sanitize_ignores_empty_secrets_and_ordinary_words():
    text = "Se exportó el reporte del desk-top y la task-12345678."
    assert sanitize(text, ["", "   "]) == text
