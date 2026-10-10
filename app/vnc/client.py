"""Sesión con el escritorio remoto por VNC (diseño D1, plan T03).

`vncdotool` aporta el protocolo RFB: saludo, autenticación VNC (DES) y decodificación ZRLE, que
trae una pantalla completa en ~0.2 s contra ~1 s de RAW. Su reactor de Twisted corre en un hilo
propio, compartido por todas las sesiones del proceso. Cada operación se agenda en ese hilo y su
resultado vuelve a asyncio como un futuro con timeout propio, sin bloquear el event loop. No se
usa el proxy con hilos de `vncdotool` porque comparte una sola cola entre llamadas: tras un
timeout, la respuesta tardía le llega a la llamada siguiente.

La copia local de la pantalla se mantiene al día sola: después de cada actualización se pide la
siguiente (incremental), como hace cualquier visor VNC, y `screenshot` y `settle` leen esa copia
sin ir a la red. El cursor llega aparte (pseudo-encoding) y no se dibuja en las capturas, así
que mover el mouse no cuenta como cambio de pantalla.

La contraseña solo viaja cifrada en el handshake: no se registra ni aparece en los errores.
"""

import asyncio
import contextlib
import logging
import threading
import unicodedata
from collections.abc import Callable
from types import TracebackType
from typing import Any, Self

import numpy as np
from PIL import Image
from twisted.internet import reactor
from twisted.internet.defer import Deferred, inlineCallbacks, maybeDeferred, succeed
from vncdotool import rfb
from vncdotool.client import AuthenticationError, VNCDoToolClient, VNCDoToolFactory
from vncdotool.keys import Key

from app.config import Settings
from app.models import ErrorCode
from app.vnc.bridge import Bridge

log = logging.getLogger(__name__)

