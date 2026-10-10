"""Filtro de acciones irreversibles (System 1): reglas y verificación del VLM (plan, T08).

`is_irreversible` decide en código qué acciones pasan por la verificación. `Gate` verifica con
`VLM_MODEL` en una llamada aparte y con contexto limpio: solo ve la tarea, la acción, la captura,
el OCR y la evidencia, nunca la conversación que propuso la acción. Si un chequeo sale en no, o
la verificación no responde después de un reintento, bloquea.
"""

import logging
import re
import unicodedata
from collections.abc import Sequence

from PIL import Image, ImageDraw
from vncdotool.keys import Key

from app.agent.prompts import VERIFY_ACTION_PROMPT, VERIFY_COMPLETION_PROMPT
from app.config import Settings
from app.llm.openrouter import ChatResult, LLMError, OpenRouterClient, image_part
from app.models import (
    Action,
    Click,
    Effect,
    FinishTask,
    GateDecision,
    PressKey,
    Scroll,
    TypeText,
    Wait,
)
from app.vnc.client import combo_keysyms

logger = logging.getLogger(__name__)

VERIFY_ATTEMPTS = 2  # un reintento; si ambos fallan, no se actúa
MAX_SCREEN_TEXT_CHARS = 6000
MAX_EVIDENCE_ITEM_CHARS = 4000
MAX_EVIDENCE_CHARS = 16000  # si no cabe todo, se descartan las pantallas más viejas
MARK_RADIUS = 16

_IRREVERSIBLE_EFFECTS = {Effect.GUARDAR, Effect.EXPORTAR, Effect.ELIMINAR}

# --- Herramienta `verificar` ---------------------------------------------------------------

ACTION_CHECKS = {
    "dentro_de_tarea": "La acción es necesaria para la tarea y no hace nada que la tarea no pida.",
    "registro_correcto": (
        "El registro afectado es exactamente el que nombra la tarea, sin homónimos que la tarea "
        "no distinga ni duplicados."
    ),
    "valores_correctos": "Los valores visibles coinciden exactamente con los que pide la tarea.",
}
TASK_CHECK = {
    "tarea_cumplida": "La captura o el texto de la pantalla muestran que la tarea quedó hecha.",
}
ANSWER_CHECK = {
    "respuesta_respaldada": (
        "Cada valor de la respuesta se ve en la captura o en el texto de la pantalla y responde "
        "exactamente lo que pregunta la tarea."
    ),
}


def verify_tool(checks: dict[str, str]) -> dict:
    """Esquema de `verificar`: los chequeos (booleanos) y al final la razón, todos obligatorios.

    Con la razón primero, en E5 en vivo el modelo a veces omitía un chequeo (`dentro_de_tarea`).
    """
    properties: dict[str, dict] = {
        name: {"type": "boolean", "description": description}
        for name, description in checks.items()
    }
    properties["razon"] = {
        "type": "string",
        "description": "Datos concretos que justifican la respuesta; si algo es no, cuál y "
        "por qué.",
    }
    return {
        "type": "function",
        "function": {
            "name": "verificar",
            "description": "Entrega el resultado de la verificación.",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": [*checks, "razon"],
                "additionalProperties": False,
            },
        },
    }


VERIFY_ACTION_TOOL = verify_tool(ACTION_CHECKS)
VERIFY_TASK_TOOL = verify_tool(TASK_CHECK)
VERIFY_ANSWER_TOOL = verify_tool(ANSWER_CHECK)


# --- Reglas en código ----------------------------------------------------------------------


def is_irreversible(
    action: Action, words_near_point: list[str], in_form: bool, keywords: list[str]
) -> bool:
    """Una acción es irreversible si:

    - es un clic con `efecto` guardar, exportar o eliminar, o con una palabra clave cerca;
    - es un `Enter` dentro de un formulario, o con una palabra clave cerca del foco;
    - escribe un salto de línea dentro de un formulario (equivale a `Enter`).
    """
    if isinstance(action, Click):
        return action.efecto in _IRREVERSIBLE_EFFECTS or _has_keyword(words_near_point, keywords)
    if isinstance(action, PressKey):
        return _is_enter(action.combinacion) and (
            in_form or _has_keyword(words_near_point, keywords)
        )
    if isinstance(action, TypeText):
        return in_form and ("\n" in action.texto or "\r" in action.texto)
    return False


