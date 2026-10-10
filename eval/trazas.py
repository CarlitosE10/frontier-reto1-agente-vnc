"""Trazas para el debrief: bajar las de la evaluación oculta y resumir cada tarea.

El evaluador no nos da sus `task_id`, pero el agente los registra en el log del servidor
(`tarea recibida` y `tarea finalizada`). `bajar` toma cualquier texto que los contenga (por
ejemplo, la salida de `railway logs`), saca los identificadores de 32 caracteres hexadecimales y
guarda la traza de cada uno con `GET /tasks/{id}/traza`, pasada por `redact`. `resumir` arma una
ficha por tarea:

- la instrucción, el estado, el código de error, los pasos, la duración y el costo;
- el primer paso que se desvía: un código de error, un bloqueo de la verificación, texto que no
  aparece después de escribir, o un cierre rechazado;
- los bloqueos de la verificación y la decisión sobre el último cierre;
- una categoría para empezar a explicar la falla (runbook, sección 5).

Uso:
  railway logs --service agente-vnc --lines 5000 --filter "tarea finalizada" > finalizadas.log
  uv run python -m eval.trazas bajar finalizadas.log --agente https://… --salida eval/reports/oculta
  uv run python -m eval.trazas resumir eval/reports/oculta/*.json > eval/reports/oculta/resumen.md

`bajar` lee `AGENT_TOKEN` (y, para sanear, `EVAL_DESKTOP_PASSWORD` y `EVAL_DESKTOP_TOKEN`) de
`EvalSettings`. `resumir` funciona también con las trazas de los reportes del arnés.
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import httpx

from app.config import EvalSettings
from eval.harness import redact

_TASK_ID = re.compile(r"\b[0-9a-f]{32}\b")
TEXT_CHARS = 300

# Categoría de partida por código de error (runbook, sección 5).
CATEGORIES = {
    "VNC_CONNECT_FAILED": "conexión",
    "VNC_AUTH_FAILED": "conexión",
    "WS_DISCONNECTED": "conexión",
    "SCREEN_NOT_STABLE": "interacción",
    "CLICK_NO_EFFECT": "interacción",
    "LOOP_DETECTED": "interacción",
    "VLM_ERROR": "modelo",
    "GATE_BLOCKED": "verificación",
    "BUDGET_EXHAUSTED": "presupuesto",
    "CANCELLED": "cancelada",
}
# Aparecen también en tareas que salen bien (un clic de enfoque sobre un campo que ya tenía el
# foco no cambia la pantalla): se listan aparte y no cuentan como primer desvío.
MINOR_CODES = {"CLICK_NO_EFFECT", "SCREEN_NOT_STABLE"}


def task_ids(text: str) -> list[str]:
    """Identificadores de tarea en el orden en que aparecen, sin repetidos."""
    return list(dict.fromkeys(_TASK_ID.findall(text)))


# --- Bajar ---


async def download(
    client: httpx.AsyncClient, ids: list[str], out_dir: Path, secrets: dict[str, str]
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for task_id in ids:
        response = await client.get(f"/tasks/{task_id}/traza")
        if response.status_code != 200:
            print(f"{task_id}: HTTP {response.status_code}", file=sys.stderr)
            continue
        path = out_dir / f"{task_id}.json"
        text = json.dumps(response.json(), ensure_ascii=False, indent=1)
        path.write_text(redact(text, secrets), encoding="utf-8")
        saved.append(path)
    return saved


# --- Resumir ---


def _short(text: object, limit: int = TEXT_CHARS) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _describe(action: dict) -> str:
    kind = action.get("kind", "?")
    if kind in ("click", "double_click"):
        return (
            f"clic en ({action.get('x')}, {action.get('y')}) sobre «{action.get('objetivo')}» "
            f"[{action.get('efecto')}]"
        )
    if kind == "type_text":
        return f"escribir «{_short(action.get('texto'), 60)}» en {action.get('campo')}"
    if kind == "press_key":
        return f"tecla {action.get('combinacion')}"
    if kind == "finish_task":
        return f"finish_task, respuesta {action.get('respuesta')}"
    if kind == "fail_task":
        return f"fail_task: {_short(action.get('razon'), 120)}"
    return kind


def _deviation(step: dict) -> tuple[str, str] | None:
    """Por qué este paso se desvía y su categoría, o None si no se desvía."""
    verdict = step.get("verificacion") or {}
    if verdict.get("outcome") == "block":
        if (step.get("accion") or {}).get("kind") == "finish_task":
            return "cierre rechazado por la verificación", "verificación (cierre rechazado)"
        return "acción bloqueada por la verificación", "verificación (acción bloqueada)"
    if step.get("texto_visible") is False:
        return "el texto escrito no aparece en la pantalla", "interacción (texto que no entró)"
    code = step.get("error_code")
    if code and code not in MINOR_CODES:
        return f"código {code}", CATEGORIES.get(code, "?")
    return None


def summarize(name: str, events: list[dict]) -> str:
    """Ficha en Markdown de una tarea a partir de los eventos de su traza.

    La categoría sale del primer paso que se desvía, no del código final: un `LOOP_DETECTED`
    suele ser la consecuencia de un cierre rechazado o de un clic que no cayó donde debía.
    """
    start = next((e for e in events if e.get("evento") == "inicio"), {})
    end = next((e for e in reversed(events) if e.get("evento") == "fin"), {})
    steps = [e for e in events if isinstance(e.get("paso"), int)]
    code = end.get("error_code")
    blocks = [s for s in steps if (s.get("verificacion") or {}).get("outcome") == "block"]
    first = next(((s, found) for s in steps if (found := _deviation(s))), None)
    final_kind = (steps[-1].get("accion") or {}).get("kind") if steps else None

    if first:
        category = first[1][1]
    elif code:
        category = CATEGORIES.get(code, "?")
    elif end.get("estado") == "fallida" and final_kind == "fail_task":
        category = "decisión del agente (fail_task)"
    elif end.get("estado") == "terminada":
        category = "terminada (revisar contra lo esperado)"
    else:
        category = "sin evento fin (traza incompleta)"

    cost = end.get("cost_usd")
    lines = [
        f"## {name}",
        "",
        f"- **Tarea:** {_short(start.get('tarea'))}",
        f"- **Resultado:** {end.get('estado', '?')}"
        + (f" · `{code}`" if code else "")
        + f" · {len(steps)} pasos · {end.get('elapsed_s', '?')} s"
        + (f" · US${cost:.4f}" if isinstance(cost, int | float) else ""),
        f"- **Categoría de partida:** {category}",
    ]
    if first:
        step, (why, _) = first
        action = _describe(step.get("accion") or {})
        lines += [
            f"- **Primer desvío:** paso {step['paso']}, {why}: {action}",
            f"  - observación: {_short(step.get('observacion'))}",
            f"  - resultado: {_short(step.get('resultado'))}",
        ]
    minor = [s for s in steps if s.get("error_code") in MINOR_CODES]
    if minor:
        lines.append(
            "- **Avisos menores:** "
            + "; ".join(
                f"paso {s['paso']} {s['error_code']} ({_describe(s.get('accion') or {})})"
                for s in minor
            )
        )
    for step in blocks:
        verdict = step["verificacion"]
        failed = [k for k, ok in (verdict.get("checks") or {}).items() if not ok]
        lines.append(
            f"- **Bloqueo** en el paso {step['paso']} ({', '.join(failed) or 'sin chequeos'}): "
            f"{_short(verdict.get('reason'), 240)}"
        )
    finishes = [
        s
        for s in steps
        if (s.get("accion") or {}).get("kind") == "finish_task" and s.get("verificacion")
    ]
    if finishes:
        verdict = finishes[-1]["verificacion"]
        lines.append(
            f"- **Último cierre:** {verdict.get('outcome')} · {_short(verdict.get('reason'), 240)}"
        )
    lines += [
        "- **Últimos pasos:**",
        *(
            f"  - {s['paso']}. {_describe(s.get('accion') or {})} → "
            f"{_short(s.get('resultado'), 120)}"
            for s in steps[-3:]
        ),
        f"- **Resumen:** {_short(end.get('resumen'), 400)}",
        "",
    ]
    return "\n".join(lines)


def _load(path: Path) -> list[dict]:
    """Una traza en JSON (lista de eventos, como la guarda el arnés) o en JSONL."""
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return data if isinstance(data, list) else []


# --- Línea de comandos ---


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eval.trazas",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    get = commands.add_parser("bajar", help="baja las trazas de los task_id de un texto")
    get.add_argument("fuente", type=Path, help="archivo con los task_id (por ejemplo, el log)")
    get.add_argument("--agente", help="URL del agente (por defecto, AGENT_URL)")
    get.add_argument("--salida", type=Path, default=Path("eval/reports/oculta"))
    show = commands.add_parser("resumir", help="una ficha por traza, en Markdown")
    show.add_argument("trazas", type=Path, nargs="+")
    args = parser.parse_args(argv)

    if args.command == "resumir":
        for path in args.trazas:
            print(summarize(path.stem, _load(path)))
        return 0

    ids = task_ids(args.fuente.read_text(encoding="utf-8"))
    if not ids:
        parser.error(f"{args.fuente} no tiene ningún task_id")
    settings = EvalSettings()
    secrets = {
        "contraseña del escritorio": settings.eval_desktop_password.get_secret_value(),
        "token del escritorio": settings.eval_desktop_token.get_secret_value(),
        "token del agente": settings.agent_token.get_secret_value(),
    }

    async def run() -> list[Path]:
        async with httpx.AsyncClient(
            base_url=args.agente or settings.agent_url,
            headers={"Authorization": f"Bearer {secrets['token del agente']}"},
            timeout=30,
        ) as client:
            return await download(client, ids, args.salida, secrets)

    saved = asyncio.run(run())
    print(f"{len(saved)} de {len(ids)} trazas en {args.salida}")
    return 0 if len(saved) == len(ids) else 1


if __name__ == "__main__":
    sys.exit(main())