_CONNECT_ATTEMPTS = 2
_CONNECT_RETRY_DELAY_S = 1.0
_CONNECT_TIMEOUT_S = 15.0  # WebSocket + saludo + autenticación
_FIRST_FRAME_TIMEOUT_S = 15.0
_ACTION_TIMEOUT_S = 10.0
_DISCONNECT_TIMEOUT_S = 3.0
_POLL_S = 0.05  # frecuencia con que settle revisa la copia local
_DOUBLE_CLICK_GAP_S = 0.1  # 120 + 100 + 120 ms: dentro de la ventana de doble clic
_WHEEL_STEP_S = 0.05
_LEFT_BUTTON = 1
_WHEEL_BUTTONS = {"up": 4, "down": 5}


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
        self.size = (0, 0)
        self._bridge: Bridge | None = None
        self._factory: _Factory | None = None

    async def __aenter__(self) -> Self:
        """Conecta y espera la primera pantalla. Un fallo de conexión se reintenta una vez; una
        contraseña rechazada, no."""
        _ensure_reactor()
        for attempt in range(1, _CONNECT_ATTEMPTS + 1):
            try:
                await self._connect()
                return self
            except DesktopError as error:
                await self._disconnect()
                if error.code is ErrorCode.VNC_AUTH_FAILED or attempt == _CONNECT_ATTEMPTS:
                    raise
                log.warning("Conexión VNC fallida (intento %d): %s", attempt, error)
                await asyncio.sleep(_CONNECT_RETRY_DELAY_S)
            except BaseException:
                await self._disconnect()
                raise
        raise AssertionError("inalcanzable")

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._disconnect()

    async def screenshot(self) -> Image.Image:
        return self._frame().copy()

    async def settle(self, before: Image.Image) -> Image.Image:
        """Espera a que la pantalla cambie respecto de `before` y luego a que se estabilice.

        - Si no cambia en `CHANGE_TIMEOUT_S`, devuelve la pantalla actual (la acción no tuvo efecto
          visible; el que llama lo detecta comparando con `before`).
        - Estable es: dos capturas separadas por `STABLE_INTERVAL_S` difieren en menos de
          `DIFF_MIN_PIXELS` píxeles, y además ya pasó `CHANGE_TIMEOUT_S` desde que empezó la
          espera. En SIGECOM el hover de un menú se pinta al instante, pero el efecto del clic
          llega hasta 1 s después: sin esa condición, el hover estable devolvía la pantalla vieja.
        - Si no se estabiliza en `STABLE_TIMEOUT_S` desde el primer cambio, devuelve la última
          captura y lo registra como `SCREEN_NOT_STABLE`, sin fallar: una animación no debe tumbar
          la tarea.
        """
        settings = self.settings
        loop = asyncio.get_running_loop()
        window_end = loop.time() + settings.change_timeout_s

        current = await self._wait_for_change(before, settings.change_timeout_s)
        if current is None:
            return await self.screenshot()

        deadline = loop.time() + settings.stable_timeout_s
        while True:
            await asyncio.sleep(settings.stable_interval_s)
            previous, current = current, self._frame()
            quiet = _changed_pixels(previous, current) < settings.diff_min_pixels
            if quiet and loop.time() >= window_end:
                return current.copy()
            if loop.time() >= deadline:
                log.warning(
                    "%s: la pantalla siguió cambiando %.1f s; se usa la última captura",
                    ErrorCode.SCREEN_NOT_STABLE,
                    settings.stable_timeout_s,
                )
                return current.copy()

    async def click(self, x: int, y: int, double: bool = False) -> None:
        """`mouseDown`, espera `CLICK_HOLD_MS` y `mouseUp` (doble clic: dos veces con
        `DOUBLE_CLICK_HOLD_MS`). Todo corre en el hilo del reactor: si la tarea se cancela a mitad,
        el botón igual se suelta."""
        self._check_point(x, y)
        if double:
            holds = [self.settings.double_click_hold_ms / 1000] * 2
        else:
            holds = [self.settings.click_hold_ms / 1000]
        await self._send(_click, x, y, holds)

    async def type_text(self, text: str) -> None:
        """Selecciona todo (ctrl+a) y luego escribe el texto, carácter por carácter como keysyms
        (tildes, ñ y símbolos incluidos). Con texto vacío, borra lo seleccionado.

        Rechaza caracteres de control (saltos de línea, tabuladores): un Enter escrito así se
        saltaría el filtro de acciones irreversibles. Para eso está `press`.
        """
        await self._send(_type, text_keysyms(text))

    async def press(self, combo: str) -> None:
        """Combinación como `enter`, `tab`, `shift+tab`, `ctrl+a` o `esc` (ver `combo_keysyms`)."""
        await self._send(_press, combo_keysyms(combo))

    async def scroll(self, x: int, y: int, direction: str, amount: int) -> None:
        """Rueda del mouse sobre (x, y): `amount` pasos hacia `up` o `down`."""
        self._check_point(x, y)
        if direction not in _WHEEL_BUTTONS:
            raise ValueError(f"Dirección de scroll inválida: {direction!r} (up o down)")
        if amount < 1:
            raise ValueError(f"La cantidad de scroll debe ser al menos 1: {amount}")
        await self._send(_scroll, x, y, _WHEEL_BUTTONS[direction], amount)

    # --- Conexión

    async def _connect(self) -> None:
        self._bridge = Bridge(self.url)
        await self._bridge.start()
        self._factory = _Factory(self._password)
        try:
            client = await _on_reactor(
                self._factory.open, self._bridge.host, self._bridge.port, timeout=_CONNECT_TIMEOUT_S
            )
        except AuthenticationError as error:
            message = "El escritorio rechazó la contraseña VNC"
            raise DesktopError(ErrorCode.VNC_AUTH_FAILED, message) from error
        except Exception as error:
            raise DesktopError(ErrorCode.VNC_CONNECT_FAILED, self._explain(error)) from error

        loop = asyncio.get_running_loop()
        deadline = loop.time() + _FIRST_FRAME_TIMEOUT_S
        while client.frame is None:
            if self._factory.lost or loop.time() >= deadline:
                message = "El escritorio no envió la primera pantalla"
                raise DesktopError(ErrorCode.VNC_CONNECT_FAILED, message)
            await asyncio.sleep(_POLL_S)
        self.size = (client.width, client.height)
        log.info("Conectado al escritorio VNC (%d×%d)", *self.size)

    def _explain(self, error: Exception) -> str:
        """Causa de un fallo de conexión, sin la URL (puede traer parámetros del evaluador)."""
        if self._bridge is not None and self._bridge.error is not None:
            cause = self._bridge.error
            detail = f"no se pudo abrir el WebSocket ({type(cause).__name__}: {cause})"
        else:
            detail = f"la conexión VNC falló ({type(error).__name__}: {error})"
        message = f"No se pudo conectar al escritorio: {detail}"
        return message.replace(self.url, "<url>") if self.url else message

    async def _disconnect(self) -> None:
        factory, self._factory = self._factory, None
        bridge, self._bridge = self._bridge, None
        if factory is not None:
            try:
                await _on_reactor(factory.close, timeout=_DISCONNECT_TIMEOUT_S)
            except Exception as error:
                log.warning("La conexión VNC no se cerró limpiamente: %s", type(error).__name__)
        if bridge is not None:
            await bridge.close()

    # --- Pantalla y envío de eventos

    def _client(self) -> "_Client":
        factory = self._factory
        if factory is None or factory.lost or factory.client is None:
            raise DesktopError(ErrorCode.WS_DISCONNECTED, "La conexión con el escritorio se cerró")
        return factory.client

    def _frame(self) -> Image.Image:
        frame = self._client().frame
        assert frame is not None  # la sesión no se abre sin la primera pantalla
        return frame

    async def _wait_for_change(self, before: Image.Image, timeout: float) -> Image.Image | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        checked = None
        while True:
            frame = self._frame()
            if frame is not checked:  # la copia local solo se reemplaza al llegar una actualización
                if _changed_pixels(before, frame) >= self.settings.diff_min_pixels:
                    return frame
                checked = frame
            if loop.time() >= deadline:
                return None
            await asyncio.sleep(_POLL_S)

    async def _send(self, action: Callable[..., Any], *args: Any) -> None:
        client = self._client()
        try:
            await _on_reactor(action, client, *args, timeout=_ACTION_TIMEOUT_S)
        except Exception as error:
            message = f"El escritorio no recibió la acción ({type(error).__name__})"
            raise DesktopError(ErrorCode.WS_DISCONNECTED, message) from error
        self._client()  # si la conexión cayó mientras tanto, la acción pudo no llegar

    def _check_point(self, x: int, y: int) -> None:
        width, height = self.size
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError(f"El punto ({x}, {y}) cae fuera de la pantalla {width}×{height}")


