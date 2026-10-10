"""Esquemas de herramientas del VLM y parseo de sus acciones (plan, T06).

Las herramientas siguen los tipos de `app.models` (sección 2.2). Además, todas aceptan
`es_listado`, que no forma parte de `Action`: el ciclo lo lee de los argumentos crudos para
guardar como evidencia las pantallas de listados y resultados de búsqueda.

Los tipos de los esquemas son simples (sin uniones con `null`) para que los acepte cualquier
proveedor de OpenRouter; `parse_action` tolera las variaciones habituales de los modelos.
"""

import math

from pydantic import TypeAdapter, ValidationError

from app.models import Action, Effect

_OBSERVACION = {
    "type": "string",
    "description": "Lo que ves en la pantalla y que justifica esta acción.",
}
_FECHA_APP = {
    "type": "string",
    "description": (
        "Obligatoria en el primer paso: la fecha de hoy tal como la muestra la app. "
        "Si no se ve, envía una cadena vacía."
    ),
}
_ES_LISTADO = {
    "type": "boolean",
    "description": (
        "true si la pantalla actual muestra un listado o resultados de búsqueda que conviene "
        "recordar como evidencia."
    ),
}
_COORD = "Coordenada {axis} del punto, en el sistema que indica el prompt del sistema."
_EFECTO = {
    "type": "string",
    "enum": [effect.value for effect in Effect],
    "description": (
        "Qué produce la acción: navegar (abrir, buscar, seleccionar), editar (enfocar o cambiar "
        "un control sin guardar), guardar (guardar, crear, registrar, aceptar, confirmar), "
        "exportar o eliminar."
    ),
}


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    """`properties` va con los campos estructurados primero y el texto libre al final.

    `observacion` queda de última: el modelo llena los parámetros en el orden del esquema, y a
    veces cierra mal un texto largo y se traga el parámetro que sigue (en la primera corrida de
    T16, `x` quedó dentro de la observación). Con el texto al final, no hay nada que tragarse.
    """
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    **properties,
                    "fecha_app": _FECHA_APP,
                    "es_listado": _ES_LISTADO,
                    "observacion": _OBSERVACION,
                },
                "required": [*required, "observacion"],
            },
        },
    }


def _click_tool(name: str, description: str) -> dict:
    return _tool(
        name,
        description,
        {
            "x": {"type": "integer", "description": _COORD.format(axis="x")},
            "y": {"type": "integer", "description": _COORD.format(axis="y")},
            "objetivo": {
                "type": "string",
                "description": "El elemento sobre el que haces clic, con su texto visible.",
            },
            "efecto": _EFECTO,
        },
        ["x", "y", "objetivo", "efecto"],
    )


TOOLS: list[dict] = [
    _click_tool("click", "Clic izquierdo en el centro de un elemento."),
    _click_tool("double_click", "Doble clic izquierdo en el centro de un elemento."),
    _tool(
        "type_text",
        "Reemplaza el contenido del campo enfocado: selecciona todo (ctrl+a) y escribe el texto.",
        {
            "texto": {"type": "string", "description": "El valor exacto que se escribe."},
            "campo": {"type": "string", "description": "El campo donde se escribe."},
        },
        ["texto", "campo"],
    ),
    _tool(
        "press_key",
        "Presiona una tecla o combinación. Enter dentro de un formulario puede guardar.",
        {
            "combinacion": {
                "type": "string",
                "description": "Por ejemplo: enter, tab, esc, ctrl+a.",
            }
        },
        ["combinacion"],
    ),
    _tool(
        "scroll",
        "Mueve la rueda del mouse sobre un punto.",
        {
            "x": {"type": "integer", "description": _COORD.format(axis="x")},
            "y": {"type": "integer", "description": _COORD.format(axis="y")},
            "direccion": {"type": "string", "enum": ["up", "down"]},
            "cantidad": {"type": "integer", "minimum": 1, "description": "Pasos de la rueda."},
        },
        ["x", "y", "direccion", "cantidad"],
    ),
    _tool(
        "wait",
        "Espera a que la app termine de cargar.",
        {"segundos": {"type": "number", "minimum": 0, "maximum": 3}},
        ["segundos"],
    ),
    _tool(
        "finish_task",
        "Cierra la tarea como cumplida. Pasa por una verificación antes de aceptarse.",
        {
            "respuesta": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Solo si la tarea es una pregunta: un elemento por dato pedido, en el orden "
                    "de la pregunta. Omítela si la tarea no pregunta nada."
                ),
            },
            "resumen": {"type": "string", "description": "Qué se hizo, en una o dos frases."},
            "evidencia": {
                "type": "string",
                "description": "El texto visible en la pantalla que respalda el resultado.",
            },
        },
        ["resumen", "evidencia"],
    ),
    _tool(
        "fail_task",
        "Cierra la tarea como fallida, sin hacer cambios.",
        {
            "datos_clave": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Valores que explican la falla: identificadores, nombres, fechas.",
            },
            "candidatos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "nombre": {"type": "string"},
                        "identificador": {
                            "type": "string",
                            "description": "Documento, NIT o código que distingue al registro.",
                        },
                    },
                    "required": ["nombre", "identificador"],
                },
                "description": "Registros que coinciden con la tarea cuando no se sabe cuál es.",
            },
            "razon": {"type": "string", "description": "Por qué no se puede cumplir la tarea."},
        },
        ["datos_clave", "razon"],
    ),
]

