"""Esquemas de herramientas del VLM y parseo de sus acciones (se implementa en T06)."""

from app.models import Action

TOOLS: list[dict] = []  # esquemas JSON en formato OpenAI tools


def parse_action(
    name: str, arguments: dict, screen_size: tuple[int, int], coord_mode: str
) -> Action:
    raise NotImplementedError
