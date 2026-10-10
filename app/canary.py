"""Canario (plan, T17; diseño, sección 2.8): una tarea de solo lectura cada CANARY_INTERVAL_S contra
el escritorio propio, para detectar en minutos que la app cambió o que algo dejó de funcionar.

Corre dentro del servicio, por el mismo `TaskRunner` que atiende al evaluador, así que prueba el
camino completo: puente, VNC, VLM, verificación y resumen. Si la tarea no termina `terminada` (o
el resumen no trae CANARY_EXPECTED), registra `ALERTA canario` con el código de error. El
diagnóstico sigue en `GET /tasks/{task_id}/traza`.

Está apagado por defecto (CANARY_INTERVAL_S=0): usa el mismo escritorio que el arnés y que las
pruebas locales, y dos agentes sobre una pantalla se pisan. Se enciende en el despliegue cuando no
hay corridas locales.

Una sola corrida, sin el servicio (para el runbook o para simular una falla):
  uv run python -m app.canary
"""

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass

from app.agent.summary import sanitize
from app.config import Settings
from app.models import Desktop, ErrorCode, TaskRequest, TaskStatus
from app.tasks import TIMEOUT_MARGIN_S, TaskRunner, task_secrets
from app.tracing import configure_logging

logger = logging.getLogger(__name__)

POLL_S = 1.0
FIRST_RUN_DELAY_S = 60.0  # deja terminar el arranque y el health check antes de la primera corrida
WAIT_MARGIN_S = 30.0  # sobre el tope duro del ejecutor, por si la tarea tarda en publicarse


@dataclass
class CanaryResult:
    ok: bool
    task_id: str
    status: TaskStatus
    error_code: ErrorCode | None
    summary: str
    cost_usd: float
    duration_s: float


def enabled(settings: Settings) -> bool:
    return (
        settings.canary_interval_s > 0
        and bool(settings.canary_desktop_url)
        and bool(settings.canary_task)
    )


async def canary_once(runner: TaskRunner, settings: Settings) -> CanaryResult:
    """Lanza la tarea del canario, espera el resultado y lo registra: INFO si salió bien, ERROR con
    `ALERTA canario` si no."""
    request = TaskRequest(
        tarea=settings.canary_task,
        escritorio=Desktop(
            url=settings.canary_desktop_url, password=settings.canary_desktop_password
        ),
    )
    started = time.monotonic()
    task_id = runner.submit(request)
    record = runner.get(task_id)
    assert record is not None
    deadline = started + settings.task_time_budget_s + TIMEOUT_MARGIN_S + WAIT_MARGIN_S
    while record.status is TaskStatus.EN_CURSO and time.monotonic() < deadline:
        await asyncio.sleep(POLL_S)

    summary = sanitize(record.summary, task_secrets(record, settings))
    ok = record.status is TaskStatus.TERMINADA and (
        not settings.canary_expected or settings.canary_expected.lower() in summary.lower()
    )
    result = CanaryResult(
        ok=ok,
        task_id=task_id,
        status=record.status,
        error_code=record.error_code,
        summary=summary,
        cost_usd=record.cost_usd,
        duration_s=round(time.monotonic() - started, 1),
    )
    fields = {
        "task_id": task_id,
        "estado": result.status.value,
        "error_code": result.error_code.value if result.error_code else None,
        "cost_usd": result.cost_usd,
        "duracion_s": result.duration_s,
    }
    if ok:
        logger.info("canario ok", extra=fields)
    else:
        logger.error("ALERTA canario", extra={**fields, "resumen": summary[:300]})
    return result


async def run_canary(runner: TaskRunner, settings: Settings) -> None:
    """Bucle del servicio: la primera corrida a los FIRST_RUN_DELAY_S y luego cada intervalo. Un
    error inesperado del canario se registra y no lo detiene; la cancelación sí (al apagar)."""
    await asyncio.sleep(FIRST_RUN_DELAY_S)
    while True:
        try:
            await canary_once(runner, settings)
        except Exception:
            logger.exception("ALERTA canario: el canario mismo falló")
        await asyncio.sleep(settings.canary_interval_s)


async def _main(settings: Settings) -> int:
    runner = TaskRunner(settings)
    try:
        result = await canary_once(runner, settings)
    finally:
        await runner.aclose()
    code = result.error_code.value if result.error_code else "-"
    print(f"canario: {'OK' if result.ok else 'ALERTA'} · {result.status.value} · {code}")
    print(f"task_id {result.task_id} · {result.duration_s} s · US${result.cost_usd:.4f}")
    print(result.summary)
    return 0 if result.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.canary", description=__doc__)
    parser.parse_args(argv)
    settings = Settings()
    if not settings.canary_desktop_url or not settings.canary_task:
        parser.error("faltan CANARY_DESKTOP_URL o CANARY_TASK")
    configure_logging()
    return asyncio.run(_main(settings))


if __name__ == "__main__":
    sys.exit(main())
