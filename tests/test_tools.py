"""Herramientas del VLM y `parse_action` (plan, T06)."""

import json

import pytest

from app.agent.tools import TOOLS, ActionError, parse_action
from app.models import (
    Candidate,
    Click,
    Effect,
    FailTask,
    FinishTask,
    PressKey,
    Scroll,
    TypeText,
    Wait,
)

SCREEN = (1280, 800)
OBS = {"observacion": "veo la lista de clientes"}


def parse(name, arguments, coord_mode="pixels"):
    return parse_action(name, {**OBS, **arguments}, SCREEN, coord_mode)


def tool(name):
    return next(t["function"] for t in TOOLS if t["function"]["name"] == name)


# --- Esquemas ---


def test_tool_names():
    assert [t["function"]["name"] for t in TOOLS] == [
        "click",
        "double_click",
        "type_text",
        "press_key",
        "scroll",
        "wait",
        "finish_task",
        "fail_task",
    ]


def test_tools_follow_the_openai_format_and_serialize():
    json.dumps(TOOLS)
    for entry in TOOLS:
        assert entry["type"] == "function"
        function = entry["function"]
        assert function["description"]
        parameters = function["parameters"]
        assert parameters["type"] == "object"
        assert set(parameters["required"]) <= set(parameters["properties"])


def test_every_tool_has_observacion_fecha_app_and_es_listado():
    for entry in TOOLS:
        parameters = entry["function"]["parameters"]
        assert "observacion" in parameters["required"]
        assert {"observacion", "fecha_app", "es_listado"} <= set(parameters["properties"])
        assert "fecha_app" not in parameters["required"]


@pytest.mark.parametrize("name", ["click", "double_click"])
def test_click_tools_declare_the_effect(name):
    parameters = tool(name)["parameters"]
    assert parameters["properties"]["efecto"]["enum"] == [e.value for e in Effect]
    assert set(parameters["required"]) == {"observacion", "x", "y", "objetivo", "efecto"}


@pytest.mark.parametrize(
    ("name", "required"),
    [
        ("type_text", {"texto", "campo"}),
        ("press_key", {"combinacion"}),
        ("scroll", {"x", "y", "direccion", "cantidad"}),
        ("wait", {"segundos"}),
        ("finish_task", {"resumen", "evidencia"}),
        ("fail_task", {"razon", "datos_clave"}),
    ],
)
def test_required_fields_follow_the_models(name, required):
    assert set(tool(name)["parameters"]["required"]) == {"observacion", *required}


def test_tool_schemas_avoid_null_unions():
    """Tipos simples para que los acepte cualquier proveedor de OpenRouter."""

    def types(node):
        if isinstance(node, dict):
            if "type" in node:
                yield node["type"]
            for value in node.values():
                yield from types(value)
        elif isinstance(node, list):
            for value in node:
                yield from types(value)

    assert all(isinstance(t, str) for t in types(TOOLS))


# --- Parseo de cada herramienta ---


def test_parse_click():
    action = parse(
        "click",
        {
            "x": 412,
            "y": 233,
            "objetivo": "botón Buscar",
            "efecto": "navegar",
            "fecha_app": "10/10/2026",
        },
    )
    assert action == Click(
        observacion=OBS["observacion"],
        fecha_app="10/10/2026",
        x=412,
        y=233,
        objetivo="botón Buscar",
        efecto=Effect.NAVEGAR,
        double=False,
    )


def test_parse_double_click_sets_double():
    action = parse("double_click", {"x": 1, "y": 2, "objetivo": "fila", "efecto": "navegar"})
    assert isinstance(action, Click)
    assert action.double is True


def test_click_ignores_a_double_flag_sent_by_the_model():
    action = parse(
        "click", {"x": 1, "y": 2, "objetivo": "fila", "efecto": "navegar", "double": True}
    )
    assert action.double is False


def test_parse_type_text_keeps_the_text_exact():
    action = parse("type_text", {"texto": " Papelería #1 ", "campo": "Nombre"})
    assert action == TypeText(
        observacion=OBS["observacion"], texto=" Papelería #1 ", campo="Nombre"
    )