# --- Teclado

_CTRL = Key.ControlLeft
_KEY_NAMES: dict[str, int] = {
    "enter": Key.Return,
    "return": Key.Return,
    "intro": Key.Return,
    "tab": Key.Tab,
    "esc": Key.Escape,
    "escape": Key.Escape,
    "backspace": Key.BackSpace,
    "retroceso": Key.BackSpace,
    "delete": Key.Delete,
    "del": Key.Delete,
    "supr": Key.Delete,
    "insert": Key.Insert,
    "home": Key.Home,
    "inicio": Key.Home,
    "end": Key.End,
    "fin": Key.End,
    "pageup": Key.PageUp,
    "pgup": Key.PageUp,
    "pagedown": Key.PageDown,
    "pgdn": Key.PageDown,
    "up": Key.Up,
    "arriba": Key.Up,
    "down": Key.Down,
    "abajo": Key.Down,
    "left": Key.Left,
    "izquierda": Key.Left,
    "right": Key.Right,
    "derecha": Key.Right,
    "space": Key.SpaceBar,
    "espacio": Key.SpaceBar,
    "ctrl": Key.ControlLeft,
    "control": Key.ControlLeft,
    "shift": Key.ShiftLeft,
    "mayus": Key.ShiftLeft,
    "alt": Key.AltLeft,
    "meta": Key.Super_L,
    "super": Key.Super_L,
    "win": Key.Super_L,
    "plus": ord("+"),
    "minus": ord("-"),
    **{f"f{n}": Key.F1 + n - 1 for n in range(1, 13)},
}


def combo_keysyms(combo: str) -> list[int]:
    """`ctrl+shift+tab` pasa a los keysyms de ctrl, shift y tab, en ese orden.

    Acepta los nombres de `_KEY_NAMES` (en inglés y en español) y cualquier carácter suelto
    (`a`, `1`, `ñ`, `+` en `ctrl++`). Sin distinción de mayúsculas. Un nombre desconocido lanza
    ValueError.
    """
    names = [name.strip() for name in combo.strip().lower().split("+")]
    if len(names) >= 2 and names[-2:] == ["", ""]:  # "ctrl++" o "+"
        names = [*names[:-2], "+"]
    keysyms = []
    for name in names:
        if name in _KEY_NAMES:
            keysyms.append(int(_KEY_NAMES[name]))
        elif len(name) == 1 and name.isprintable():
            keysyms.append(_char_keysym(name))
        else:
            raise ValueError(f"Tecla desconocida {name!r} en la combinación {combo!r}")
    return keysyms


def text_keysyms(text: str) -> list[int]:
    for char in text:
        if unicodedata.category(char) == "Cc":
            raise ValueError(f"type_text no escribe caracteres de control: {char!r}; usa press")
    return [_char_keysym(char) for char in text]


def _char_keysym(char: str) -> int:
    """Latin-1 (incluye á, é, í, ó, ú, ñ, ü, ¿, ¡) se envía tal cual; el resto de Unicode, con el
    prefijo 0x01000000 de X11."""
    code = ord(char)
    return code if code <= 0xFF else 0x01000000 | code


# --- Lo que corre en el hilo del reactor


