"""Resumen final, normalización de números y saneador de secretos (diseño, sección 2.4).

El resumen se arma en código a partir de los campos de `finish_task` y `fail_task`, no del
texto libre del modelo: así la línea `respuesta:` va primero en las preguntas y nunca aparece
en las fallidas, y los datos que explican una falla siempre quedan en el texto.
"""

import re

from app.models import ErrorCode, FailTask, FinishTask

REDACTED = "[oculto]"

_ERRORS = {
    ErrorCode.VNC_CONNECT_FAILED: "no se pudo conectar al escritorio",
    ErrorCode.VNC_AUTH_FAILED: "el escritorio rechazó la contraseña",
    ErrorCode.WS_DISCONNECTED: "se perdió la conexión con el escritorio",
    ErrorCode.SCREEN_NOT_STABLE: "la pantalla no se estabilizó",
    ErrorCode.CLICK_NO_EFFECT: "las acciones no produjeron cambios en la pantalla",
    ErrorCode.LOOP_DETECTED: "se repitió la misma acción sin avanzar",
    ErrorCode.VLM_ERROR: "el modelo no respondió",
    ErrorCode.GATE_BLOCKED: "la verificación bloqueó una acción irreversible",
    ErrorCode.BUDGET_EXHAUSTED: "se agotó el presupuesto de tiempo, pasos o costo",
    ErrorCode.CANCELLED: "una tarea nueva en el mismo escritorio interrumpió esta",
}

# Cualquier "respuesta:" que no sea la línea que arma el código
_ANSWER_LABEL = re.compile(r"(respuesta)\s*:", re.IGNORECASE)
_LEADING_ANSWER_LABEL = re.compile(r"^\s*respuesta\s*:\s*", re.IGNORECASE)
# Llaves con forma de API key (OpenRouter, Anthropic, OpenAI): sk-or-v1-…, sk-ant-…
_API_KEY = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{8,}")
# Un monto: signo y moneda opcionales, y dígitos con separadores
_AMOUNT = re.compile(
    r"(?P<sign>-?)\s*(?:US\$|\$|COP)?\s*(?P<inner_sign>-?)\s*(?P<number>\d(?:[\d.,]*\d)?)"
    r"\s*(?:COP)?",
    re.IGNORECASE,
)


def build_summary(result: FinishTask | FailTask | None, error_code: ErrorCode | None) -> str:
    """Resumen que se publica. No sanea: el ciclo le aplica `sanitize` después."""
    if isinstance(result, FinishTask):
        lines = _finished(result)
    elif isinstance(result, FailTask):
        lines = _failed(result)
    elif error_code is not None:
        lines = ["No se completó la tarea."]
    else:
        lines = ["La tarea terminó sin resultado."]
    if error_code is not None:
        lines.append(f"Código de error: {error_code.value} ({_ERRORS[error_code]}).")
    return "\n".join(lines)


def normalize_number(value: str) -> str:
    """`$1.234.567,50` pasa a `1234567.50`. Lo que no es un número queda igual.

    Se sigue el formato colombiano: el punto agrupa miles y la coma separa decimales. Si
    aparecen los dos, el último es el decimal. Un solo punto es de miles solo si agrupa de a
    tres (`45.000`); si no, es decimal (`3.5`). Los dígitos no se reinterpretan: `0007` sigue
    siendo `0007`.
    """
    match = _AMOUNT.fullmatch(value.strip())
    if match is None:
        return value
    parts = _split_number(match["number"])
    if parts is None:
        return value
    integer, decimals = parts
    sign = "-" if match["sign"] or match["inner_sign"] else ""
    return sign + integer + (f".{decimals}" if decimals is not None else "")


def sanitize(text: str, secrets: list[str]) -> str:
    """Reemplaza cada secreto (sin importar mayúsculas) y cada llave `sk-…` por `[oculto]`."""
    # Los más largos primero, por si un secreto contiene a otro
    for secret in sorted({s for s in secrets if s and s.strip()}, key=len, reverse=True):
        text = re.sub(re.escape(secret), REDACTED, text, flags=re.IGNORECASE)
    return _API_KEY.sub(REDACTED, text)


def _finished(result: FinishTask) -> list[str]:
    values = [_LEADING_ANSWER_LABEL.sub("", value) for value in result.respuesta or []]
    values = [_one_line(_drop_answer_labels(value)) for value in values]
    values = [normalize_number(value) for value in values if value]
    lines = [f"respuesta: {'; '.join(values)}"] if values else []
    body = _drop_answer_labels(result.resumen.strip())
    if body:
        lines.append(body)
    return lines or ["Tarea terminada."]


def _failed(result: FailTask) -> list[str]:
    lines = [result.razon.strip() or "No se pudo completar la tarea."]
    candidates = [c for c in result.candidatos if c.identificador.strip()]
    if any(c.identificador.strip() not in lines[0] for c in candidates):
        listed = "; ".join(f"{c.nombre.strip()} ({c.identificador.strip()})" for c in candidates)
        lines.append(_sentence(f"Candidatos: {listed}"))
    key_data = [d.strip() for d in result.datos_clave if d.strip()]
    if any(d not in "\n".join(lines) for d in key_data):
        lines.append(_sentence(f"Datos clave: {', '.join(key_data)}"))
    # Una fallida nunca lleva línea de respuesta, aunque el modelo la haya escrito
    return [_drop_answer_labels(line) for line in lines]


def _split_number(number: str) -> tuple[str, str | None] | None:
    """Parte entera sin separadores y parte decimal, o None si no tiene forma de número."""
    if "." in number and "," in number:
        decimal = "." if number.rfind(".") > number.rfind(",") else ","
        thousands = "," if decimal == "." else "."
        integer, _, decimals = number.rpartition(decimal)
        if not _grouped(integer, thousands) or not decimals.isdigit():
            return None
        return integer.replace(thousands, ""), decimals
    if "," in number:
        if number.count(",") == 1:
            integer, decimals = number.split(",")
            return integer, decimals
        return (number.replace(",", ""), None) if _grouped(number, ",") else None
    if "." in number:
        if _grouped(number, "."):
            return number.replace(".", ""), None
        if number.count(".") == 1:
            integer, decimals = number.split(".")
            return integer, decimals
        return None
    return number, None


def _grouped(integer: str, separator: str) -> bool:
    """`1.234.567` agrupa de a tres con `.`; `0.125` y `12.34` no."""
    return re.fullmatch(rf"[1-9]\d{{0,2}}(?:{re.escape(separator)}\d{{3}})+", integer) is not None


def _drop_answer_labels(text: str) -> str:
    return _ANSWER_LABEL.sub(r"\1", text)


def _sentence(text: str) -> str:
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _one_line(text: str) -> str:
    return " ".join(text.split())