@pytest.mark.parametrize(
    ("combo", "expected"), [("enter", "enter"), ("Ctrl + A", "ctrl+a"), (" ESC ", "esc")]
)
def test_parse_press_key_normalizes_the_combination(combo, expected):
    action = parse("press_key", {"combinacion": combo})
    assert action == PressKey(observacion=OBS["observacion"], combinacion=expected)


def test_parse_scroll():
    action = parse("scroll", {"x": 640, "y": 400, "direccion": "down", "cantidad": 3})
    assert action == Scroll(
        observacion=OBS["observacion"], x=640, y=400, direccion="down", cantidad=3
    )


def test_parse_wait():
    assert parse("wait", {"segundos": 1.5}) == Wait(observacion=OBS["observacion"], segundos=1.5)


def test_parse_finish_task_with_answer():
    action = parse(
        "finish_task",
        {"resumen": "Conté las facturas", "respuesta": ["45"], "evidencia": "Vencidas: 45"},
    )
    assert action == FinishTask(
        observacion=OBS["observacion"],
        resumen="Conté las facturas",
        respuesta=["45"],
        evidencia="Vencidas: 45",
    )


def test_parse_finish_task_without_answer():
    action = parse("finish_task", {"resumen": "Cliente creado", "evidencia": "Guardado"})
    assert action.respuesta is None


@pytest.mark.parametrize(
    ("respuesta", "expected"),
    [
        ("45", ["45"]),
        (45, ["45"]),
        ([45, " 3157654321 "], ["45", "3157654321"]),
        (["Pereira", "", "3157654321"], ["Pereira", "3157654321"]),
        ([], None),
        ("", None),
        (None, None),
    ],
)
def test_finish_task_answer_variations(respuesta, expected):
    action = parse("finish_task", {"resumen": "r", "respuesta": respuesta, "evidencia": "e"})
    assert action.respuesta == expected


def test_parse_fail_task_with_candidates():
    action = parse(
        "fail_task",
        {
            "razon": "Hay dos clientes llamados Ana Torres",
            "datos_clave": ["52345678", "1019876543"],
            "candidatos": [
                {"nombre": "Ana Torres", "identificador": "52345678"},
                {"nombre": "Ana Torres", "identificador": 1019876543},
            ],
        },
    )
    assert action == FailTask(
        observacion=OBS["observacion"],
        razon="Hay dos clientes llamados Ana Torres",
        datos_clave=["52345678", "1019876543"],
        candidatos=[
            Candidate(nombre="Ana Torres", identificador="52345678"),
            Candidate(nombre="Ana Torres", identificador="1019876543"),
        ],
    )


def test_fail_task_variations():
    action = parse("fail_task", {"razon": "r", "datos_clave": 900111222, "candidatos": None})
    assert action.datos_clave == ["900111222"]
    assert action.candidatos == []


@pytest.mark.parametrize("value", ["", "null", " NULL ", None])
def test_missing_app_date_becomes_none(value):
    action = parse("wait", {"segundos": 1, "fecha_app": value})
    assert action.fecha_app is None


def test_extra_fields_like_es_listado_are_ignored():
    action = parse("wait", {"segundos": 1, "es_listado": True, "kind": "click"})
    assert isinstance(action, Wait)


# --- Coordenadas ---


@pytest.mark.parametrize(
    ("x", "y", "expected"),
    [
        (0, 0, (0, 0)),
        (500, 500, (640, 400)),
        (1000, 1000, (1279, 799)),
        (250.2, 125, (320, 100)),
    ],
)
def test_norm1000_converts_to_real_pixels(x, y, expected):
    action = parse("click", {"x": x, "y": y, "objetivo": "o", "efecto": "navegar"}, "norm1000")
    assert (action.x, action.y) == expected


def test_norm1000_applies_to_scroll():
    action = parse(
        "scroll", {"x": 500, "y": 250, "direccion": "up", "cantidad": 1}, coord_mode="norm1000"
    )
    assert (action.x, action.y) == (640, 200)


