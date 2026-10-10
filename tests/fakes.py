"""Dobles de prueba (plan, sección 2.4): cada módulo se prueba sin escritorio ni modelos reales."""

from pathlib import Path
from types import TracebackType
from typing import Any, Self

from PIL import Image

from app.llm.openrouter import ChatResult
from app.models import ErrorCode
from app.vnc.client import DesktopError


class FakeDesktop:
    """Cumple la interfaz de `DesktopSession` con capturas de archivo.

    Cada acción queda en `actions` como `(nombre, argumentos)` y avanza a la captura siguiente;
    la última se repite. Para simular una acción sin efecto, repite la misma ruta en `screens`.
    Usarla fuera del `async with` lanza `DesktopError(WS_DISCONNECTED)`.
    """

    def __init__(self, screens: list[Path]) -> None:
        if not screens:
            raise ValueError("FakeDesktop necesita al menos una captura")
        self._screens = [_load(path) for path in screens]
        self._index = 0
        self.size: tuple[int, int] = self._screens[0].size
        self.actions: list[tuple[str, dict[str, Any]]] = []
        self.connected = False

    async def __aenter__(self) -> Self:
        self.connected = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.connected = False

    async def screenshot(self) -> Image.Image:
        self._require_connected()
        return self._screens[self._index].copy()

    async def settle(self, before: Image.Image) -> Image.Image:
        return await self.screenshot()

    async def click(self, x: int, y: int, double: bool = False) -> None:
        self._record("click", x=x, y=y, double=double)

    async def type_text(self, text: str) -> None:
        self._record("type_text", text=text)

    async def press(self, combo: str) -> None:
        self._record("press", combo=combo)

    async def scroll(self, x: int, y: int, direction: str, amount: int) -> None:
        self._record("scroll", x=x, y=y, direction=direction, amount=amount)

    def _record(self, name: str, **arguments: Any) -> None:
        self._require_connected()
        self.actions.append((name, arguments))
        self._index = min(self._index + 1, len(self._screens) - 1)

    def _require_connected(self) -> None:
        if not self.connected:
            raise DesktopError(ErrorCode.WS_DISCONNECTED, "FakeDesktop sin conexión")


class FakeLLM:
    """Cumple la interfaz de `OpenRouterClient` con respuestas guionadas, en orden.

    Un elemento del guion que sea una excepción se lanza en vez de devolverse. Cada llamada
    queda en `calls`.
    """

    def __init__(self, script: list[ChatResult | Exception]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    @property
    def remaining(self) -> int:
        return len(self._script)

    async def chat(self, model: str, messages: list[dict], tools: list[dict]) -> ChatResult:
        self.calls.append({"model": model, "messages": messages, "tools": tools})
        if not self._script:
            raise AssertionError("FakeLLM: se acabó el guion")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def tool_call(name: str, arguments: dict, cost_usd: float = 0.0) -> ChatResult:
    """Respuesta del VLM que elige la herramienta `name`."""
    return ChatResult(
        tool_name=name, arguments=arguments, text="", cost_usd=cost_usd, latency_s=0.0
    )


def write_screen(path: Path, color: str, size: tuple[int, int] = (1280, 800)) -> Path:
    """Guarda una captura de un solo color, para pruebas que no necesitan una real."""
    Image.new("RGB", size, color).save(path)
    return path


def _load(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGB")
