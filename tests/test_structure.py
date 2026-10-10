"""La estructura del plan (sección 1) existe y todos los módulos se importan."""

import importlib

import pytest

MODULES = [
    "app.main",
    "app.api",
    "app.tasks",
    "app.config",
    "app.models",
    "app.tracing",
    "app.vnc.bridge",
    "app.vnc.client",
    "app.vnc.probe",
    "app.perception.diff",
    "app.perception.ocr",
    "app.llm.openrouter",
    "app.agent.tools",
    "app.agent.prompts",
    "app.agent.gate",
    "app.agent.summary",
    "app.agent.loop",
    "eval.harness",
    "eval.grounding",
    "tests.fakes",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)


def test_main_creates_fastapi_app():
    from fastapi import FastAPI

    from app.main import app

    assert isinstance(app, FastAPI)
