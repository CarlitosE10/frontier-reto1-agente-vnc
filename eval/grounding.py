"""Comparación de modelos por precisión de clic (plan T13).

Cada archivo de `eval/grounding/*.json` describe una captura real de SIGECOM con objetivos
etiquetados (descripción y recuadro en píxeles, bordes incluidos) y preguntas de estado con
opciones cerradas. Por cada modelo de la lista, con su VLM_COORD_MODE:

- **Objetivo:** se envía la captura con «Haz clic en <descripción>» y, como única herramienta,
  el `click` del agente (`app.agent.tools.TOOLS`). La tool call es válida si `parse_action` la
  acepta, como en el ciclo. El clic acierta si es válido y el punto, ya en píxeles reales, cae
  dentro del recuadro. También se anota si habría acertado leyendo las coordenadas en la otra
  escala: así se ve qué escala usa de verdad el modelo, aunque el prompt pida otra.
- **Estado:** se envía la pregunta con una herramienta `responder` cuyas opciones son las de la
  pregunta, y se compara la opción elegida con la esperada.

El prompt del sistema es corto para que la comparación quepa en el presupuesto: da el tamaño de
la pantalla y el mismo texto de coordenadas que el prompt del agente.

Cada resultado se agrega a un JSONL. Al volver a correr, lo que ya está en el archivo no se
repite (no se paga dos veces), y el gasto total, contando lo que ya está en el archivo, no pasa
de `--max-costo`: antes de cada llamada se reserva el costo más alto visto para ese modelo. Al
final se reescriben las tablas del reporte entre los marcadores `<!-- tablas -->` y
`<!-- /tablas -->`; el resto del reporte (las conclusiones) no se toca.

Uso:
  uv run python -m eval.grounding --modelo anthropic/claude-haiku-5.5=pixels \\
      --modelo qwen/qwen3.7-plus=norm1000 --max-costo 0.25
  uv run python -m eval.grounding --modelo qwen/qwen3.7-plus=pixels \\
      --pantalla clientes-lista --solo-clics       # qué escala usa el modelo
  uv run python -m eval.grounding --solo-reporte   # rehace las tablas sin llamar a modelos
"""

import argparse
import asyncio
import json
import math
import statistics
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

# El mismo texto de coordenadas que lee el agente en su prompt del sistema.
from app.agent.prompts import _COORDINATES
from app.agent.tools import TOOLS, ActionError, parse_action
from app.config import Settings
from app.llm.openrouter import ChatResult, LLMError, OpenRouterClient, image_part

GROUNDING_DIR = Path(__file__).resolve().parent / "grounding"
RESULTS = GROUNDING_DIR / "resultados.jsonl"
REPORT = GROUNDING_DIR / "reporte.md"
COORD_MODES = ("pixels", "norm1000")
DEFAULT_MAX_COST_USD = 0.30
FIRST_CALL_ESTIMATE_USD = 0.005  # reserva para la primera llamada de un modelo
TABLES_START = "<!-- tablas -->"
TABLES_END = "<!-- /tablas -->"

SYSTEM_PROMPT = """\
Operas una aplicación de escritorio legacy viendo capturas de su pantalla de {width}×{height} \
píxeles. Respondes con exactamente una herramienta.

Coordenadas: {coordinates}\
"""

CLICK_TOOL = next(tool for tool in TOOLS if tool["function"]["name"] == "click")


@dataclass(frozen=True)
class Target:
    id: str
    descripcion: str
    box: tuple[int, int, int, int]  # x1, y1, x2, y2, bordes incluidos


@dataclass(frozen=True)
class StateQuestion:
    id: str
    pregunta: str
    opciones: tuple[str, ...]
    respuesta: str


@dataclass(frozen=True)
class Screen:
    name: str
    captura: Path
    pantalla: str
    objetivos: tuple[Target, ...]
    estados: tuple[StateQuestion, ...]


@dataclass(frozen=True)
class ModelConfig:
    model: str
    coord_mode: str

    @classmethod
    def parse(cls, text: str) -> "ModelConfig":
        """`qwen/qwen3.7-plus=norm1000`; sin `=`, pixels."""
        model, _, mode = text.partition("=")
        mode = mode or "pixels"
        if not model or mode not in COORD_MODES:
            raise ValueError(f"modelo inválido: {text!r} (usa modelo=pixels o modelo=norm1000)")
        return cls(model, mode)


# --- Pantallas y mensajes


