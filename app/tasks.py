"""Ejecutor de tareas (plan, T10): registro en memoria, candado por escritorio, presupuesto y
cancelación.

Cada tarea corre en su propio `asyncio.Task`. Una tarea nueva en un escritorio cancela a la
anterior y espera su candado, así que nunca hay dos sesiones VNC sobre la misma pantalla. El estado
final se publica solo después de que el agente se detuvo (y, con eso, se desconectó).
"""

import asyncio
import logging
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial

from app.agent.gate import Gate
from app.agent.loop import run_agent
from app.agent.summary import build_summary
from app.config import Settings
from app.llm.openrouter import LLMError, OpenRouterClient
from app.models import AgentResult, ErrorCode, TaskRecord, TaskRequest, TaskStatus
from app.tracing import Trace
from app.vnc.client import DesktopError, DesktopSession

logger = logging.getLogger(__name__)

# Firma de `run_agent` (plan, 2.3). Se inyecta para probar el ejecutor con un agente simulado.
Agent = Callable[
    [
        TaskRecord,
        Callable[[], DesktopSession],
        OpenRouterClient,
        Gate,
        Trace,
        asyncio.Event,
        Settings,
    ],
    Awaitable[AgentResult],
]

# El agente respeta TASK_TIME_BUDGET_S por su cuenta. Este margen es el tope duro por si no lo
# hace: 270 + 15 = 285 s, antes de que el evaluador deje de consultar a los 300 s.
TIMEOUT_MARGIN_S = 15.0


def task_secrets(record: TaskRecord, settings: Settings) -> list[str]:
    """Valores que nunca pueden aparecer en un resumen ni en una traza."""
    values = [
        record.request.escritorio.password.get_secret_value(),
        settings.team_token.get_secret_value(),
        settings.openrouter_api_key.get_secret_value(),
    ]
    return [value for value in values if value]


@dataclass
class _Job:
    record: TaskRecord
    trace: Trace
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] = field(init=False)

    @property
    def desktop(self) -> str:
        return self.record.request.escritorio.url


class TaskRunner:
    def __init__(
        self,
        settings: Settings,
        agent: Agent = run_agent,
        timeout_margin_s: float = TIMEOUT_MARGIN_S,
    ) -> None:
        self.settings = settings
        self._agent = agent
        self._timeout_s = settings.task_time_budget_s + timeout_margin_s
        self._llm = OpenRouterClient(settings)
        self._jobs: dict[str, _Job] = {}
        self._active: dict[str, _Job] = {}  # escritorio → la última tarea que lo pidió
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def submit(self, request: TaskRequest) -> str:
        """Registra la tarea y la lanza en segundo plano. No toca VNC; devuelve el task_id."""
        record = TaskRecord(id=uuid.uuid4().hex, request=request, progress="Tarea recibida")
        secrets = task_secrets(record, self.settings)
        job = _Job(record, Trace(record.id, self.settings.trace_dir, secrets))

        previous = self._active.get(job.desktop)
        if previous is not None:
            previous.cancel.set()
            previous.task.cancel()

        self._jobs[record.id] = job
        self._active[job.desktop] = job
        job.task = asyncio.create_task(self._run(job))
        logger.info("tarea recibida", extra={"task_id": record.id})
        return record.id

    def get(self, task_id: str) -> TaskRecord | None:
        job = self._jobs.get(task_id)
        return job.record if job else None

    def trace(self, task_id: str) -> Trace | None:
        job = self._jobs.get(task_id)
        return job.trace if job else None

    async def _run(self, job: _Job) -> None:
        try:
            result = await asyncio.wait_for(self._run_locked(job), self._timeout_s)
        except TimeoutError:
            self._fail(job, ErrorCode.BUDGET_EXHAUSTED)
        except asyncio.CancelledError:
            self._fail(job, ErrorCode.CANCELLED)
            raise
        except (DesktopError, LLMError) as error:
            self._fail(job, error.code)
        except Exception:
            logger.exception("el agente falló", extra={"task_id": job.record.id})
            self._fail(job, None)
        else:
            self._close(job, result.status, result.summary, result.error_code, result.cost_usd)
        finally:
            job.cancel.set()
            if self._active.get(job.desktop) is job:
                del self._active[job.desktop]

    async def _run_locked(self, job: _Job) -> AgentResult:
        # Si otra tarea tiene el escritorio, ya fue cancelada en `submit`: aquí se espera a que
        # termine de detenerse y desconectarse.
        async with self._locks[job.desktop]:
            job.record.progress = "Conectando con el escritorio"
            password = job.record.request.escritorio.password.get_secret_value()
            desktop_factory = partial(DesktopSession, job.desktop, password, self.settings)
            gate = Gate(self._llm, self.settings)
            return await self._agent(
                job.record, desktop_factory, self._llm, gate, job.trace, job.cancel, self.settings
            )

    def _fail(self, job: _Job, code: ErrorCode | None) -> None:
        self._close(job, TaskStatus.FALLIDA, build_summary(None, code), code, job.record.cost_usd)

    def _close(
        self,
        job: _Job,
        status: TaskStatus,
        summary: str,
        code: ErrorCode | None,
        cost_usd: float,
    ) -> None:
        record = job.record
        record.status = status
        record.summary = summary
        record.error_code = code
        record.cost_usd = cost_usd
        logger.info(
            "tarea finalizada",
            extra={
                "task_id": record.id,
                "estado": status.value,
                "error_code": code.value if code else None,
                "cost_usd": cost_usd,
                "duracion_s": round((datetime.now(UTC) - record.created_at).total_seconds(), 3),
            },
        )