class _Client(VNCDoToolClient):
    """Mantiene `frame` al día: tras cada actualización pide la siguiente (incremental)."""

    encoding = rfb.Encoding.ZRLE
    frame: Image.Image | None = None  # última pantalla completa; se reemplaza, nunca se modifica

    def vncConnectionMade(self) -> None:
        super().vncConnectionMade()
        self.framebufferUpdateRequest(incremental=False)

    def commitUpdate(self, rectangles: list[rfb.Rect] | None = None) -> None:
        if rectangles and self.screen is not None:
            self.frame = self.screen.copy()
        self.framebufferUpdateRequest(incremental=True)

    def updateDesktopSize(self, width: int, height: int) -> None:
        super().updateDesktopSize(width, height)
        self.width, self.height = width, height


class _Factory(VNCDoToolFactory):
    protocol = _Client
    nocursor = True  # pide el cursor aparte y no lo dibuja en la pantalla

    def __init__(self, password: str) -> None:
        super().__init__()
        self.password = password
        self.client: _Client | None = None
        self.lost = False
        self.ready: Deferred = Deferred()  # el protocolo, tras el saludo y la autenticación
        self.done: Deferred = Deferred()  # la conexión terminó, por fallo o por cierre
        self._connector: Any = None

    def open(self, host: str, port: int) -> Deferred:
        self._connector = reactor.connectTCP(host, port, self, timeout=_CONNECT_TIMEOUT_S)
        return self.ready

    def close(self) -> Deferred:
        if self._connector is None:
            return succeed(None)
        if not self.done.called:
            self._connector.disconnect()
        return self.done

    def clientConnectionMade(self, protocol: _Client) -> None:
        self.client = protocol
        if not self.ready.called:
            self.ready.callback(protocol)

    def clientConnectionFailed(self, connector: Any, reason: Any) -> None:
        self.lost = True
        if not self.ready.called:
            self.ready.errback(reason)
        if not self.done.called:
            self.done.callback(None)

    def clientConnectionLost(self, connector: Any, reason: Any) -> None:
        self.clientConnectionFailed(connector, reason)


@inlineCallbacks
def _click(client: _Client, x: int, y: int, holds: list[float]):
    client.mouseMove(x, y)
    for index, hold in enumerate(holds):
        if index:
            yield client.pause(_DOUBLE_CLICK_GAP_S)
        client.mouseDown(_LEFT_BUTTON)
        yield client.pause(hold)
        client.mouseUp(_LEFT_BUTTON)


def _press(client: _Client, keysyms: list[int]) -> None:
    for keysym in keysyms:
        client.keyEvent(keysym, down=True)
    for keysym in reversed(keysyms):
        client.keyEvent(keysym, down=False)


def _type(client: _Client, keysyms: list[int]) -> None:
    _press(client, [_CTRL, ord("a")])
    for keysym in keysyms or [Key.BackSpace]:
        _press(client, [keysym])


@inlineCallbacks
def _scroll(client: _Client, x: int, y: int, button: int, amount: int):
    client.mouseMove(x, y)
    for index in range(amount):
        if index:
            yield client.pause(_WHEEL_STEP_S)
        client.mousePress(button)


_reactor_lock = threading.Lock()
_reactor_thread: threading.Thread | None = None


def _ensure_reactor() -> None:
    """Arranca el reactor de Twisted en un hilo daemon, una sola vez por proceso (no se puede
    reiniciar, así que nunca se detiene)."""
    global _reactor_thread
    with _reactor_lock:
        if _reactor_thread is None and not reactor.running:
            _reactor_thread = threading.Thread(
                target=reactor.run,
                kwargs={"installSignalHandlers": False},
                name="vnc-reactor",
                daemon=True,
            )
            _reactor_thread.start()


async def _on_reactor(function: Callable[..., Any], *args: Any, timeout: float) -> Any:
    """Corre `function(*args)` en el hilo del reactor y espera su resultado (o su Deferred)."""
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def resolve(outcome: Any, failed: bool) -> None:
        if not future.done():
            if failed:
                future.set_exception(outcome)
            else:
                future.set_result(outcome)

    def deliver(outcome: Any, failed: bool) -> None:
        with contextlib.suppress(RuntimeError):  # el event loop ya se cerró
            loop.call_soon_threadsafe(resolve, outcome, failed)

    def run() -> None:
        deferred = maybeDeferred(function, *args)
        deferred.addTimeout(timeout, reactor)
        deferred.addCallbacks(
            lambda result: deliver(result, False), lambda failure: deliver(failure.value, True)
        )

    reactor.callFromThread(run)
    return await future


def _changed_pixels(a: Image.Image, b: Image.Image) -> int:
    """Píxeles distintos entre dos capturas (todos, si cambió el tamaño)."""
    if a.size != b.size:
        return max(a.width * a.height, b.width * b.height)
    pixels_a = np.asarray(a if a.mode == "RGB" else a.convert("RGB"))
    pixels_b = np.asarray(b if b.mode == "RGB" else b.convert("RGB"))
    return int(np.count_nonzero(np.any(pixels_a != pixels_b, axis=-1)))
