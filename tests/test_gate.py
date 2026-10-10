"""Filtro de acciones irreversibles (plan, T08): reglas, verificación con FakeLLM y E5 en vivo."""

import base64
import io

import pytest
from PIL import Image

from app.agent.gate import (
    MAX_EVIDENCE_CHARS,
    VERIFY_ACTION_TOOL,
    VERIFY_ANSWER_TOOL,
    VERIFY_TASK_TOOL,
    Gate,
    is_irreversible,
    mark_action,
)
from app.agent.prompts import VERIFY_ACTION_PROMPT, VERIFY_COMPLETION_PROMPT
from app.config import Settings
from app.llm.openrouter import ChatResult, LLMError, OpenRouterClient
from app.models import (
    Click,
    Effect,
    FailTask,
    FinishTask,
    PressKey,
    Scroll,
    TypeText,
    Wait,
)
from tests.fakes import FakeLLM, tool_call
from tests.screens import (
    E5_FORM_OCR,
    E5_SAVE_BUTTON,
    E5_SEARCH_OCR,
    E5_TASK,
    e5_edit_form,
)
from tests.test_openrouter import live_settings

KEYWORDS = Settings.model_fields["irreversible_keywords"].default
TASK = "Cambia el teléfono de Ana Torres con cédula 52345678 a 3014445566."
SCREEN = Image.new("RGB", (1280, 800), "white")
SAVE = Click(
    observacion="EL_AGENTE_CREE_QUE_ESTA_BIEN",
    x=630,
    y=442,
    objetivo="Guardar",
    efecto=Effect.GUARDAR,
)
ALL_YES = {"dentro_de_tarea": True, "registro_correcto": True, "valores_correctos": True}


def click(efecto: Effect = Effect.NAVEGAR) -> Click:
    return Click(observacion="", x=10, y=10, objetivo="botón", efecto=efecto)


def verdict(
    razon: str = "Coincide con la tarea.", cost_usd: float = 0.0005, **checks: bool | str
) -> ChatResult:
    return tool_call("verificar", {"razon": razon, **checks}, cost_usd=cost_usd)


@pytest.fixture
def settings():
    return Settings(_env_file=None, team_token="t", openrouter_api_key="k", verify_enabled=True)


def user_text(call: dict) -> str:
    return call["messages"][1]["content"][0]["text"]


def sent_image(call: dict) -> Image.Image:
    url = call["messages"][1]["content"][1]["image_url"]["url"]
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")


# --- is_irreversible -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "words", "in_form", "expected"),
    [
        (click(Effect.GUARDAR), [], False, True),
        (click(Effect.EXPORTAR), [], False, True),
        (click(Effect.ELIMINAR), [], False, True),
        (click(Effect.EDITAR), [], True, False),
        (click(), ["Buscar", "cliente"], False, False),
        (click(), ["[Guardar]"], False, True),
        (click(), ["Exportar CSV"], False, True),
        (click(), ["¿Desea", "continuar?", "Sí,"], False, True),
        (click(), ["Si"], False, True),  # el OCR a veces pierde la tilde
        (click(), ["GUARDARLO"], False, True),
        (click(), ["Registro", "de", "clientes"], False, False),  # registro no es registrar
        (click(), ["así", "aparece"], False, False),  # «sí» solo como palabra completa
        (PressKey(observacion="", combinacion="enter"), [], True, True),
        (PressKey(observacion="", combinacion="Return"), [], True, True),
        (PressKey(observacion="", combinacion="ctrl+Enter"), [], True, True),
        (PressKey(observacion="", combinacion="enter"), [], False, False),
        (PressKey(observacion="", combinacion="enter"), ["Aceptar"], False, True),
        (PressKey(observacion="", combinacion="tab"), ["Guardar"], True, False),
        (TypeText(observacion="", texto="Papelería #1", campo="Nombre"), [], True, False),
        (TypeText(observacion="", texto="3014445566\n", campo="Teléfono"), [], True, True),
        (Scroll(observacion="", x=1, y=1, direccion="down", cantidad=3), ["Guardar"], True, False),
        (Wait(observacion="", segundos=1), ["Guardar"], True, False),
        (FinishTask(observacion="", resumen="", evidencia=""), ["Guardar"], True, False),
        (FailTask(observacion="", razon="", datos_clave=[]), ["Guardar"], True, False),
    ],
)
def test_is_irreversible(action, words, in_form, expected):
    assert is_irreversible(action, words, in_form, KEYWORDS) is expected