# Nombre de la herramienta -> "kind" de la acción.
_KINDS = {
    "click": "click",
    "double_click": "click",
    "type_text": "type_text",
    "press_key": "press_key",
    "scroll": "scroll",
    "wait": "wait",
    "finish_task": "finish_task",
    "fail_task": "fail_task",
}
_COORD_MODES = ("pixels", "norm1000")
_ACTION: TypeAdapter[Action] = TypeAdapter(Action)


class ActionError(ValueError):
    """La acción del VLM no es válida. El mensaje se le devuelve al VLM para que corrija."""


def parse_action(
    name: str, arguments: dict, screen_size: tuple[int, int], coord_mode: str
) -> Action:
    """Valida la herramienta elegida por el VLM y la convierte en una `Action` en píxeles reales.

    Lanza `ActionError` si la herramienta no existe, si los argumentos no cumplen el esquema o
    si las coordenadas caen fuera de la pantalla.
    """
    if coord_mode not in _COORD_MODES:
        raise ValueError(f"VLM_COORD_MODE desconocido: {coord_mode!r}")
    kind = _KINDS.get(name)
    if kind is None:
        raise ActionError(f"herramienta desconocida: {name!r}")
    if not isinstance(arguments, dict):
        raise ActionError("los argumentos deben ser un objeto JSON")

    data = {**arguments, "kind": kind}
    if kind == "click":
        data["double"] = name == "double_click"
    if kind in ("click", "scroll"):
        width, height = screen_size
        data["x"] = _to_pixel(data.get("x"), width, coord_mode, "x")
        data["y"] = _to_pixel(data.get("y"), height, coord_mode, "y")
    fecha_app = data.get("fecha_app")
    if isinstance(fecha_app, str) and fecha_app.strip().lower() in ("", "null"):
        data["fecha_app"] = None
    if kind == "press_key" and isinstance(data.get("combinacion"), str):
        data["combinacion"] = "".join(data["combinacion"].split()).lower()
    if kind == "finish_task":
        data["respuesta"] = _str_list(data.get("respuesta")) or None
    if kind == "fail_task":
        if "datos_clave" in data:
            data["datos_clave"] = _str_list(data["datos_clave"])
        data["candidatos"] = _candidates(data.get("candidatos"))

    try:
        action = _ACTION.validate_python(data)
    except ValidationError as error:
        raise ActionError(f"argumentos inválidos para {name}: {_describe(error)}") from None

    if action.kind == "scroll" and action.cantidad < 1:
        raise ActionError("cantidad debe ser al menos 1")
    if action.kind == "press_key" and not action.combinacion:
        raise ActionError("combinacion no puede estar vacía")
    return action


def _to_pixel(value: object, length: int, coord_mode: str, axis: str) -> int:
    """Convierte una coordenada del VLM a píxeles reales y rechaza las que caen fuera."""
    if value is None:
        raise ActionError(f"falta la coordenada {axis}")
    if isinstance(value, bool):
        raise ActionError(f"{axis} debe ser un número, llegó {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ActionError(f"{axis} debe ser un número, llegó {value!r}") from None
    if not math.isfinite(number):
        raise ActionError(f"{axis} debe ser un número finito, llegó {value!r}")

    if coord_mode == "norm1000":
        if not 0 <= number <= 1000:
            raise ActionError(f"{axis}={value} está fuera de la escala 0-1000")
        return min(round(number * length / 1000), length - 1)
    pixel = round(number)
    if not 0 <= pixel < length:
        raise ActionError(f"{axis}={value} está fuera de la pantalla (0 a {length - 1})")
    return pixel


def _str_list(value: object) -> object:
    """`"45"` o `45` pasan a `["45"]`; los números pasan a texto y se quitan los vacíos.

    Lo que no sea texto ni número queda igual para que lo rechace Pydantic.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    items = []
    for item in value:
        item = _number_to_str(item)
        if isinstance(item, str):
            item = item.strip()
            if not item:
                continue
        items.append(item)
    return items


def _candidates(value: object) -> object:
    """Los identificadores numéricos (`52345678`) pasan a texto."""
    if value is None:
        return []
    if not isinstance(value, list):
        return value
    return [
        {key: _number_to_str(field) for key, field in item.items()}
        if isinstance(item, dict)
        else item
        for item in value
    ]


def _number_to_str(value: object) -> object:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return value


def _describe(error: ValidationError) -> str:
    parts = []
    for detail in error.errors():
        # El primer elemento de loc es la etiqueta de la unión ("click", "wait"...).
        loc = ".".join(str(part) for part in detail["loc"][1:]) or "acción"
        parts.append(f"{loc}: {detail['msg']}")
    return "; ".join(parts)
