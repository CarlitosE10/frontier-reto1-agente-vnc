"""Sesión con el escritorio remoto por VNC (se implementa en T03)."""

from types import TracebackType
from typing import Self

from PIL import Image

from app.config import Settings
from app.models import ErrorCode


class DesktopError(Exception):
    def __init__(self, code: ErrorCode, message: str = "") -> None:
        super().__init__(message or code.value)
        self.code = code


class DesktopSession:
    """Se usa como `async with DesktopSession(...) as desktop:`. Al salir se desconecta."""

    size: tuple[int, int]  # leído del servidor VNC al conectar

    def __init__(self, url: str, password: str, settings: Settings) -> None:
        self.url = url
        self._password = password
        self.settings = settings

    async def __aenter__(self) -> Self:
        raise NotImplementedError

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        raise NotImplementedError

    async def screenshot(self) -> Image.Image:
        raise NotImplementedError

    async def settle(self, before: Image.Image) -> Image.Image:
        """Espera a que la pantalla cambie respecto de `before` y luego a que se estabilice."""
        raise NotImplementedError

    async def click(self, x: int, y: int, double: bool = False) -> None:
        raise NotImplementedError

    async def type_text(self, text: str) -> None:
        """Selecciona todo (ctrl+a) y luego escribe el texto."""
        raise NotImplementedError

    async def press(self, combo: str) -> None:
        raise NotImplementedError

    async def scroll(self, x: int, y: int, direction: str, amount: int) -> None:
        raise NotImplementedError
