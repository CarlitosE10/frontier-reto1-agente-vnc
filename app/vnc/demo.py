"""Demostración y exploración del escritorio propio con `DesktopSession` (plan T03).

Se conecta al escritorio de EVAL_DESKTOP_URL con EVAL_DESKTOP_PASSWORD y ejecuta los pasos en
orden, en una sola sesión. Después de cada acción espera con `settle` e informa cuánto cambió la
pantalla y en cuánto tiempo.

    python -m app.vnc.demo captura:antes clic:300,120 "escribir:Papelería #1" captura:despues

Pasos:
    captura:NOMBRE          guarda la pantalla en <salida>/NOMBRE.png
    clic:X,Y   doble:X,Y    clic o doble clic
    escribir:TEXTO          ctrl+a y luego el texto
    tecla:COMBO             por ejemplo enter, tab, esc, ctrl+a
    rueda:X,Y,up|down,N     N pasos de la rueda del mouse
    esperar:S               pausa de S segundos
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

from app.config import EvalSettings, Settings
from app.vnc.client import DesktopError, DesktopSession, _changed_pixels


async def run(steps: list[str], output: Path) -> None:
    eval_settings = EvalSettings()
    password = eval_settings.eval_desktop_password.get_secret_value()
    session = DesktopSession(eval_settings.eval_desktop_url, password, Settings())
    output.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    async with session as desktop:
        print(f"conectado en {time.monotonic() - started:.1f} s, pantalla {desktop.size}")
        for step in steps:
            name, _, argument = step.partition(":")
            if name == "captura":
                path = output / f"{argument}.png"
                (await desktop.screenshot()).save(path)
                print(f"captura → {path}")
                continue
            if name == "esperar":
                await asyncio.sleep(float(argument))
                continue

            before = await desktop.screenshot()
            started = time.monotonic()
            await _act(desktop, name, argument)
            sent = time.monotonic()
            after = await desktop.settle(before)
            changed = _changed_pixels(before, after)
            print(
                f"{step}: {changed} px distintos; acción {sent - started:.2f} s, "
                f"settle {time.monotonic() - sent:.2f} s"
            )


async def _act(desktop: DesktopSession, name: str, argument: str) -> None:
    if name in ("clic", "doble"):
        x, y = (int(value) for value in argument.split(","))
        await desktop.click(x, y, double=name == "doble")
    elif name == "escribir":
        await desktop.type_text(argument)
    elif name == "tecla":
        await desktop.press(argument)
    elif name == "rueda":
        x, y, direction, amount = argument.split(",")
        await desktop.scroll(int(x), int(y), direction, int(amount))
    else:
        raise ValueError(f"Paso desconocido: {name!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.vnc.demo",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("pasos", nargs="+")
    parser.add_argument("--salida", type=Path, default=Path("traces/demo"))
    args = parser.parse_args(argv)
    try:
        asyncio.run(run(args.pasos, args.salida))
    except DesktopError as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
