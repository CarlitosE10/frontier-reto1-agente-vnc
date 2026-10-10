"""Puente local TCP ↔ WebSocket hacia el escritorio (diseño D1).

`vncdotool` solo habla RFB sobre TCP y el escritorio solo expone `wss://…/websockify`. El puente
escucha en `127.0.0.1`, en un puerto efímero, y por cada conexión TCP abre un WebSocket con
subprotocolo `binary` hacia la URL de la tarea y copia bytes en ambos sentidos. Cuando un lado se
cierra, cierra el otro.

    async with Bridge(url) as bridge:
        conectar vncdotool a bridge.host, bridge.port
"""

import asyncio
import contextlib
import logging
from types import TracebackType
from typing import Self

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

log = logging.getLogger(__name__)

SUBPROTOCOL = "binary"
_CHUNK_BYTES = 64 * 1024


class Bridge:
    host = "127.0.0.1"

    def __init__(self, url: str, open_timeout: float = 10.0, close_timeout: float = 2.0) -> None:
        self.url = url
        self.open_timeout = open_timeout
        self.close_timeout = close_timeout
        self.port = 0
        # Último error al abrir el WebSocket. El cliente VNC lo usa para explicar por qué se
        # cerró la conexión antes del saludo RFB.
        self.error: Exception | None = None
        self._server: asyncio.Server | None = None
        self._connections: set[asyncio.Task] = set()

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def close(self) -> None:
        """Deja de aceptar conexiones y cierra las abiertas, en ambos lados."""
        server, self._server = self._server, None
        if server is not None:
            server.close()
        for task in list(self._connections):
            task.cancel()
        await asyncio.gather(*self._connections, return_exceptions=True)
        if server is not None:
            await server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        self._connections.add(task)
        try:
            try:
                websocket = await connect(
                    self.url,
                    subprotocols=[SUBPROTOCOL],
                    open_timeout=self.open_timeout,
                    close_timeout=self.close_timeout,
                    max_size=None,  # una actualización RAW de pantalla completa pesa ~4 MB
                )
            except Exception as error:
                # La URL no se registra: llega del evaluador y no hace falta para diagnosticar.
                self.error = error
                log.warning("Puente: no se pudo abrir el WebSocket (%s)", type(error).__name__)
                return
            async with websocket:
                await _copy_both_ways(reader, writer, websocket)
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            self._connections.discard(task)


async def _copy_both_ways(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, websocket: ClientConnection
) -> None:
    """Copia hasta que un lado se cierra y luego detiene el otro sentido.

    Si el que cierra es el escritorio, registra el código y la razón del cierre: es lo único que
    distingue un visor que tomó la pantalla, un reinicio del escritorio o una red caída
    (`WS_DISCONNECTED`).
    """
    to_websocket = asyncio.create_task(_tcp_to_websocket(reader, websocket))
    from_websocket = asyncio.create_task(_websocket_to_tcp(websocket, writer))
    directions = [to_websocket, from_websocket]
    try:
        done, _ = await asyncio.wait(directions, return_when=asyncio.FIRST_COMPLETED)
        if from_websocket in done and to_websocket not in done:
            log.warning(
                "Puente: el escritorio cerró el WebSocket (código %s, razón %r)",
                websocket.close_code,
                websocket.close_reason or "",
            )
    finally:
        for task in directions:
            task.cancel()
        await asyncio.gather(*directions, return_exceptions=True)


async def _tcp_to_websocket(reader: asyncio.StreamReader, websocket: ClientConnection) -> None:
    with contextlib.suppress(ConnectionError, ConnectionClosed):
        while data := await reader.read(_CHUNK_BYTES):
            await websocket.send(data)


async def _websocket_to_tcp(websocket: ClientConnection, writer: asyncio.StreamWriter) -> None:
    with contextlib.suppress(ConnectionError, ConnectionClosed):
        async for message in websocket:
            writer.write(message if isinstance(message, bytes) else message.encode())
            await writer.drain()