def test_norm1000_uses_the_screen_size():
    action = parse_action(
        "click",
        {**OBS, "x": 500, "y": 500, "objetivo": "o", "efecto": "navegar"},
        (1920, 1080),
        "norm1000",
    )
    assert (action.x, action.y) == (960, 540)


@pytest.mark.parametrize(
    ("x", "y", "expected"),
    [(0, 0, (0, 0)), (1279, 799, (1279, 799)), (640.6, 399.4, (641, 399)), ("12", "34", (12, 34))],
)
def test_pixels_inside_the_screen(x, y, expected):
    action = parse("click", {"x": x, "y": y, "objetivo": "o", "efecto": "navegar"})
    assert (action.x, action.y) == expected


@pytest.mark.parametrize(
    ("coord_mode", "x", "y"),
    [
        ("pixels", 1280, 10),
        ("pixels", 10, 800),
        ("pixels", -1, 10),
        ("pixels", 1279.6, 10),
        ("norm1000", 1001, 10),
        ("norm1000", 10, -0.5),
    ],
)
def test_coordinates_outside_the_screen_are_rejected(coord_mode, x, y):
    with pytest.raises(ActionError, match="fuera"):
        parse("click", {"x": x, "y": y, "objetivo": "o", "efecto": "navegar"}, coord_mode)


@pytest.mark.parametrize("bad", [None, "centro", True, float("nan"), [1, 2]])
def test_coordinates_must_be_numbers(bad):
    arguments = {"y": 10, "objetivo": "o", "efecto": "navegar"}
    if bad is not None:
        arguments["x"] = bad
    with pytest.raises(ActionError, match="x"):
        parse("click", arguments)


def test_scroll_coordinates_are_checked():
    with pytest.raises(ActionError, match="fuera"):
        parse("scroll", {"x": 10, "y": 900, "direccion": "down", "cantidad": 1})


def test_unknown_coord_mode_is_a_programming_error():
    with pytest.raises(ValueError, match="VLM_COORD_MODE") as error:
        parse("wait", {"segundos": 1}, coord_mode="grid")
    assert not isinstance(error.value, ActionError)


# --- Errores de esquema ---


@pytest.mark.parametrize(
    ("name", "arguments", "message"),
    [
        ("drag", {}, "herramienta desconocida"),
        ("click", {"x": 1, "y": 2, "efecto": "navegar"}, "objetivo"),
        ("click", {"x": 1, "y": 2, "objetivo": "o", "efecto": "borrar"}, "efecto"),
        ("type_text", {"texto": "hola"}, "campo"),
        ("press_key", {}, "combinacion"),
        ("press_key", {"combinacion": "   "}, "combinacion"),
        ("scroll", {"x": 1, "y": 2, "direccion": "left", "cantidad": 1}, "direccion"),
        ("scroll", {"x": 1, "y": 2, "direccion": "up", "cantidad": 0}, "cantidad"),
        ("wait", {"segundos": 3.5}, "segundos"),
        ("wait", {"segundos": -1}, "segundos"),
        ("finish_task", {"resumen": "Listo"}, "evidencia"),
        ("finish_task", {"resumen": "r", "evidencia": "e", "respuesta": {"a": 1}}, "respuesta"),
        ("fail_task", {"datos_clave": []}, "razon"),
        ("fail_task", {"razon": "r"}, "datos_clave"),
        (
            "fail_task",
            {"razon": "r", "datos_clave": [], "candidatos": [{"nombre": "A"}]},
            "identificador",
        ),
    ],
)
def test_schema_errors(name, arguments, message):
    with pytest.raises(ActionError, match=message):
        parse(name, arguments)


def test_observacion_is_required():
    with pytest.raises(ActionError, match="observacion"):
        parse_action("wait", {"segundos": 1}, SCREEN, "pixels")


def test_arguments_must_be_an_object():
    with pytest.raises(ActionError, match="objeto"):
        parse_action("wait", ["segundos", 1], SCREEN, "pixels")  # type: ignore[arg-type]


def test_action_error_is_a_value_error():
    assert issubclass(ActionError, ValueError)
