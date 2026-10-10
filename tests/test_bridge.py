"""Puente TCP ↔ WebSocket y sonda (T02), contra un servidor WebSocket local."""

import asyncio
import socket

import pytest
from websockets.asyncio.server import serve

from app.vnc.bridge import Bridge
from app.vnc.probe import main as probe_main
from app.vnc.probe import read_greeting

GREETING = b"RFB 003.008\n"
TIMEOUT = 5


class EchoServer:
    """Saluda como un servidor RFB y luego devuelve cada mensaje que recibe."""

    def __init__(self) -> None:
        self.subprotocols: list[str | None] = []
        self.closed = asyncio.Event()
        self.connections = []

    async def handler(self, websocket) -> None:
        self.subprotocols.append(websocket.subprotocol)
        self.connections.append(websocket)
        try:
            await websocket.send(GREETING)
            async for message in websocket:
                if message == b"grande":
                    await websocket.send(b"x" * 5_000_000)
                else:
                    await websocket.send(message)
        finally:
            self.closed.set()


@pytest.fixture
async def echo():
    server = EchoServer()
    async with serve(server.handler, "127.0.0.1", 0, subprotocols=["binary"]) as ws_server:
        port = ws_server.sockets[0].getsockname()[1]
        server.url = f"ws://127.0.0.1:{port}/websockify"
        yield server


async def read_exactly(reader: asyncio.StreamReader, size: int) -> bytes:
    return await asyncio.wait_for(reader.readexactly(size), TIMEOUT)


async def test_copies_bytes_both_ways_with_binary_subprotocol(echo):
    async with Bridge(echo.url) as bridge:
        assert bridge.host == "127.0.0.1"
        assert bridge.port > 0
        reader, writer = await asyncio.open_connection(bridge.host, bridge.port)

        assert await read_exactly(reader, len(GREETING)) == GREETING
        writer.write(b"RFB 003.008\n")
        assert await read_exactly(reader, 12) == b"RFB 003.008\n"
        writer.write(bytes(range(256)))
        assert await read_exactly(reader, 256) == bytes(range(256))

        writer.close()
    assert echo.subprotocols == ["binary"]


async def test_large_server_messages_pass_through(echo):
    async with Bridge(echo.url) as bridge:
        reader, writer = await asyncio.open_connection(bridge.host, bridge.port)
        await read_exactly(reader, len(GREETING))
        writer.write(b"grande")
        assert await read_exactly(reader, 5_000_000) == b"x" * 5_000_000
        writer.close()


async def test_closing_the_tcp_side_closes_the_websocket(echo):
    async with Bridge(echo.url) as bridge:
        reader, writer = await asyncio.open_connection(bridge.host, bridge.port)
        await read_exactly(reader, len(GREETING))
        writer.close()
        await asyncio.wait_for(echo.closed.wait(), TIMEOUT)


async def test_closing_the_websocket_closes_the_tcp_side(echo):
    async with Bridge(echo.url) as bridge:
        reader, writer = await asyncio.open_connection(bridge.host, bridge.port)
        await read_exactly(reader, len(GREETING))
        await echo.connections[0].close()
        assert await asyncio.wait_for(reader.read(), TIMEOUT) == b""
        writer.close()


async def test_a_close_from_the_desktop_is_logged_with_its_code(echo, caplog):
    async with Bridge(echo.url) as bridge:
        reader, writer = await asyncio.open_connection(bridge.host, bridge.port)
        await read_exactly(reader, len(GREETING))
        await echo.connections[0].close(code=1008, reason="otro visor tomó la pantalla")
        assert await asyncio.wait_for(reader.read(), TIMEOUT) == b""
        writer.close()

    assert "código 1008, razón 'otro visor tomó la pantalla'" in caplog.text


async def test_our_own_close_is_not_logged_as_a_desktop_close(echo, caplog):
    async with Bridge(echo.url) as bridge:
        reader, writer = await asyncio.open_connection(bridge.host, bridge.port)
        await read_exactly(reader, len(GREETING))
        writer.close()
        await asyncio.wait_for(echo.closed.wait(), TIMEOUT)

    assert "el escritorio cerró" not in caplog.text


async def test_close_ends_open_connections_and_stops_listening(echo):
    bridge = Bridge(echo.url)
    await bridge.start()
    reader, writer = await asyncio.open_connection(bridge.host, bridge.port)
    await read_exactly(reader, len(GREETING))

    await asyncio.wait_for(bridge.close(), TIMEOUT)

    assert await asyncio.wait_for(reader.read(), TIMEOUT) == b""
    await asyncio.wait_for(echo.closed.wait(), TIMEOUT)
    with pytest.raises(OSError):
        await asyncio.open_connection(bridge.host, bridge.port)
    writer.close()


async def test_unreachable_websocket_closes_the_tcp_side_and_keeps_the_error():
    with socket.socket() as probe:  # un puerto libre, sin nadie escuchando
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    async with Bridge(f"ws://127.0.0.1:{port}/websockify", open_timeout=1) as bridge:
        reader, writer = await asyncio.open_connection(bridge.host, bridge.port)
        assert await asyncio.wait_for(reader.read(), TIMEOUT) == b""
        assert isinstance(bridge.error, OSError)
        writer.close()


async def test_probe_reads_the_rfb_greeting(echo):
    assert await read_greeting(echo.url) == "RFB 003.008"


def test_probe_cli_reports_failure_without_traceback(capsys):
    assert probe_main(["ws://127.0.0.1:9/websockify", "--timeout", "1"]) == 1
    assert "Sin saludo RFB" in capsys.readouterr().err