def load_screens(directory: Path = GROUNDING_DIR, root: Path | None = None) -> list[Screen]:
    """Lee los `*.json` de `directory`. `captura` es relativa a la raíz del repositorio."""
    root = root or directory.resolve().parents[1]
    screens = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        screens.append(
            Screen(
                name=path.stem,
                captura=root / data["captura"],
                pantalla=data["pantalla"],
                objetivos=tuple(
                    Target(t["id"], t["descripcion"], tuple(t["box"])) for t in data["objetivos"]
                ),
                estados=tuple(
                    StateQuestion(q["id"], q["pregunta"], tuple(q["opciones"]), q["respuesta"])
                    for q in data.get("estados", [])
                ),
            )
        )
    return screens


def system_prompt(size: tuple[int, int], coord_mode: str) -> str:
    width, height = size
    coordinates = _COORDINATES[coord_mode].format(max_x=width - 1, max_y=height - 1)
    return SYSTEM_PROMPT.format(width=width, height=height, coordinates=coordinates)


def click_messages(image: Image.Image, coord_mode: str, target: Target) -> list[dict]:
    text = f"Haz clic en {target.descripcion}. Apunta al centro del elemento."
    return _messages(image, coord_mode, text)


def state_messages(image: Image.Image, coord_mode: str, question: StateQuestion) -> list[dict]:
    text = f"{question.pregunta}\nResponde con la herramienta responder."
    return _messages(image, coord_mode, text)


def _messages(image: Image.Image, coord_mode: str, text: str) -> list[dict]:
    return [
        {"role": "system", "content": system_prompt(image.size, coord_mode)},
        {"role": "user", "content": [image_part(image), {"type": "text", "text": text}]},
    ]


def answer_tool(question: StateQuestion) -> dict:
    return {
        "type": "function",
        "function": {
            "name": "responder",
            "description": "Responde la pregunta sobre la pantalla con una de las opciones.",
            "parameters": {
                "type": "object",
                "properties": {"opcion": {"type": "string", "enum": list(question.opciones)}},
                "required": ["opcion"],
            },
        },
    }


# --- Puntaje


def to_pixels(x: float, y: float, size: tuple[int, int], coord_mode: str) -> tuple[int, int]:
    """La conversión de `parse_action`, sin rechazar los puntos que caen fuera."""
    if coord_mode == "norm1000":
        width, height = size
        return round(x * width / 1000), round(y * height / 1000)
    return round(x), round(y)


def box_distance(point: tuple[int, int], box: tuple[int, int, int, int]) -> float:
    """Distancia en píxeles del punto al recuadro (0 si cae dentro)."""
    x, y = point
    x1, y1, x2, y2 = box
    return math.hypot(max(x1 - x, 0, x - x2), max(y1 - y, 0, y - y2))


def score_click(
    chat: ChatResult, target: Target, size: tuple[int, int], coord_mode: str
) -> dict[str, Any]:
    row: dict[str, Any] = {"valida": False, "acierto": False, "acierto_otra_escala": False}
    if chat.tool_name != "click":
        row["error"] = f"herramienta {chat.tool_name!r} en vez de click"
        return row
    raw_x, raw_y = chat.arguments.get("x"), chat.arguments.get("y")
    row["x_modelo"], row["y_modelo"] = raw_x, raw_y
    try:
        action = parse_action("click", chat.arguments, size, coord_mode)
    except ActionError as error:
        row["error"] = str(error)
    else:
        row["valida"] = True
        row["x"], row["y"] = action.x, action.y
        row["distancia_px"] = round(box_distance((action.x, action.y), target.box), 1)
        row["acierto"] = row["distancia_px"] == 0
    if _is_number(raw_x) and _is_number(raw_y):
        other = COORD_MODES[1 - COORD_MODES.index(coord_mode)]
        point = to_pixels(float(raw_x), float(raw_y), size, other)
        row["acierto_otra_escala"] = box_distance(point, target.box) == 0
    return row


def score_state(chat: ChatResult, question: StateQuestion) -> dict[str, Any]:
    answer = chat.arguments.get("opcion") if chat.tool_name == "responder" else None
    row: dict[str, Any] = {
        "valida": answer in question.opciones,
        "respuesta": answer,
        "esperada": question.respuesta,
        "correcta": answer == question.respuesta,
    }
    if not row["valida"]:
        row["error"] = f"herramienta {chat.tool_name!r}, opción {answer!r}"
    return row


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


# --- Ejecución