def _is_enter(combo: str) -> bool:
    """La combinación termina en Return, leída con la misma tabla de teclas que usa el escritorio
    (`enter`, `return`, `intro`, `ctrl+enter`...): así las dos listas no pueden divergir."""
    try:
        keysyms = combo_keysyms(combo)
    except ValueError:
        return False  # el escritorio tampoco la puede enviar: no llega a ejecutarse
    return keysyms[-1] == Key.Return


def _fold(text: str) -> str:
    """Minúsculas y sin tildes: el OCR a veces lee `Si` donde dice `Sí`."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def fold_tokens(text: str) -> list[str]:
    """Palabras en minúsculas y sin tildes."""
    return re.findall(r"\w+", _fold(text))


def _has_keyword(words: list[str], keywords: list[str]) -> bool:
    """Compara por palabra; las claves de 4 letras o más también cubren sus conjugaciones
    (`guardarlo`), y las de varias palabras se buscan como frase."""
    tokens = [token for word in words for token in fold_tokens(word)]
    joined = f" {' '.join(tokens)} "
    for keyword in keywords:
        parts = fold_tokens(keyword)
        if len(parts) > 1:
            if f" {' '.join(parts)} " in joined:
                return True
        elif parts:
            target = parts[0]
            if any(t == target or (len(target) >= 4 and t.startswith(target)) for t in tokens):
                return True
    return False


# --- Verificación con el VLM ---------------------------------------------------------------


class _InvalidVerdict(Exception):
    pass


class Gate:
    """Hoy verifica con el VLM; más adelante puede sumar Jev sin cambiar esta interfaz.

    `cost_usd` acumula el gasto de las verificaciones de esta instancia, para que el ciclo lo
    sume al tope de gasto de la tarea.
    """

    def __init__(self, llm: OpenRouterClient, settings: Settings) -> None:
        self.llm = llm
        self.settings = settings
        self.cost_usd = 0.0

    async def check_action(
        self,
        task: str,
        action: Action,
        screen: Image.Image,
        screen_text: str,
        evidence: list[str],
    ) -> GateDecision:
        if not self.settings.verify_enabled:
            return _disabled()
        text = (
            f"<tarea>\n{task}\n</tarea>\n\n"
            f"<accion>\n{describe_action(action)}\n</accion>\n\n"
            f"<texto_pantalla>\n{_clip(screen_text, MAX_SCREEN_TEXT_CHARS)}\n</texto_pantalla>\n\n"
            f"<evidencia>\n{_format_evidence(evidence)}\n</evidencia>"
        )
        messages = _messages(VERIFY_ACTION_PROMPT, text, mark_action(screen, action))
        return await self._verify(messages, VERIFY_ACTION_TOOL, list(ACTION_CHECKS))

    async def check_completion(
        self,
        task: str,
        result: FinishTask,
        screen: Image.Image,
        screen_text: str,
        evidence: Sequence[str] = (),
    ) -> GateDecision:
        """Chequeo de éxito falso. `evidence` deja respaldar lo que no cabe en la pantalla final,
        como un conteo sobre varias páginas (E3: el total 45 no aparece en ninguna)."""
        if not self.settings.verify_enabled:
            return _disabled()
        if result.respuesta:
            tool, checks = VERIFY_ANSWER_TOOL, list(ANSWER_CHECK)
            answer = "; ".join(result.respuesta)
        else:
            tool, checks = VERIFY_TASK_TOOL, list(TASK_CHECK)
            answer = "(ninguna)"
        text = (
            f"<tarea>\n{task}\n</tarea>\n\n"
            f"<cierre>\nresumen: {result.resumen}\nrespuesta: {answer}\n"
            f"evidencia citada: {result.evidencia}\n</cierre>\n\n"
            f"<texto_pantalla>\n{_clip(screen_text, MAX_SCREEN_TEXT_CHARS)}\n</texto_pantalla>\n\n"
            f"<evidencia>\n{_format_evidence(list(evidence))}\n</evidencia>"
        )
        messages = _messages(VERIFY_COMPLETION_PROMPT, text, screen)
        return await self._verify(messages, tool, checks)

    async def _verify(self, messages: list[dict], tool: dict, checks: list[str]) -> GateDecision:
        failure = ""
        for attempt in range(1, VERIFY_ATTEMPTS + 1):
            try:
                result = await self.llm.chat(self.settings.verify_model_effective, messages, [tool])
            except LLMError as error:
                failure = f"{error.code.value}: {error}"
            else:
                self.cost_usd += result.cost_usd
                try:
                    values, reason = _read_verdict(result, checks)
                except _InvalidVerdict as error:
                    failure = str(error)
                else:
                    return _decide(values, reason)
            logger.warning("gate: intento %d de verificación fallido: %s", attempt, failure)
        return GateDecision(
            outcome="block",
            reason=f"La verificación falló {VERIFY_ATTEMPTS} veces ({failure}); no se actúa.",
            checks=None,
        )


def describe_action(action: Action) -> str:
    """La acción en texto, sin la `observacion` del agente que la propuso (contexto limpio)."""
    if isinstance(action, Click):
        verb = "doble clic" if action.double else "clic"
        return (
            f"{verb} en ({action.x}, {action.y}) sobre «{action.objetivo}»; "
            f"efecto declarado: {action.efecto.value}"
        )
    if isinstance(action, TypeText):
        return f"escribir «{action.texto}» en el campo «{action.campo}»"
    if isinstance(action, PressKey):
        return f"presionar la tecla {action.combinacion}"
    if isinstance(action, Scroll):
        return f"desplazar {action.direccion} {action.cantidad} veces en ({action.x}, {action.y})"
    if isinstance(action, Wait):
        return f"esperar {action.segundos} s"
    return action.kind


def mark_action(screen: Image.Image, action: Action) -> Image.Image:
    """Copia de la captura con un círculo rojo en el punto de la acción, si tiene coordenadas."""
    if not isinstance(action, Click | Scroll):
        return screen
    marked = screen.convert("RGB")  # convert siempre devuelve una copia
    box = (
        action.x - MARK_RADIUS,
        action.y - MARK_RADIUS,
        action.x + MARK_RADIUS,
        action.y + MARK_RADIUS,
    )
    ImageDraw.Draw(marked).ellipse(box, outline=(255, 0, 0), width=3)
    return marked


def _messages(system: str, text: str, screen: Image.Image) -> list[dict]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": [{"type": "text", "text": text}, image_part(screen)]},
    ]


def _read_verdict(result: ChatResult, checks: list[str]) -> tuple[dict[str, bool], str]:
    if result.tool_name != "verificar":
        raise _InvalidVerdict(f"el modelo no llamó a verificar (llamó a {result.tool_name})")
    values = {}
    for name in checks:
        value = result.arguments.get(name)
        if not isinstance(value, bool):
            keys = ", ".join(sorted(result.arguments)) or "ninguna"
            raise _InvalidVerdict(f"{name} no es booleano: {value!r} (claves: {keys})")
        values[name] = value
    reason = result.arguments.get("razon")
    return values, reason.strip() if isinstance(reason, str) else ""


def _decide(values: dict[str, bool], reason: str) -> GateDecision:
    failed = [name for name, ok in values.items() if not ok]
    if not failed:
        return GateDecision(outcome="approve", reason=reason or "Chequeos en sí.", checks=values)
    logger.info("gate: bloqueada por %s", ", ".join(failed))
    detail = f"{', '.join(failed)} en no"
    return GateDecision(
        outcome="block", reason=f"{detail}: {reason}" if reason else detail, checks=values
    )


def _disabled() -> GateDecision:
    return GateDecision(outcome="approve", reason="Verificación desactivada.", checks=None)


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if not text:
        return "(vacío)"
    return text if len(text) <= limit else text[:limit] + " […]"


def _format_evidence(evidence: list[str]) -> str:
    kept: list[str] = []
    total = 0
    for item in reversed(evidence):  # de la más reciente a la más vieja
        item = _clip(item, MAX_EVIDENCE_ITEM_CHARS)
        if kept and total + len(item) > MAX_EVIDENCE_CHARS:
            break
        kept.append(item)
        total += len(item)
    if not kept:
        return "(sin evidencia)"
    kept.reverse()
    skipped = len(evidence) - len(kept)
    header = f"({skipped} pantallas más viejas omitidas)\n" if skipped else ""
    return header + "\n".join(
        f"--- pantalla {skipped + i} ---\n{item}" for i, item in enumerate(kept, start=1)
    )