def test_keywords_come_from_the_parameter():
    assert is_irreversible(click(), ["Procesar"], False, ["procesar"]) is True
    assert is_irreversible(click(), ["Guardar"], False, []) is False
    assert is_irreversible(click(), ["Aceptar", "todo"], False, ["aceptar todo"]) is True
    assert is_irreversible(click(), ["Aceptar"], False, ["aceptar todo"]) is False


# --- check_action --------------------------------------------------------------------------


async def test_approves_when_all_checks_pass(settings):
    llm = FakeLLM([verdict(**ALL_YES)])
    gate = Gate(llm, settings)

    decision = await gate.check_action(TASK, SAVE, SCREEN, "Teléfono 3014445566", ["listado"])

    assert decision.outcome == "approve"
    assert decision.checks == ALL_YES
    assert decision.reason == "Coincide con la tarea."
    assert gate.cost_usd == pytest.approx(0.0005)

    [call] = llm.calls
    assert call["model"] == settings.vlm_model
    assert call["tools"] == [VERIFY_ACTION_TOOL]
    # Contexto limpio: solo el prompt de verificación y un mensaje con los datos.
    assert [m["role"] for m in call["messages"]] == ["system", "user"]
    assert call["messages"][0]["content"] == VERIFY_ACTION_PROMPT
    text = user_text(call)
    assert TASK in text
    assert "clic en (630, 442) sobre «Guardar»; efecto declarado: guardar" in text
    assert "Teléfono 3014445566" in text
    assert "listado" in text
    assert "EL_AGENTE_CREE_QUE_ESTA_BIEN" not in text


async def test_blocks_when_a_check_fails(settings):
    razon = "Hay dos Ana Torres (52345678 y 1019876543)."
    llm = FakeLLM([verdict(razon=razon, **{**ALL_YES, "registro_correcto": False})])

    decision = await Gate(llm, settings).check_action(TASK, SAVE, SCREEN, "", [])

    assert decision.outcome == "block"
    assert decision.checks["registro_correcto"] is False
    assert decision.reason == f"registro_correcto en no: {razon}"
    assert len(llm.calls) == 1


async def test_blocks_when_the_call_fails_twice(settings):
    llm = FakeLLM([LLMError(message="HTTP 503"), LLMError(message="HTTP 503")])

    decision = await Gate(llm, settings).check_action(TASK, SAVE, SCREEN, "", [])

    assert decision.outcome == "block"
    assert decision.checks is None
    assert "VLM_ERROR" in decision.reason
    assert len(llm.calls) == 2


async def test_retries_once_after_a_failed_call(settings):
    llm = FakeLLM([LLMError(), verdict(**ALL_YES)])

    decision = await Gate(llm, settings).check_action(TASK, SAVE, SCREEN, "", [])

    assert decision.outcome == "approve"
    assert len(llm.calls) == 2


@pytest.mark.parametrize(
    "bad",
    [
        tool_call("click", {"x": 1, "y": 2}),
        tool_call(None, {}),
        verdict(**{**ALL_YES, "registro_correcto": "no"}),
        tool_call("verificar", {"razon": "falta un chequeo", "dentro_de_tarea": True}),
    ],
)
async def test_invalid_verdicts_count_as_failures(settings, bad):
    gate = Gate(FakeLLM([bad, bad]), settings)

    decision = await gate.check_action(TASK, SAVE, SCREEN, "", [])

    assert decision.outcome == "block"
    assert decision.checks is None


async def test_verification_disabled_approves_without_calling(settings):
    llm = FakeLLM([])
    gate = Gate(llm, settings.model_copy(update={"verify_enabled": False}))
    finish = FinishTask(observacion="", resumen="Listo", evidencia="")

    action = await gate.check_action(TASK, SAVE, SCREEN, "", [])
    completion = await gate.check_completion(TASK, finish, SCREEN, "")

    assert action.outcome == completion.outcome == "approve"
    assert llm.calls == []
    assert gate.cost_usd == 0.0


async def test_click_point_is_marked_on_a_copy(settings):
    screen = Image.new("RGB", (1280, 800), "white")
    llm = FakeLLM([verdict(**ALL_YES)])

    await Gate(llm, settings).check_action(TASK, SAVE, screen, "", [])

    image = sent_image(llm.calls[0])
    assert image.size == (1280, 800)
    red = [image.getpixel((SAVE.x + dx, SAVE.y)) for dx in range(-18, 19)]
    assert any(r > 200 and g < 60 and b < 60 for r, g, b in red)
    assert screen.getpixel((SAVE.x + 16, SAVE.y)) == (255, 255, 255)  # original intacta