@dataclass(frozen=True)
class Job:
    config: ModelConfig
    screen: Screen
    item: Target | StateQuestion

    @property
    def kind(self) -> str:
        return "clic" if isinstance(self.item, Target) else "estado"

    @property
    def key(self) -> tuple[str, str, str, str, str]:
        config = self.config
        return (config.model, config.coord_mode, self.screen.name, self.kind, self.item.id)


def row_key(row: dict) -> tuple[str, str, str, str, str]:
    return (row["modelo"], row["coord_mode"], row["pantalla"], row["tipo"], row["id"])


def plan_jobs(
    screens: Iterable[Screen], configs: list[ModelConfig], clicks_only: bool = False
) -> list[Job]:
    """Objetivo por objetivo, con todos los modelos seguidos: si el presupuesto se acaba, los
    modelos quedan medidos sobre los mismos objetivos."""
    jobs = []
    for screen in screens:
        items: list[Target | StateQuestion] = list(screen.objetivos)
        if not clicks_only:
            items += screen.estados
        for item in items:
            jobs.extend(Job(config, screen, item) for config in configs)
    return jobs


class Budget:
    """Tope de gasto con reservas: las llamadas en vuelo no pueden pasarse entre todas."""

    def __init__(self, limit_usd: float, spent_usd: float = 0.0) -> None:
        self.limit_usd = limit_usd
        self.spent_usd = spent_usd
        self._reserved_usd = 0.0

    def reserve(self, estimate_usd: float) -> bool:
        if self.spent_usd + self._reserved_usd + estimate_usd > self.limit_usd:
            return False
        self._reserved_usd += estimate_usd
        return True

    def settle(self, estimate_usd: float, cost_usd: float) -> None:
        self._reserved_usd -= estimate_usd
        self.spent_usd += cost_usd


async def run_jobs(
    jobs: list[Job],
    llm: OpenRouterClient,
    budget: Budget,
    results: Path,
    parallel: int = 4,
    known_costs: dict[str, float] | None = None,
) -> tuple[int, int]:
    """Corre los trabajos y agrega cada resultado a `results`. Devuelve (hechos, omitidos por
    presupuesto)."""
    max_cost = dict(known_costs or {})  # costo más alto visto por modelo
    images: dict[Path, Image.Image] = {}
    semaphore = asyncio.Semaphore(parallel)
    done = skipped = 0

    async def run(job: Job) -> None:
        nonlocal done, skipped
        async with semaphore:
            estimate = max_cost.get(job.config.model, FIRST_CALL_ESTIMATE_USD)
            if not budget.reserve(estimate):
                skipped += 1
                return
            cost = 0.0
            try:
                row = await _run_job(job, llm, images)
                cost = row["costo_usd"]
            finally:
                budget.settle(estimate, cost)
            max_cost[job.config.model] = max(max_cost.get(job.config.model, 0.0), cost)
            with results.open("a", encoding="utf-8") as file:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
            done += 1
            _progress(row, budget)

    await asyncio.gather(*(run(job) for job in jobs))
    return done, skipped


async def _run_job(job: Job, llm: OpenRouterClient, images: dict[Path, Image.Image]) -> dict:
    image = images.get(job.screen.captura)
    if image is None:
        image = images[job.screen.captura] = Image.open(job.screen.captura).convert("RGB")
    model, coord_mode, screen, kind, item_id = job.key
    row: dict[str, Any] = {
        "modelo": model,
        "coord_mode": coord_mode,
        "pantalla": screen,
        "tipo": kind,
        "id": item_id,
    }
    if isinstance(job.item, Target):
        messages, tools = click_messages(image, coord_mode, job.item), [CLICK_TOOL]
        failed: dict[str, Any] = {"acierto": False, "acierto_otra_escala": False}
    else:
        messages, tools = state_messages(image, coord_mode, job.item), [answer_tool(job.item)]
        failed = {"respuesta": None, "esperada": job.item.respuesta, "correcta": False}

    try:
        chat = await llm.chat(model, messages, tools)
    except LLMError as error:
        return {
            **row,
            **failed,
            "valida": False,
            "error": str(error),
            "latencia_s": None,
            "costo_usd": 0.0,
        }

    if isinstance(job.item, Target):
        row.update(score_click(chat, job.item, image.size, coord_mode))
    else:
        row.update(score_state(chat, job.item))
    row["latencia_s"] = round(chat.latency_s, 2)
    row["costo_usd"] = chat.cost_usd
    return row


