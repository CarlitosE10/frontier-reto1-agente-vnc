"""Trazas por tarea y logs del servidor en JSON (plan, T11).

Cada tarea escribe en `TRACE_DIR/<task_id>/`: `trace.jsonl`, con una línea por paso, y las capturas
PNG. Todo texto pasa por `sanitize` antes de llegar al disco.
"""

import json
import logging
import re
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic_core import to_jsonable_python

from app.agent.summary import sanitize

TRACE_FILE = "trace.jsonl"


class Trace:
    """La carpeta de la tarea se crea con la primera escritura."""

    def __init__(self, task_id: str, root: Path, secrets: list[str]) -> None:
        self.task_id = task_id
        self.root = root
        self.dir = Path(root) / task_id
        self._secrets = [secret for secret in secrets if secret]
        self._started = time.monotonic()
        self._screens = 0

    def step(self, **fields: Any) -> None:
        """Agrega una línea JSONL saneada, con la hora (`ts`) y los segundos desde que se recibió la
        tarea (`elapsed_s`).

        Por paso, el ciclo del agente registra `paso`, `captura`, `accion`, `observacion`,
        `verificacion`, `diff_pct`, `latencias`, `cost_usd` y `error_code`. Los valores pueden ser
        modelos de Pydantic, enums o rutas.
        """
        entry = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "elapsed_s": round(time.monotonic() - self._started, 3),
            **fields,
        }
        clean = self._sanitize(to_jsonable_python(entry, fallback=str))
        self.dir.mkdir(parents=True, exist_ok=True)
        with (self.dir / TRACE_FILE).open("a", encoding="utf-8") as file:
            file.write(json.dumps(clean, ensure_ascii=False) + "\n")

    def screenshot(self, image: Image.Image, label: str) -> str:
        """Guarda la captura como `NNN-<label>.png` y devuelve su ruta."""
        self._screens += 1
        path = self.dir / f"{self._screens:03d}-{_slug(sanitize(label, self._secrets))}.png"
        self.dir.mkdir(parents=True, exist_ok=True)
        image.save(path)
        return str(path)

    def read(self) -> list[dict]:
        try:
            lines = (self.dir / TRACE_FILE).read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        steps = []
        for line in lines:
            try:
                steps.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # una línea a medio escribir, si el proceso murió escribiéndola
        return steps

    def _sanitize(self, value: Any) -> Any:
        # Texto por texto y no sobre el JSON ya armado: ahí un secreto con comillas o barras
        # aparecería escapado y no se encontraría.
        if isinstance(value, str):
            return sanitize(value, self._secrets)
        if isinstance(value, dict):
            return {self._sanitize(key): self._sanitize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._sanitize(item) for item in value]
        return value


def _slug(label: str) -> str:
    """`Búsqueda: Ana Torres` pasa a `busqueda-ana-torres`."""
    ascii_label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_label.lower())[:40].strip("-") or "captura"


# --- Logs del servidor ---------------------------------------------------------------------------

# Atributos propios de un LogRecord. Lo demás llegó por `extra` y va como campo de la línea.
# `color_message` es un extra de uvicorn con códigos de color.
_RECORD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "color_message"}


class JsonFormatter(logging.Formatter):
    """Una línea JSON por registro: `ts`, `level`, `logger`, `msg`, los `extra` y `exc`."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        entry.update({k: v for k, v in vars(record).items() if k not in _RECORD_ATTRS})
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_logging(level: int | str = logging.INFO) -> None:
    """Manda todos los logs, incluidos los de uvicorn, a stderr en JSON.

    Se llama al arrancar la app: uvicorn ya instaló sus handlers y aquí se reemplazan.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