def test_actions_without_coordinates_are_not_marked():
    press = PressKey(observacion="", combinacion="enter")
    assert mark_action(SCREEN, press) is SCREEN


async def test_long_evidence_keeps_the_newest_screens(settings):
    evidence = [f"pantalla-{i} " + "x" * 3000 for i in range(10)]
    llm = FakeLLM([verdict(**ALL_YES)])

    await Gate(llm, settings).check_action(TASK, SAVE, SCREEN, "", evidence)

    text = user_text(llm.calls[0])
    assert "pantalla-9" in text
    assert "pantalla-0" not in text
    assert "más viejas omitidas" in text
    assert len(text) < MAX_EVIDENCE_CHARS + 2000


# --- check_completion ----------------------------------------------------------------------


async def test_completion_of_a_question_checks_the_answer(settings):
    llm = FakeLLM([verdict(respuesta_respaldada=True)])
    gate = Gate(llm, settings)
    finish = FinishTask(
        observacion="", resumen="Conté las vencidas", respuesta=["45"], evidencia="Total: 45"
    )

    decision = await gate.check_completion("¿Cuántas facturas vencidas hay?", finish, SCREEN, "45")

    assert decision.outcome == "approve"
    assert decision.checks == {"respuesta_respaldada": True}
    [call] = llm.calls
    assert call["tools"] == [VERIFY_ANSWER_TOOL]
    assert call["messages"][0]["content"] == VERIFY_COMPLETION_PROMPT
    assert "respuesta: 45" in user_text(call)


async def test_completion_of_a_change_checks_the_task(settings):
    razon = "La pantalla sigue mostrando el teléfono viejo."
    llm = FakeLLM([verdict(razon=razon, tarea_cumplida=False)])
    finish = FinishTask(observacion="", resumen="Cambié el teléfono", evidencia="Guardado")

    decision = await Gate(llm, settings).check_completion(TASK, finish, SCREEN, "3104567890")

    assert decision.outcome == "block"
    assert decision.reason == f"tarea_cumplida en no: {razon}"
    assert llm.calls[0]["tools"] == [VERIFY_TASK_TOOL]
    assert "respuesta: (ninguna)" in user_text(llm.calls[0])


async def test_completion_blocks_when_the_call_fails_twice(settings):
    llm = FakeLLM([LLMError(), LLMError()])
    finish = FinishTask(observacion="", resumen="Listo", evidencia="")

    decision = await Gate(llm, settings).check_completion(TASK, finish, SCREEN, "")

    assert decision.outcome == "block"
    assert len(llm.calls) == 2


# --- En vivo -------------------------------------------------------------------------------


async def live_check_save(task: str) -> tuple[object, float]:
    """Verifica "Guardar" sobre el formulario de Ana Torres (52345678), con las dos Ana Torres
    de la búsqueda en la evidencia."""
    settings = live_settings().model_copy(update={"verify_enabled": True})
    llm = OpenRouterClient(settings)
    gate = Gate(llm, settings)
    action = Click(
        observacion="El formulario tiene el teléfono nuevo; falta guardar.",
        x=(E5_SAVE_BUTTON[0] + E5_SAVE_BUTTON[2]) // 2,
        y=(E5_SAVE_BUTTON[1] + E5_SAVE_BUTTON[3]) // 2,
        objetivo="Guardar",
        efecto=Effect.GUARDAR,
    )
    try:
        decision = await gate.check_action(
            task, action, e5_edit_form(), E5_FORM_OCR, [E5_SEARCH_OCR, E5_FORM_OCR]
        )
    finally:
        await llm.aclose()
    print(
        f"\n[en vivo] decisión={decision.outcome} chequeos={decision.checks} "
        f"costo=US${gate.cost_usd:.6f}\nrazón: {decision.reason}"
    )
    return decision, gate.cost_usd


@pytest.mark.live
async def test_live_e5_save_on_a_homonym_is_blocked():
    """E5: la tarea no dice cuál de las dos Ana Torres."""
    decision, cost = await live_check_save(E5_TASK)

    assert decision.checks is not None
    assert decision.checks["registro_correcto"] is False
    assert decision.outcome == "block"
    assert cost < 0.002


@pytest.mark.live
async def test_live_p01_save_with_the_document_is_approved():
    """P01, contraparte de E5: la cédula de la tarea desempata, así que el filtro aprueba."""
    decision, cost = await live_check_save(TASK)

    assert decision.outcome == "approve"
    assert decision.checks == ALL_YES
    assert cost < 0.002
