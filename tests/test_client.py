"""DesktopSession (T03) contra un servidor RFB mínimo sobre WebSocket.

Recorre el camino real (puente, saludo, autenticación VNC, pantalla, eventos y cierre) sin
escritorio. El servidor registra cada evento con la hora en que llegó.
"""

import asyncio
import contextlib
import logging
import os
import struct
import time
from http import HTTPStatus

import pytest
from vncdotool.rfb import PixelFormat, _vnc_des, des_encrypt
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from app.config import Settings
from app.models import ErrorCode
from app.vnc import client as client_module
from app.vnc.client import DesktopError, DesktopSession, combo_keysyms, text_keysyms

PASSWORD = "clave-vnc"
SIZE = (64, 48)
WHITE, GRAY, BLACK = (255, 255, 255), (128, 128, 128), (0, 0, 0)
TIMEOUT = 5

ENCODING_ZRLE = 16
ENCODING_CURSOR = -239
CTRL, SHIFT, ALT = 0xFFE3, 0xFFE1, 0xFFE9


class FakeRFBServer:
    """RFB 3.8 con autenticación VNC y una pantalla de un solo color, enviada en RAW.

    Responde las peticiones incrementales solo cuando la pantalla cambia (`paint`), como un
    servidor real. `on_click` se llama al soltar el botón izquierdo.
    """

    def __init__(self) -> None:
        self.color = WHITE
        self.events: list[tuple] = []  # ("key", down, keysym, t) o ("pointer", mask, x, y, t)
        self.encodings: list[int] = []
        self.connections = 0
        self.websockets = []
        self.closed = asyncio.Event()
        self.on_click = None
        self._buttons = 0
        self._waiting = None  # websocket con una petición incremental pendiente
        self._send_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()

    async def handler(self, websocket) -> None:
        self.connections += 1
        self.websockets.append(websocket)
        try:
            await self._serve(websocket, _Stream(websocket))
        except ConnectionClosed:
            pass
        finally:
            self.closed.set()

    async def _serve(self, websocket, stream: "_Stream") -> None:
        await websocket.send(b"RFB 003.008\n")
        await stream.read(12)
        await websocket.send(bytes([1, 2]))  # un tipo de seguridad: autenticación VNC
        await stream.read(1)
        challenge = os.urandom(16)
        await websocket.send(challenge)
        if await stream.read(16) != des_encrypt(_vnc_des(PASSWORD), challenge):
            reason = b"Authentication failed"
            await websocket.send(struct.pack("!II", 1, len(reason)) + reason)
            return
        await websocket.send(struct.pack("!I", 0))
        await stream.read(1)  # ClientInit
        name = b"falso"
        init = struct.pack("!HH", *SIZE) + PixelFormat().to_bytes()
        await websocket.send(init + struct.pack("!I", len(name)) + name)

        while True:
            kind = (await stream.read(1))[0]
            if kind == 0:  # SetPixelFormat
                await stream.read(19)
            elif kind == 2:  # SetEncodings
                _, count = struct.unpack("!BH", await stream.read(3))
                self.encodings = list(struct.unpack(f"!{count}i", await stream.read(4 * count)))
            elif kind == 3:  # FramebufferUpdateRequest
                incremental = (await stream.read(9))[0]
                if incremental:
                    self._waiting = websocket
                else:
                    await self._send_screen(websocket)
            elif kind == 4:  # KeyEvent
                down, keysym = struct.unpack("!BxxI", await stream.read(7))
                self.events.append(("key", bool(down), keysym, time.monotonic()))
            elif kind == 5:  # PointerEvent
                mask, x, y = struct.unpack("!BHH", await stream.read(5))
                self.events.append(("pointer", mask, x, y, time.monotonic()))
                released = self._buttons & 1 and not mask & 1
                self._buttons = mask
                if released and self.on_click:
                    self.on_click()
            else:
                raise AssertionError(f"mensaje inesperado del cliente: {kind}")

    async def paint(self, color: tuple[int, int, int]) -> None:
        self.color = color
        websocket, self._waiting = self._waiting, None
        if websocket is not None:
            await self._send_screen(websocket)

    def paint_later(self, color: tuple[int, int, int], delay: float) -> None:
        async def later() -> None:
            await asyncio.sleep(delay)
            await self.paint(color)

        self._spawn(later())

    def flicker(self, period: float) -> None:
        """Cambia de color sin parar y sin repetir, como una animación."""

        async def forever() -> None:
            for index in range(10_000):
                level = index % 200
                await self.paint((level, level, level))
                await asyncio.sleep(period)

        self._spawn(forever())

    def stop(self) -> None:
        for task in self._tasks:
            task.cancel()

    def key_events(self) -> list[tuple[bool, int]]:
        return [(down, keysym) for kind, down, keysym, _ in self._of("key")]

    def pointer_events(self) -> list[tuple[int, int, int]]:
        return [(mask, x, y) for kind, mask, x, y, _ in self._of("pointer")]

    def _of(self, kind: str) -> list[tuple]:
        return [event for event in self.events if event[0] == kind]

    def _spawn(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _send_screen(self, websocket) -> None:
        width, height = SIZE
        header = struct.pack("!BxH", 0, 1) + struct.pack("!HHHHi", 0, 0, width, height, 0)
        pixels = bytes([*self.color, 0]) * (width * height)  # RGBX, el formato por defecto
        async with self._send_lock:
            with contextlib.suppress(ConnectionClosed):
                await websocket.send(header + pixels)


class _Stream:
    """Lee bytes exactos de un WebSocket: el puente no respeta los límites de los mensajes."""

    def __init__(self, websocket) -> None:
        self.websocket = websocket
        self.buffer = bytearray()

    async def read(self, size: int) -> bytes:
        while len(self.buffer) < size:
            self.buffer += await self.websocket.recv()
        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data


@pytest.fixture
async def server():
    fake = FakeRFBServer()
    async with serve(fake.handler, "127.0.0.1", 0, subprotocols=["binary"]) as ws_server:
        fake.url = f"ws://127.0.0.1:{ws_server.sockets[0].getsockname()[1]}/websockify"
        yield fake
        fake.stop()


def make_settings(**overrides) -> Settings:
    values = {
        "change_timeout_s": 0.4,
        "stable_interval_s": 0.1,
        "stable_timeout_s": 0.6,
        "diff_min_pixels": 10,
    }
    values.update(overrides)
    return Settings(_env_file=None, team_token="t", openrouter_api_key="k", **values)


def session(server: FakeRFBServer, **overrides) -> DesktopSession:
    return DesktopSession(server.url, PASSWORD, make_settings(**overrides))


async def until_closed(server: FakeRFBServer) -> None:
    """Tras salir de la sesión: el servidor ya procesó todos los eventos."""
    await asyncio.wait_for(server.closed.wait(), TIMEOUT)


# --- Conexión


async def test_connects_reads_size_and_screen_and_disconnects(server, caplog):
    caplog.set_level(logging.DEBUG)
    async with session(server) as desktop:
        assert desktop.size == SIZE
        screen = await desktop.screenshot()
        assert (screen.size, screen.mode) == (SIZE, "RGB")
        assert screen.getpixel((0, 0)) == WHITE

    await until_closed(server)
    assert ENCODING_ZRLE in server.encodings
    assert ENCODING_CURSOR in server.encodings  # el cursor no se dibuja en las capturas
    with pytest.raises(DesktopError) as error:
        await desktop.screenshot()
    assert error.value.code is ErrorCode.WS_DISCONNECTED
    assert PASSWORD not in caplog.text


async def test_wrong_password_is_vnc_auth_failed_and_is_not_retried(server, caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(DesktopError) as error:
        async with DesktopSession(server.url, "otra-clave", make_settings()):
            pass
    assert error.value.code is ErrorCode.VNC_AUTH_FAILED
    assert server.connections == 1
    assert "otra-clave" not in str(error.value)
    assert "otra-clave" not in caplog.text


async def test_rejected_websocket_is_vnc_connect_failed_after_two_attempts(monkeypatch):
    monkeypatch.setattr(client_module, "_CONNECT_RETRY_DELAY_S", 0)
    attempts = []

    def reject(connection, request):
        attempts.append(request.path)
        return connection.respond(HTTPStatus.FORBIDDEN, "no\n")

    async with serve(lambda ws: None, "127.0.0.1", 0, process_request=reject) as ws_server:
        url = f"ws://127.0.0.1:{ws_server.sockets[0].getsockname()[1]}/websockify?token=abc"
        with pytest.raises(DesktopError) as error:
            async with DesktopSession(url, PASSWORD, make_settings()):
                pass

    assert error.value.code is ErrorCode.VNC_CONNECT_FAILED
    assert len(attempts) == 2
    assert "403" in str(error.value)
    assert url not in str(error.value)


async def test_dropped_websocket_is_ws_disconnected(server):
    async with session(server) as desktop:
        await server.websockets[0].close()
        with pytest.raises(DesktopError) as error:
            for _ in range(100):
                await desktop.screenshot()
                await asyncio.sleep(0.02)
        assert error.value.code is ErrorCode.WS_DISCONNECTED
        with pytest.raises(DesktopError) as error:
            await desktop.click(1, 1)
        assert error.value.code is ErrorCode.WS_DISCONNECTED


# --- Acciones


async def test_click_holds_the_button_between_down_and_up(server):
    async with session(server) as desktop:
        await desktop.click(10, 20)
    await until_closed(server)

    assert server.pointer_events() == [(0, 10, 20), (1, 10, 20), (0, 10, 20)]
    down, up = server._of("pointer")[1:]
    assert up[-1] - down[-1] >= 0.14  # CLICK_HOLD_MS = 150; menos de 100 ms se ignora


async def test_double_click_is_two_held_clicks(server):
    async with session(server, double_click_hold_ms=120) as desktop:
        await desktop.click(5, 6, double=True)
    await until_closed(server)

    assert server.pointer_events() == [(0, 5, 6), (1, 5, 6), (0, 5, 6), (1, 5, 6), (0, 5, 6)]
    times = [event[-1] for event in server._of("pointer")]
    assert times[2] - times[1] >= 0.11
    assert times[4] - times[3] >= 0.11
    assert times[4] - times[1] < 0.5  # dentro de la ventana de doble clic


async def test_a_cancelled_click_still_releases_the_button(server):
    async with session(server) as desktop:
        task = asyncio.create_task(desktop.click(3, 4))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.3)
    await until_closed(server)

    assert server.pointer_events()[-2:] == [(1, 3, 4), (0, 3, 4)]


async def test_type_text_selects_all_and_then_types_each_character(server):
    async with session(server) as desktop:
        await desktop.type_text("Papelería #1")
    await until_closed(server)

    expected = [(True, CTRL), (True, ord("a")), (False, ord("a")), (False, CTRL)]
    for char in "Papelería #1":
        expected += [(True, ord(char)), (False, ord(char))]
    assert server.key_events() == expected
    assert (True, 0xED) in server.key_events()  # í


async def test_type_text_with_empty_text_clears_the_field(server):
    async with session(server) as desktop:
        await desktop.type_text("")
    await until_closed(server)

    assert server.key_events()[4:] == [(True, 0xFF08), (False, 0xFF08)]  # backspace tras ctrl+a


async def test_press_sends_the_combination(server):
    async with session(server) as desktop:
        await desktop.press("ctrl+shift+s")
        await desktop.press("enter")
    await until_closed(server)

    s = ord("s")
    assert server.key_events() == [
        (True, CTRL),
        (True, SHIFT),
        (True, s),
        (False, s),
        (False, SHIFT),
        (False, CTRL),
        (True, 0xFF0D),
        (False, 0xFF0D),
    ]


async def test_scroll_uses_the_wheel_buttons(server):
    async with session(server) as desktop:
        await desktop.scroll(7, 8, "down", 2)
        await desktop.scroll(7, 8, "up", 1)
    await until_closed(server)

    assert server.pointer_events() == [
        (0, 7, 8),
        (16, 7, 8),  # botón 5
        (0, 7, 8),
        (16, 7, 8),
        (0, 7, 8),
        (0, 7, 8),
        (8, 7, 8),  # botón 4
        (0, 7, 8),
    ]


async def test_invalid_actions_are_rejected_before_sending(server):
    async with session(server) as desktop:
        for x, y in [(64, 0), (0, 48), (-1, 5)]:
            with pytest.raises(ValueError):
                await desktop.click(x, y)
        with pytest.raises(ValueError):
            await desktop.scroll(1, 1, "left", 1)
        with pytest.raises(ValueError):
            await desktop.scroll(1, 1, "down", 0)
        with pytest.raises(ValueError):
            await desktop.type_text("Calle 1\nCasa 2")
        with pytest.raises(ValueError):
            await desktop.press("hyper-espacio")
    await until_closed(server)

    assert server.events == []


@pytest.mark.parametrize(
    ("combo", "keysyms"),
    [
        ("enter", [0xFF0D]),
        ("Ctrl+A", [CTRL, ord("a")]),
        ("shift+tab", [SHIFT, 0xFF09]),
        ("alt+f4", [ALT, 0xFFC1]),
        ("esc", [0xFF1B]),
        ("ctrl++", [CTRL, ord("+")]),
        ("+", [ord("+")]),
        (" ctrl + 0 ", [CTRL, ord("0")]),
        ("supr", [0xFFFF]),
    ],
)
def test_combo_keysyms(combo, keysyms):
    assert combo_keysyms(combo) == keysyms


@pytest.mark.parametrize("combo", ["", "ctrl+", "hyperspace", "ctrl+ab"])
def test_combo_keysyms_rejects_unknown_keys(combo):
    with pytest.raises(ValueError):
        combo_keysyms(combo)


def test_text_keysyms():
    assert text_keysyms("Ñandú & Cía.") == [ord(char) for char in "Ñandú & Cía."]
    assert text_keysyms("€") == [0x010020AC]  # fuera de Latin-1: prefijo Unicode de X11
    for text in ["a\nb", "a\tb", "\r"]:
        with pytest.raises(ValueError):
            text_keysyms(text)


# --- settle


async def test_settle_waits_for_a_delayed_repaint(server):
    server.on_click = lambda: server.paint_later(BLACK, 0.25)
    async with session(server, change_timeout_s=0.6) as desktop:
        before = await desktop.screenshot()
        await desktop.click(1, 1)
        started = time.monotonic()
        after = await desktop.settle(before)
        elapsed = time.monotonic() - started

    assert after.getpixel((0, 0)) == BLACK
    assert elapsed < 0.6 + 0.6  # ventana de cambio + estabilidad


async def test_settle_does_not_stop_at_a_hover_before_the_click_repaints(server):
    """Un hover se pinta al instante y queda quieto; el efecto del clic llega después."""

    def on_click() -> None:
        server.paint_later(GRAY, 0)
        server.paint_later(BLACK, 0.4)

    server.on_click = on_click
    async with session(server, change_timeout_s=0.6) as desktop:
        before = await desktop.screenshot()
        await desktop.click(1, 1)
        after = await desktop.settle(before)

    assert after.getpixel((0, 0)) == BLACK


async def test_settle_without_change_returns_the_same_screen_after_the_window(server):
    async with session(server, change_timeout_s=0.4) as desktop:
        before = await desktop.screenshot()
        await desktop.click(1, 1)
        started = time.monotonic()
        after = await desktop.settle(before)
        elapsed = time.monotonic() - started

    assert after.getpixel((0, 0)) == WHITE
    assert 0.35 <= elapsed < 1.0


async def test_settle_gives_up_on_a_screen_that_never_stabilizes(server, caplog):
    server.on_click = lambda: server.flicker(0.03)
    async with session(server, change_timeout_s=0.2, stable_timeout_s=0.5) as desktop:
        before = await desktop.screenshot()
        await desktop.click(1, 1)
        started = time.monotonic()
        after = await desktop.settle(before)
        elapsed = time.monotonic() - started
        server.stop()

    assert after.getpixel((0, 0)) != WHITE
    assert elapsed < 1.2
    assert "SCREEN_NOT_STABLE" in caplog.text