def _progress(row: dict, budget: Budget) -> None:
    if row["tipo"] == "clic":
        outcome = "acierto" if row["acierto"] else "fallo"
    else:
        outcome = "correcta" if row["correcta"] else "incorrecta"
    error = f" · {row['error']}" if row.get("error") else ""
    print(
        f"{row['modelo']} ({row['coord_mode']}) {row['pantalla']}/{row['id']}: {outcome}{error}"
        f" · gasto US${budget.spent_usd:.4f}",
        flush=True,
    )


def read_results(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# --- Reporte


def summarize(rows: list[dict]) -> list[dict]:
    """Una fila por modelo y escala, en el orden en que aparecen."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault((row["modelo"], row["coord_mode"]), []).append(row)
    summary = []
    for (model, mode), group in groups.items():
        clicks = [r for r in group if r["tipo"] == "clic"]
        states = [r for r in group if r["tipo"] == "estado"]
        misses = [r["distancia_px"] for r in clicks if r["valida"] and not r["acierto"]]
        latencies = sorted(r["latencia_s"] for r in group if r["latencia_s"] is not None)
        cost = sum(r["costo_usd"] for r in group)
        summary.append(
            {
                "modelo": model,
                "coord_mode": mode,
                "clics": len(clicks),
                "aciertos": _share(r["acierto"] for r in clicks),
                "aciertos_otra_escala": _share(r["acierto_otra_escala"] for r in clicks),
                "validas": _share(r["valida"] for r in group),
                "distancia_fallos_px": statistics.median(misses) if misses else None,
                "estados": len(states),
                "estados_correctos": _share(r["correcta"] for r in states),
                "latencia_p50_s": _percentile(latencies, 50),
                "latencia_p95_s": _percentile(latencies, 95),
                "llamadas": len(group),
                "costo_usd": cost,
                "costo_por_llamada_usd": cost / len(group),
            }
        )
    return summary


def _share(values: Iterable[bool]) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def _percentile(values: list[float], percent: int) -> float | None:
    """Percentil por rango más cercano de una lista ordenada."""
    if not values:
        return None
    return values[max(math.ceil(percent / 100 * len(values)) - 1, 0)]


def render_tables(rows: list[dict], screens: list[Screen]) -> str:
    summary = summarize(rows)
    if not summary:
        return "Todavía no hay resultados.\n"
    total = sum(s["costo_usd"] for s in summary)
    lines = [
        f"{len(rows)} llamadas en total, US${total:.4f} de gasto.",
        "",
        "| Modelo | Escala | Clics | Aciertos | Aciertos leyendo la otra escala | Tool calls "
        "válidas | Distancia mediana de los fallos | Estados correctos | Latencia p50 / p95 | "
        "Costo | Costo por llamada |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summary:
        lines.append(
            f"| `{s['modelo']}` | `{s['coord_mode']}` | {s['clics']} | {_pct(s['aciertos'])} | "
            f"{_pct(s['aciertos_otra_escala'])} | {_pct(s['validas'])} | "
            f"{_px(s['distancia_fallos_px'])} | {_pct(s['estados_correctos'])} "
            f"({s['estados']}) | {_secs(s['latencia_p50_s'])} / {_secs(s['latencia_p95_s'])} | "
            f"US${s['costo_usd']:.4f} | US${s['costo_por_llamada_usd']:.5f} |"
        )

    configs = [(s["modelo"], s["coord_mode"]) for s in summary]
    lines += [
        "",
        "Aciertos de clic por pantalla:",
        "",
        "| Pantalla | " + " | ".join(f"`{m}` ({c})" for m, c in configs) + " |",
        "|---|" + "---|" * len(configs),
    ]
    for screen in screens:
        cells = []
        for config in configs:
            clicks = [
                r
                for r in rows
                if (r["modelo"], r["coord_mode"]) == config
                and (r["pantalla"], r["tipo"]) == (screen.name, "clic")
            ]
            cells.append(f"{sum(r['acierto'] for r in clicks)}/{len(clicks)}" if clicks else "—")
        lines.append(f"| `{screen.name}` | " + " | ".join(cells) + " |")

    targets = {(s.name, t.id): t for s in screens for t in s.objetivos}
    questions = {(s.name, q.id): q for s in screens for q in s.estados}
    lines += [
        "",
        "Fallos: clics fuera del recuadro, tool calls inválidas y estados incorrectos.",
        "",
        "| Modelo | Pantalla | Objetivo o pregunta | Qué pasó |",
        "|---|---|---|---|",
    ]
    for row in rows:
        failure = _failure(row, targets, questions)
        if failure:
            lines.append(
                f"| `{row['modelo']}` ({row['coord_mode']}) | `{row['pantalla']}` | "
                f"{_cell(failure[0])} | {_cell(failure[1])} |"
            )
    return "\n".join(lines) + "\n"


def _failure(row: dict, targets: dict, questions: dict) -> tuple[str, str] | None:
    key = (row["pantalla"], row["id"])
    if row["tipo"] == "clic":
        if row["acierto"]:
            return None
        target = targets.get(key)
        name = target.descripcion if target else row["id"]
        if not row["valida"]:
            return name, f"inválida: {row.get('error', '')}"
        box = list(target.box) if target else "?"
        return name, f"({row['x']}, {row['y']}) a {row['distancia_px']:.0f} px de {box}"
    if row["correcta"]:
        return None
    question = questions.get(key)
    name = question.pregunta if question else row["id"]
    if not row["valida"]:
        return name, f"inválida: {row.get('error', '')}"
    return name, f"respondió «{row['respuesta']}»; se esperaba «{row['esperada']}»"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"


def _px(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f} px"


def _secs(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f} s"


def write_report(rows: list[dict], screens: list[Screen], path: Path = REPORT) -> None:
    """Reemplaza las tablas entre los marcadores y deja el resto del reporte como está."""
    tables = f"{TABLES_START}\n{render_tables(rows, screens)}{TABLES_END}"
    if path.exists():
        text = path.read_text(encoding="utf-8")
        start, end = text.find(TABLES_START), text.find(TABLES_END)
        if start != -1 and end > start:
            text = text[:start] + tables + text[end + len(TABLES_END) :]
        else:
            text = f"{text.rstrip()}\n\n{tables}\n"
    else:
        text = f"# Comparación de modelos por precisión de clic\n\n{tables}\n"
    path.write_text(text, encoding="utf-8")


# --- Línea de comandos


async def run(args: argparse.Namespace) -> int:
    screens = load_screens()
    selected = screens
    if args.pantalla:
        unknown = set(args.pantalla) - {s.name for s in screens}
        if unknown:
            print(f"pantallas desconocidas: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        selected = [s for s in screens if s.name in args.pantalla]

    if not args.solo_reporte:
        previous = read_results(args.resultados)
        done_keys = {row_key(row) for row in previous}
        jobs = [
            j for j in plan_jobs(selected, args.modelo, args.solo_clics) if j.key not in done_keys
        ]
        known_costs: dict[str, float] = {}
        for row in previous:
            known_costs[row["modelo"]] = max(known_costs.get(row["modelo"], 0.0), row["costo_usd"])
        budget = Budget(args.max_costo, sum(row["costo_usd"] for row in previous))
        print(
            f"{len(jobs)} llamadas por hacer; gasto previo US${budget.spent_usd:.4f} "
            f"de US${args.max_costo:.2f}"
        )
        llm = OpenRouterClient(Settings())
        try:
            done, skipped = await run_jobs(
                jobs, llm, budget, args.resultados, args.paralelo, known_costs
            )
        finally:
            await llm.aclose()
        print(
            f"{done} llamadas hechas, {skipped} omitidas por presupuesto; "
            f"gasto total US${budget.spent_usd:.4f}"
        )

    write_report(read_results(args.resultados), screens, args.reporte)
    print(f"reporte → {args.reporte}")
    return 0


def _model_arg(text: str) -> ModelConfig:
    try:
        return ModelConfig.parse(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eval.grounding",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--modelo",
        action="append",
        default=[],
        type=_model_arg,
        help="modelo=pixels o modelo=norm1000; repetible",
    )
    parser.add_argument("--pantalla", action="append", help="solo esta pantalla; repetible")
    parser.add_argument("--solo-clics", action="store_true", help="sin preguntas de estado")
    parser.add_argument("--max-costo", type=float, default=DEFAULT_MAX_COST_USD)
    parser.add_argument("--paralelo", type=int, default=4, help="llamadas en vuelo a la vez")
    parser.add_argument("--resultados", type=Path, default=RESULTS)
    parser.add_argument("--reporte", type=Path, default=REPORT)
    parser.add_argument("--solo-reporte", action="store_true", help="no llama a los modelos")
    args = parser.parse_args(argv)
    if not args.solo_reporte and not args.modelo:
        parser.error("indica al menos un --modelo, o usa --solo-reporte")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
