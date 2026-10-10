"""Trazas por tarea: JSONL saneado y capturas PNG (se implementa en T11)."""

from pathlib import Path

from PIL import Image


class Trace:
    def __init__(self, task_id: str, root: Path, secrets: list[str]) -> None:
        self.task_id = task_id
        self.root = root
        self._secrets = secrets

    def step(self, **fields) -> None:
        """Agrega una línea JSONL saneada."""
        raise NotImplementedError

    def screenshot(self, image: Image.Image, label: str) -> str:
        raise NotImplementedError

    def read(self) -> list[dict]:
        raise NotImplementedError
