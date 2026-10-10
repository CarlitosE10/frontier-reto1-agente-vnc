"""Cliente de OpenRouter: chat con herramientas e imágenes (se implementa en T05)."""

from dataclasses import dataclass

from app.config import Settings
from app.models import ErrorCode


class LLMError(Exception):
    def __init__(self, code: ErrorCode = ErrorCode.VLM_ERROR, message: str = "") -> None:
        super().__init__(message or code.value)
        self.code = code


@dataclass
class ChatResult:
    tool_name: str | None
    arguments: dict
    text: str
    cost_usd: float
    latency_s: float


class OpenRouterClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def chat(self, model: str, messages: list[dict], tools: list[dict]) -> ChatResult:
        raise NotImplementedError
