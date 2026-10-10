"""Ejecutor de tareas: candados por escritorio, presupuesto y cancelación (se implementa en T10)."""

from app.config import Settings
from app.models import TaskRecord, TaskRequest


class TaskRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def submit(self, request: TaskRequest) -> str:
        """Registra la tarea y la lanza en segundo plano. No toca VNC; devuelve el task_id."""
        raise NotImplementedError

    def get(self, task_id: str) -> TaskRecord | None:
        raise NotImplementedError
