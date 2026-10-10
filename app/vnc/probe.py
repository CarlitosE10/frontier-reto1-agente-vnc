"""Sonda: imprime el saludo RFB del escritorio.

Uso: python -m app.vnc.probe wss://<escritorio>/websockify

Solo abre el WebSocket y lee los 12 bytes del saludo (`RFB 003.008`); no necesita la contraseña.
Sale con código 0 si el saludo es RFB.
"""

import argparse
import asyncio
import sys

from websockets.asyncio.client import connect

from app.vnc.bridge import SUBPROTOCOL

_GREETING_BYTES = 12  # "RFB xxx.yyy\n"


async def read_greeting(url: str, timeout: float = 10.0) -> str:
    async with connect(url, subprotocols=[SUBPROTOCOL], open_timeout=timeout) as websocket:
        data = b""
        while len(data) < _GREETING_BYTES:
            message = await asyncio.wait_for(websocket.recv(), timeout)
            data += message if isinstance(message, bytes) else message.encode()
    return data[:_GREETING_BYTES].decode("ascii", errors="replace").strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.vnc.probe", description=__doc__)
    parser.add_argument("url", help="wss://<escritorio>/websockify")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)
    try:
        greeting = asyncio.run(read_greeting(args.url, args.timeout))
    except Exception as error:
        print(f"Sin saludo RFB: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(greeting)
    return 0 if greeting.startswith("RFB ") else 1


if __name__ == "__main__":
    sys.exit(main())
