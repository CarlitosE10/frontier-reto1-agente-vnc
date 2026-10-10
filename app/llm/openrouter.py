"""Cliente de OpenRouter: chat con herramientas e imágenes (plan, T05).

Cada llamada es un `POST /api/v1/chat/completions` con `tool_choice: auto`, el esfuerzo de
razonamiento de `Settings` y `provider.require_parameters` para que OpenRouter solo enrute a
proveedores que aceptan todos los parámetros. Ante 429, 5xx o fallas de red reintenta dos veces
con backoff; cualquier otra falla termina en `LLMError(VLM_ERROR)`.

La llave solo vive en el encabezado `Authorization` de cada petición: no se registra ni aparece
en los mensajes de error.
"""

import asyncio
import base64
import io
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from PIL import Image

from app.config import Settings
from app.models import ErrorCode

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
RETRIES = 2  # reintentos después del primer intento
BACKOFF_S = 1.0  # espera antes del reintento n: BACKOFF_S * 2**(n-1)
MAX_RETRY_AFTER_S = 10.0  # tope para el Retry-After de un 429
MAX_TOKENS = 4096  # razonamiento + respuesta; una acción ocupa unos cientos de tokens
TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

# Se llama a través de este nombre para que las pruebas puedan saltarse las esperas.
_sleep = asyncio.sleep


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


def image_part(image: Image.Image) -> dict:
    """Bloque de contenido `image_url` con la imagen en PNG base64, en resolución nativa."""
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    data = base64.b64encode(buffer.getvalue()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}}


class _Retryable(Exception):
    """Falla transitoria: se reintenta y, si se agotan los intentos, pasa a `LLMError`."""

    def __init__(self, message: str, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class OpenRouterClient:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    async def chat(self, model: str, messages: list[dict], tools: list[dict]) -> ChatResult:
        """Devuelve la primera tool call de la respuesta (o el texto, si no hubo ninguna)."""
        body = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "reasoning": {"effort": self.settings.vlm_reasoning_effort},
            "provider": {"require_parameters": True},
            "max_tokens": MAX_TOKENS,
        }
        start = time.monotonic()
        for attempt in range(RETRIES + 1):
            try:
                data = await self._post(body)
                result = self._parse(data, latency_s=time.monotonic() - start)
            except _Retryable as error:
                if attempt == RETRIES:
                    raise LLMError(message=f"{error} (después de {attempt + 1} intentos)") from None
                delay = BACKOFF_S * 2**attempt
                if error.retry_after_s is not None:
                    delay = min(max(delay, error.retry_after_s), MAX_RETRY_AFTER_S)
                logger.warning(
                    "openrouter: %s; reintento %d de %d en %.1f s",
                    error, attempt + 1, RETRIES, delay,
                )
                await _sleep(delay)
                continue
            logger.info(
                "openrouter: modelo=%s herramienta=%s costo=%.6f latencia=%.2f s intentos=%d",
                model, result.tool_name, result.cost_usd, result.latency_s, attempt + 1,
            )
            return result
        raise AssertionError("inalcanzable")

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _post(self, body: dict) -> dict:
        if self._http is None:
            self._http = httpx.AsyncClient(transport=self._transport, timeout=TIMEOUT)
        key = self.settings.openrouter_api_key.get_secret_value()
        try:
            response = await self._http.post(
                OPENROUTER_URL, json=body, headers={"Authorization": f"Bearer {key}"}
            )
        except httpx.TransportError as error:  # conexión, timeout, protocolo
            raise _Retryable(f"falla de red ({type(error).__name__})") from None

        if response.status_code in _RETRYABLE_STATUS:
            raise _Retryable(
                f"HTTP {response.status_code}: {self._error_message(response)}",
                retry_after_s=_retry_after(response),
            )
        if response.status_code != 200:
            raise LLMError(message=f"HTTP {response.status_code}: {self._error_message(response)}")
        try:
            data = response.json()
        except ValueError:
            raise _Retryable("respuesta que no es JSON") from None

        # OpenRouter puede responder 200 con un error del proveedor en el cuerpo.
        if isinstance(data, dict) and "error" in data:
            error = data["error"] if isinstance(data["error"], dict) else {}
            code = error.get("code")
            message = self._clean(str(error.get("message", "error sin mensaje")))
            if code in _RETRYABLE_STATUS or code is None:
                raise _Retryable(f"error del proveedor {code}: {message}")
            raise LLMError(message=f"error del proveedor {code}: {message}")
        return data

    def _parse(self, data: Any, latency_s: float) -> ChatResult:
        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError):
            raise _Retryable("respuesta sin choices") from None
        if choice.get("finish_reason") == "error":
            raise _Retryable("el proveedor cortó la respuesta (finish_reason=error)")

        text = _content_text(message.get("content"))
        tool_name, arguments = None, {}
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            function = tool_calls[0].get("function") or {}
            tool_name = function.get("name")
            raw = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                raise LLMError(
                    message=f"argumentos de {tool_name} que no son JSON válido"
                ) from None
            if not isinstance(arguments, dict):
                raise LLMError(message=f"argumentos de {tool_name} que no son un objeto")

        usage = data.get("usage") or {}
        cost = usage.get("cost")
        if cost is None:
            logger.warning("openrouter: la respuesta no trae usage.cost; se cuenta 0")
        return ChatResult(
            tool_name=tool_name,
            arguments=arguments,
            text=text,
            cost_usd=float(cost or 0.0),
            latency_s=latency_s,
        )

    def _error_message(self, response: httpx.Response) -> str:
        try:
            message = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = response.text
        return self._clean(str(message))

    def _clean(self, message: str) -> str:
        """Recorta el mensaje y le quita la llave por si el servidor la repitiera."""
        key = self.settings.openrouter_api_key.get_secret_value()
        if key:
            message = message.replace(key, "***")
        return message[:300]


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers["retry-after"])
    except (KeyError, ValueError):
        return None


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # algunos proveedores devuelven partes
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""
