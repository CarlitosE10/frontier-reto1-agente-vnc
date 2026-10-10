"""Rutas HTTP y autenticación Bearer (plan, T10; contrato en el diseño, sección 2.9).

Las rutas toman el `TaskRunner` de `app.state.runner`, que se arma al crear la app.
"""

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.agent.summary import sanitize
from app.models import TaskRequest, TaskStatus
from app.tasks import TaskRunner, task_secrets

router = APIRouter()

_bearer = HTTPBearer(auto_error=False)


class TaskCreated(BaseModel):
    task_id: str


class TaskView(BaseModel):
    estado: TaskStatus
    resumen: str


def get_runner(request: Request) -> TaskRunner:
    return request.app.state.runner


Runner = Annotated[TaskRunner, Depends(get_runner)]


def require_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    runner: Runner,
) -> None:
    expected = runner.settings.team_token.get_secret_value().encode()
    # En bytes: compare_digest no acepta str con caracteres fuera de ASCII.
    given = credentials.credentials.encode() if credentials else b""
    if not secrets.compare_digest(given, expected):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Token inválido o ausente",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get("/health", response_model=None)
async def health(request: Request) -> JSONResponse:
    """Sin token, para el health check de la plataforma. 503 mientras la app no tenga ejecutor."""
    ready = getattr(request.app.state, "runner", None) is not None
    code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse({"ok": ready}, code)


@router.post("/tasks", dependencies=[Depends(require_token)])
async def create_task(body: TaskRequest, runner: Runner) -> TaskCreated:
    return TaskCreated(task_id=runner.submit(body))


@router.get("/tasks/{task_id}", dependencies=[Depends(require_token)])
async def read_task(task_id: str, runner: Runner) -> TaskView:
    record = runner.get(task_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La tarea no existe")
    text = record.progress if record.status is TaskStatus.EN_CURSO else record.summary
    # El agente ya sanea el resumen; esta es la última barrera antes de que salga.
    resumen = sanitize(text, task_secrets(record, runner.settings))
    return TaskView(estado=record.status, resumen=resumen)


@router.get("/tasks/{task_id}/traza", dependencies=[Depends(require_token)])
async def read_trace(task_id: str, runner: Runner) -> list[dict]:
    trace = runner.trace(task_id)
    if trace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La tarea no existe")
    return trace.read()
