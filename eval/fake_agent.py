"""Agente simulado: cumple el contrato HTTP del agente sin operar el escritorio (plan T12).

Sirve para probar el arnés de punta a punta, incluido el `/__check` real, sin VNC ni modelos.
Después de `--delay` segundos reporta el estado esperado del caso cuya instrucción coincide, con
un resumen que pasa los chequeos locales. Como no toca la app, el `/__check` real solo pasa en los
casos que no esperan cambios.

Uso: uv run python -m eval.fake_agent [--port 8001] [--delay 6]
Exige como token `AGENT_TOKEN`, el mismo que envía el arnés.
"""

import argparse
import secrets
import time
import uuid
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import EvalSettings
from app.models import TaskRequest, TaskStatus
from eval.harness import CASES_DIR, Case, load_cases

PROGRESS = "Agente simulado: trabajando."
TRACE = [
    {"step": 1, "accion": "simulada", "cost_usd": 0.001},
    {"step": 2, "accion": "simulada", "cost_usd": 0.0015},
]


def simulated_outcome(case: Case | None) -> tuple[str, str]:
    """Estado y resumen que esperaría el arnés para `case`."""
    if case is None:
        return TaskStatus.FALLIDA, "Agente simulado: la tarea no corresponde a ningún caso."
    if case.expected == TaskStatus.FALLIDA:
        keys = ", ".join(str(key) for key in case.data.get("claves_razon", []))
        return TaskStatus.FALLIDA, f"Agente simulado: no se hizo ningún cambio. Datos: {keys}."
    lines = ["Agente simulado: no operó el escritorio."]
    if case.data.get("respuesta_esperada") is not None:
        lines.insert(0, f"respuesta: {case.data['respuesta_esperada']}")
    return TaskStatus.TERMINADA, "\n".join(lines)


def create_app(
    token: str,
    cases: list[Case],
    delay_s: float = 0.0,
    overrides: dict[str, tuple[str, str]] | None = None,
) -> FastAPI:
    """`overrides` cambia el (estado, resumen) final de una instrucción; con estado `en_curso`
    la tarea no termina nunca."""
    by_instruction = {case.instruccion: case for case in cases}
    overrides = overrides or {}
    tasks: dict[str, tuple[str, float]] = {}
    bearer = HTTPBearer(auto_error=False)

    def authorize(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        if credentials is None or not secrets.compare_digest(
            credentials.credentials.encode(), token.encode()
        ):
            raise HTTPException(status_code=401, detail="no autorizado")

    app = FastAPI(title="Agente simulado")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/tasks", dependencies=[Depends(authorize)])
    def submit(request: TaskRequest) -> dict:
        task_id = uuid.uuid4().hex
        tasks[task_id] = (request.tarea, time.monotonic())
        return {"task_id": task_id}

    @app.get("/tasks/{task_id}", dependencies=[Depends(authorize)])
    def status(task_id: str) -> dict:
        if task_id not in tasks:
            raise HTTPException(status_code=404, detail="tarea desconocida")
        tarea, started = tasks[task_id]
        if time.monotonic() - started < delay_s:
            return {"estado": TaskStatus.EN_CURSO, "resumen": PROGRESS}
        estado, resumen = overrides.get(tarea) or simulated_outcome(by_instruction.get(tarea))
        return {"estado": estado, "resumen": resumen}

    @app.get("/tasks/{task_id}/traza", dependencies=[Depends(authorize)])
    def trace(task_id: str) -> list[dict]:
        if task_id not in tasks:
            raise HTTPException(status_code=404, detail="tarea desconocida")
        return TRACE

    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m eval.fake_agent", description=__doc__)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--delay", type=float, default=6.0, help="segundos hasta el estado final")
    args = parser.parse_args(argv)
    token = EvalSettings().agent_token.get_secret_value()
    app = create_app(token, load_cases(CASES_DIR), args.delay)
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
