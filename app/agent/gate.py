"""Filtro de acciones irreversibles: reglas y verificación del VLM (se implementa en T08)."""

from PIL import Image

from app.config import Settings
from app.llm.openrouter import OpenRouterClient
from app.models import Action, FinishTask, GateDecision


def is_irreversible(
    action: Action, words_near_point: list[str], in_form: bool, keywords: list[str]
) -> bool:
    raise NotImplementedError


class Gate:
    """Hoy verifica con el VLM; más adelante puede sumar Jev sin cambiar esta interfaz."""

    def __init__(self, llm: OpenRouterClient, settings: Settings) -> None:
        self.llm = llm
        self.settings = settings

    async def check_action(
        self,
        task: str,
        action: Action,
        screen: Image.Image,
        screen_text: str,
        evidence: list[str],
    ) -> GateDecision:
        raise NotImplementedError

    async def check_completion(
        self, task: str, result: FinishTask, screen: Image.Image, screen_text: str
    ) -> GateDecision:
        raise NotImplementedError
