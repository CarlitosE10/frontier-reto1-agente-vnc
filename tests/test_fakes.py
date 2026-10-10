"""Dobles de prueba (plan, sección 2.4)."""

import pytest

from app.llm.openrouter import LLMError
from app.models import ErrorCode
from app.vnc.client import DesktopError
from tests.fakes import FakeDesktop, FakeLLM, tool_call, write_screen


@pytest.fixture
def screens(tmp_path):
    return [
        write_screen(tmp_path / "lista.png", "white"),
        write_screen(tmp_path / "formulario.png", "gray"),
    ]


async def test_fake_desktop_serves_screens_and_records_actions(screens):
    async with FakeDesktop(screens) as desktop:
        assert desktop.size == (1280, 800)
        first = await desktop.screenshot()
        assert first.getpixel((0, 0)) == (255, 255, 255)

        await desktop.click(100, 200)
        assert (await desktop.settle(first)).getpixel((0, 0)) == (128, 128, 128)

        await desktop.type_text("Papelería #1")
        await desktop.press("enter")
        await desktop.scroll(640, 400, "down", 3)
        assert (await desktop.screenshot()).getpixel((0, 0)) == (128, 128, 128)

    assert desktop.connected is False
    assert desktop.actions == [
        ("click", {"x": 100, "y": 200, "double": False}),
        ("type_text", {"text": "Papelería #1"}),
        ("press", {"combo": "enter"}),
        ("scroll", {"x": 640, "y": 400, "direction": "down", "amount": 3}),
    ]


async def test_fake_desktop_rejects_use_outside_the_session(screens):
    desktop = FakeDesktop(screens)
    with pytest.raises(DesktopError) as error:
        await desktop.screenshot()
    assert error.value.code is ErrorCode.WS_DISCONNECTED

    async with desktop:
        pass
    with pytest.raises(DesktopError):
        await desktop.click(1, 1)
    assert desktop.actions == []


def test_fake_desktop_needs_a_screen():
    with pytest.raises(ValueError):
        FakeDesktop([])


async def test_fake_llm_follows_the_script():
    finish = tool_call("finish_task", {"resumen": "Listo"}, cost_usd=0.002)
    llm = FakeLLM([tool_call("click", {"x": 1, "y": 2}), LLMError(), finish])

    first = await llm.chat("modelo", [{"role": "user", "content": "hola"}], [])
    assert (first.tool_name, first.arguments) == ("click", {"x": 1, "y": 2})
    with pytest.raises(LLMError) as error:
        await llm.chat("modelo", [], [])
    assert error.value.code is ErrorCode.VLM_ERROR
    assert await llm.chat("modelo", [], []) is finish

    assert llm.remaining == 0
    assert len(llm.calls) == 3
    assert llm.calls[0]["messages"] == [{"role": "user", "content": "hola"}]
    with pytest.raises(AssertionError):
        await llm.chat("modelo", [], [])
