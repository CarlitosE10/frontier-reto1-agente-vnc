"""Resumen final, normalización de números y saneador de secretos (se implementa en T07)."""

from app.models import ErrorCode, FailTask, FinishTask


def build_summary(result: FinishTask | FailTask | None, error_code: ErrorCode | None) -> str:
    raise NotImplementedError


def normalize_number(value: str) -> str:
    raise NotImplementedError


def sanitize(text: str, secrets: list[str]) -> str:
    raise NotImplementedError
