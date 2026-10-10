"""Arnés de evaluación (plan T12, diseño 3.1): reproduce al evaluador contra el escritorio propio.

Por cada caso de `eval/cases/` y cada corrida:

1. `POST /__reset` del escritorio (salvo con `--no-reset`).
2. `POST /tasks` al agente, cronometrado: el contrato pide menos de 2 s.
3. `GET /tasks/{id}` cada 5 s hasta el estado final o 300 s.
4. `POST /__check` del escritorio con el JSON del caso.
5. Chequeos locales: estado esperado, línea `respuesta:`, `claves_razon` y ausencia de secretos.

Al final escribe `reporte.csv` y `reporte.md` en `eval/reports/<fecha>/`, junto con las trazas
que entregue `GET /tasks/{id}/traza`. Todo lo que escribe pasa antes por `redact`.

El escritorio y los tokens salen de `EVAL_DESKTOP_URL`, `EVAL_DESKTOP_PASSWORD`,
`EVAL_DESKTOP_TOKEN`, `AGENT_URL` y `AGENT_TOKEN`. La base de `/__reset` y `/__check` es la de
`EVAL_DESKTOP_URL` (`wss://…/websockify` pasa a `https://…`).

Los casos usan el formato de `frontier-reto-1/pruebas/`. Un caso con el campo `pendiente` todavía
tiene datos por completar (marcados con †) y se omite, salvo con `--include-pending`.

Uso:
  uv run python -m eval.harness                   # todos los casos
  uv run python -m eval.harness E3 E5 --runs 3    # algunos casos, tres corridas (P11)
  uv run python -m eval.harness --no-reset        # sin /__reset (escritorio compartido)
"""

import argparse
import asyncio
import csv
import json
import math
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import EvalSettings
from app.models import ErrorCode, TaskStatus

CASES_DIR = Path(__file__).resolve().parent / "cases"
REPORTS_DIR = Path(__file__).resolve().parent / "reports"

POLL_INTERVAL_S = 5.0  # el evaluador consulta cada 5 s
TASK_TIMEOUT_S = 300.0  # y deja de consultar a los 5 min
POST_LIMIT_S = 2.0  # POST /tasks tiene que responder en menos de 2 s

# Chequeos de /__check que alimentan métricas propias.
CHECK_OUT_OF_TASK = "sin acciones fuera de la tarea"
CHECK_DUPLICATES = "sin registros duplicados"

PASS, FAIL, ERROR = "PASA", "FALLA", "ERROR"
FINAL_STATES = {TaskStatus.TERMINADA.value, TaskStatus.FALLIDA.value}

_RESPUESTA_LINE = re.compile(r"^[ \t]*respuesta:(.*)$", re.MULTILINE)
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")
_ERROR_CODES = re.compile(r"\b(?:" + "|".join(code.value for code in ErrorCode) + r")\b")
# Campos de cada paso de la traza (T11) de los que salen los pasos y el costo.
_STEP_KEYS = ("step", "paso")
_COST_KEYS = ("cost_usd", "costo_usd")


class HarnessError(Exception):
    """Falla del arnés o de un servicio, no del agente evaluado."""


@dataclass
class Case:
    """Una prueba en el formato de `frontier-reto-1/pruebas/`."""

    data: dict
    path: Path

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def instruccion(self) -> str:
        return self.data["instruccion"]

    @property
    def expected(self) -> str:
        return self.data["estado_esperado"]

    @property
    def pending(self) -> str | None:
        return self.data.get("pendiente")


@dataclass
class CaseResult:
    case_id: str
    run: int
    expected: str
    task_id: str | None = None
    estado: str | None = None
    resumen: str = ""
    seen_summaries: list[str] = field(default_factory=list)
    post_s: float | None = None
    duration_s: float | None = None
    timed_out: bool = False
    check_pass: bool | None = None
    failed_checks: list[str] = field(default_factory=list)
    respuesta_ok: bool | None = None
    claves_ok: bool | None = None
    leaks: list[str] = field(default_factory=list)
    trace: list[dict] | None = None
    trace_file: str | None = None
    steps: int | None = None
    cost_usd: float | None = None
    error_codes: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def outcome(self) -> str:
        if self.error:
            return ERROR
        return FAIL if self.reasons else PASS

    @property
    def false_success(self) -> bool:
        """`terminada` en una tarea que tenía que fallar o que no quedó bien."""
        return self.estado == TaskStatus.TERMINADA and (
            self.expected == TaskStatus.FALLIDA
            or self.check_pass is False
            or self.respuesta_ok is False
        )


# --- Casos ---


def load_cases(directory: Path = CASES_DIR, ids: list[str] | None = None) -> list[Case]:
    """Casos de `directory` ordenados por archivo; con `ids`, solo esos."""
    cases = [
        Case(json.loads(path.read_text(encoding="utf-8")), path)
        for path in sorted(directory.glob("*.json"))
    ]
    if ids:
        unknown = sorted(set(ids) - {case.id for case in cases})
        if unknown:
            raise ValueError(f"Casos desconocidos: {', '.join(unknown)}")
        cases = [case for case in cases if case.id in ids]
    return cases


def desktop_base_url(ws_url: str) -> str:
    """`wss://host/websockify` pasa a `https://host` (y `ws://` a `http://`)."""
    parts = urlsplit(ws_url)
    scheme = {"wss": "https", "ws": "http"}.get(parts.scheme, parts.scheme)
    path = parts.path.rstrip("/").removesuffix("/websockify")
    return urlunsplit((scheme, parts.netloc, path, "", ""))


# --- Chequeos locales ---


def respuesta_line(resumen: str) -> str | None:
    """Valor de la primera línea `respuesta:` del resumen, o None si no hay."""
    match = _RESPUESTA_LINE.search(resumen)
    return match.group(1).strip() if match else None


def answer_matches(expected: str, line: str) -> bool:
    """Compara como el evaluador: con dos datos, separados por `;` y en orden; en un número,
    el primer número de la línea; en un texto, sin distinguir mayúsculas ni espacios."""
    expected_parts = [part.strip() for part in expected.split(";")]
    if len(expected_parts) == 1:
        return _value_matches(expected_parts[0], line)
    got_parts = [part.strip() for part in line.split(";")]
    return len(got_parts) == len(expected_parts) and all(
        _value_matches(want, got) for want, got in zip(expected_parts, got_parts, strict=True)
    )


def _value_matches(expected: str, got: str) -> bool:
    if _NUMBER.fullmatch(expected):
        found = _NUMBER.search(got)
        return found is not None and Decimal(found.group()) == Decimal(expected)
    return _normalize_text(expected) == _normalize_text(got)


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).rstrip(".").casefold()


def check_respuesta(case: Case, resumen: str) -> bool | None:
    """En una tarea que falla no puede haber línea `respuesta:`; en una pregunta tiene que traer
    el valor esperado. None si el caso no dice nada sobre la respuesta."""
    line = respuesta_line(resumen)
    if case.expected == TaskStatus.FALLIDA:
        return line is None
    expected = case.data.get("respuesta_esperada")
    if expected is None:
        return None
    return line is not None and answer_matches(str(expected), line)


def missing_claves(case: Case, resumen: str) -> list[str]:
    """Valores de `claves_razon` que el resumen no nombra."""
    text = resumen.casefold()
    keys = [str(key) for key in case.data.get("claves_razon", [])]
    return [key for key in keys if key.casefold() not in text]


def find_leaks(text: str, secrets: dict[str, str]) -> list[str]:
    """Nombres (nunca valores) de los secretos que aparecen en `text`."""
    leaks = [name for name, value in secrets.items() if value and value in text]
    if _KEY_PATTERN.search(text):
        leaks.append("llave sk-…")
    return leaks


def redact(text: str, secrets: dict[str, str]) -> str:
    """Reemplaza los secretos y los patrones de llave por asteriscos."""
    for value in sorted(filter(None, secrets.values()), key=len, reverse=True):
        text = text.replace(value, "***")
    return _KEY_PATTERN.sub("sk-***", text)


def trace_metrics(entries: list[dict]) -> tuple[int | None, float | None]:
    """Pasos (el mayor número de paso) y costo de la traza.

    El costo es el `cost_usd` del evento "fin", que escribe el ejecutor (T10) y ya incluye el VLM
    y las verificaciones: sumarlo con los costos por paso lo contaría dos veces. Solo si no hay
    evento "fin" (la traza quedó a medias) se suman los costos por paso.
    """
    steps = [entry[key] for entry in entries for key in _STEP_KEYS if type(entry.get(key)) is int]
    totals = [
        entry["cost_usd"]
        for entry in entries
        if entry.get("evento") == "fin" and type(entry.get("cost_usd")) in (int, float)
    ]
    if totals:
        return (max(steps) if steps else None, round(totals[-1], 6))
    costs = [
        entry[key]
        for entry in entries
        for key in _COST_KEYS
        if type(entry.get(key)) in (int, float)
    ]
    return (max(steps) if steps else None, round(sum(costs), 6) if costs else None)


def error_codes(*texts: str) -> list[str]:
    """Códigos de error que aparecen en los textos, en orden de aparición."""
    found: list[str] = []
    for text in texts:
        for code in _ERROR_CODES.findall(text):
            if code not in found:
                found.append(code)
    return found


def evaluate(case: Case, result: CaseResult, secrets: dict[str, str]) -> None:
    """Corre los chequeos locales y deja en `result.reasons` todo lo que no cumple."""
    reasons = result.reasons
    if result.error:
        reasons.append(f"error: {result.error}")
    if result.post_s is not None and result.post_s >= POST_LIMIT_S:
        reasons.append(f"POST /tasks tardó {result.post_s:.2f} s")
    if result.timed_out:
        reasons.append("sin estado final dentro del tiempo")
    if result.estado != case.expected:
        reasons.append(f"estado: se esperaba {case.expected} y llegó {result.estado or '—'}")
    if result.check_pass is False:
        reasons.append("__check: " + ", ".join(result.failed_checks or ["no pasa"]))

    if result.estado in FINAL_STATES:
        result.respuesta_ok = check_respuesta(case, result.resumen)
        if result.respuesta_ok is False:
            line = respuesta_line(result.resumen)
            if case.expected == TaskStatus.FALLIDA:
                reasons.append("respuesta: hay línea respuesta: en una tarea que falla")
            else:
                got = f"«{line}»" if line is not None else "ninguna línea respuesta:"
                reasons.append(
                    f"respuesta: se esperaba «{case.data['respuesta_esperada']}» y llegó {got}"
                )
        if case.data.get("claves_razon"):
            missing = missing_claves(case, result.resumen)
            result.claves_ok = not missing
            if missing:
                reasons.append("claves_razon: falta " + ", ".join(missing))

    # Se revisan todos los resúmenes vistos, no solo el final: el progreso también se publica.
    leaks: list[str] = []
    for summary in result.seen_summaries:
        leaks += [f"resumen: {name}" for name in find_leaks(summary, secrets)]
    trace_text = json.dumps(result.trace, ensure_ascii=False) if result.trace else ""
    leaks += [f"traza: {name}" for name in find_leaks(trace_text, secrets)]
    result.leaks = list(dict.fromkeys(leaks))
    if result.leaks:
        reasons.append("fuga de secretos: " + ", ".join(result.leaks))

    result.error_codes = error_codes(trace_text, result.resumen)


# --- Ejecución ---


class Harness:
    """Corre un caso contra el agente y el escritorio.

    `agent` y `desktop` son clientes httpx con su `base_url` y su header Authorization.
    """

    def __init__(
        self,
        agent: httpx.AsyncClient,
        desktop: httpx.AsyncClient,
        escritorio: dict[str, str],
        secrets: dict[str, str],
        *,
        reset: bool = True,
        poll_interval_s: float = POLL_INTERVAL_S,
        task_timeout_s: float = TASK_TIMEOUT_S,
    ) -> None:
        self.agent = agent
        self.desktop = desktop
        self.escritorio = escritorio
        self.secrets = secrets
        self.reset = reset
        self.poll_interval_s = poll_interval_s
        self.task_timeout_s = task_timeout_s

    async def run_case(self, case: Case, run: int, trace_dir: Path) -> CaseResult:
        result = CaseResult(case.id, run, case.expected)
        try:
            if self.reset:
                await self._reset()
            started = await self._submit(case, result)
            await self._wait_final(result, started)
        except HarnessError as error:
            result.error = str(error)
        if result.task_id is not None:
            try:
                await self._check(case, result)
            except HarnessError as error:
                result.error = result.error or str(error)
            await self._fetch_trace(result, trace_dir)
        evaluate(case, result, self.secrets)
        return result

    async def _reset(self) -> None:
        response = await self._request(self.desktop, "POST", "/__reset")
        if response.status_code != 200:
            raise HarnessError(f"POST /__reset: HTTP {response.status_code}")

    async def _submit(self, case: Case, result: CaseResult) -> float:
        body = {"tarea": case.instruccion, "escritorio": self.escritorio}
        started = time.perf_counter()
        response = await self._request(self.agent, "POST", "/tasks", json=body)
        result.post_s = time.perf_counter() - started
        if response.status_code != 200:
            raise HarnessError(f"POST /tasks: HTTP {response.status_code}")
        task_id = _json(response, "POST /tasks").get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise HarnessError("POST /tasks: la respuesta no trae task_id")
        result.task_id = task_id
        return started

    async def _wait_final(self, result: CaseResult, started: float) -> None:
        deadline = started + self.task_timeout_s
        while True:
            await asyncio.sleep(max(0.0, min(self.poll_interval_s, deadline - time.perf_counter())))
            try:
                response = await self._request(self.agent, "GET", f"/tasks/{result.task_id}")
            except HarnessError:
                response = None  # una consulta fallida no termina la tarea: se reintenta
            if response is not None and response.status_code == 404:
                raise HarnessError("GET /tasks: 404, el agente no conoce la tarea")
            if response is not None and response.status_code == 200:
                body = _json(response, "GET /tasks")
                estado, resumen = body.get("estado"), body.get("resumen")
                if not isinstance(estado, str) or not isinstance(resumen, str):
                    raise HarnessError("GET /tasks: la respuesta no trae estado y resumen")
                result.estado, result.resumen = estado, resumen
                if resumen not in result.seen_summaries:
                    result.seen_summaries.append(resumen)
                if estado in FINAL_STATES:
                    result.duration_s = time.perf_counter() - started
                    return
                if estado != TaskStatus.EN_CURSO:
                    raise HarnessError(f"GET /tasks: estado desconocido «{estado}»")
            if time.perf_counter() >= deadline:
                result.timed_out = True
                result.duration_s = time.perf_counter() - started
                return

    async def _check(self, case: Case, result: CaseResult) -> None:
        response = await self._request(self.desktop, "POST", "/__check", json=case.data)
        if response.status_code != 200:
            raise HarnessError(f"POST /__check: HTTP {response.status_code}")
        body = _json(response, "POST /__check")
        result.check_pass = body.get("pass") is True
        result.failed_checks = [
            str(check.get("nombre", "?")) for check in body.get("checks", []) if not check.get("ok")
        ]

    async def _fetch_trace(self, result: CaseResult, trace_dir: Path) -> None:
        """La traza es para depurar: si el agente no la entrega, el caso sigue sin ella."""
        try:
            response = await self._request(self.agent, "GET", f"/tasks/{result.task_id}/traza")
            entries = _json(response, "GET /traza") if response.status_code == 200 else None
        except HarnessError:
            return
        if isinstance(entries, dict):  # por si llega envuelta, como {"pasos": [...]}
            entries = next((value for value in entries.values() if isinstance(value, list)), None)
        if not isinstance(entries, list):
            return
        result.trace = [entry for entry in entries if isinstance(entry, dict)]
        result.steps, result.cost_usd = trace_metrics(result.trace)
        path = trace_dir / f"{result.case_id}-r{result.run}.json"
        text = json.dumps(result.trace, ensure_ascii=False, indent=2)
        path.write_text(redact(text, self.secrets), encoding="utf-8")
        result.trace_file = f"{trace_dir.name}/{path.name}"

    @staticmethod
    async def _request(
        client: httpx.AsyncClient, method: str, path: str, **kwargs
    ) -> httpx.Response:
        try:
            return await client.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            # Solo el tipo: el mensaje podría traer la URL o el cuerpo de la petición.
            raise HarnessError(f"{method} {path}: {type(error).__name__}") from None


def _json(response: httpx.Response, where: str):
    try:
        return response.json()
    except ValueError:
        raise HarnessError(f"{where}: la respuesta no es JSON") from None


async def run_cases(
    harness: Harness, cases: list[Case], runs: int, out_dir: Path
) -> list[CaseResult]:
    """Corre cada caso `runs` veces, una corrida completa tras otra."""
    trace_dir = out_dir / "trazas"
    trace_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for run in range(1, runs + 1):
        for case in cases:
            result = await harness.run_case(case, run, trace_dir)
            results.append(result)
            line = f"{case.id} · corrida {run}: {result.outcome} ({_seconds(result.duration_s)})"
            for reason in result.reasons:
                line += f"\n    - {reason}"
            print(redact(line, harness.secrets), flush=True)
    return results


# --- Reporte ---

CSV_COLUMNS = [
    "caso",
    "corrida",
    "resultado",
    "estado_esperado",
    "estado",
    "check",
    "checks_fallidos",
    "respuesta_ok",
    "claves_ok",
    "fugas",
    "post_ms",
    "duracion_s",
    "pasos",
    "costo_usd",
    "codigos_error",
    "task_id",
    "traza",
    "motivos",
    "resumen",
]


def percentile(values: list[float], pct: float) -> float | None:
    """Percentil por rango más cercano; None si no hay valores."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def metrics(results: list[CaseResult]) -> list[tuple[str, str, str]]:
    """Métricas de la sección 3.3 del diseño que se pueden medir desde el arnés."""
    total = len(results)
    passed = sum(result.outcome == PASS for result in results)
    answered = [result.respuesta_ok for result in results if result.respuesta_ok is not None]
    posts = [result.post_s * 1000 for result in results if result.post_s is not None]
    durations = [
        result.duration_s
        for result in results
        if result.duration_s is not None and not result.timed_out
    ]
    steps = [result.steps for result in results if result.steps is not None]
    costs = [result.cost_usd for result in results if result.cost_usd is not None]
    mean_cost = sum(costs) / len(costs) if costs else None
    p99_post, max_post = percentile(posts, 99), max(posts, default=None)
    rows = [
        ("Éxito de punta a punta", _ratio(passed, total), "≥ 80 %"),
        ("Falsos éxitos", str(sum(result.false_success for result in results)), "0"),
        ("Acciones fuera de la tarea", _failed_check_count(results, CHECK_OUT_OF_TASK), "0"),
        ("Registros duplicados", _failed_check_count(results, CHECK_DUPLICATES), "0"),
        ("Formato de respuesta", _ratio(sum(answered), len(answered)), "100 %"),
        ("Fugas de secretos", str(sum(bool(result.leaks) for result in results)), "0"),
        (
            "Latencia de POST /tasks (p99 / máx.)",
            f"{_number(p99_post, '.0f')} ms / {_number(max_post, '.0f')} ms",
            "< 200 ms (límite: 2 s)",
        ),
        ("Duración por tarea (p95)", _seconds(percentile(durations, 95)), "< 240 s"),
        ("Pasos por tarea (p95)", _number(percentile(steps, 95), "d"), "< 30"),
        (
            "Costo por tarea (promedio / máx.)",
            f"{_usd(mean_cost)} / {_usd(max(costs, default=None))}",
            "≤ US$0.05 (tope: US$0.15)",
        ),
    ]
    runs_by_case: dict[str, list[str]] = {}
    for result in results:
        runs_by_case.setdefault(result.case_id, []).append(result.outcome)
    if any(len(outcomes) > 1 for outcomes in runs_by_case.values()):
        stable = sum(len(set(outcomes)) == 1 for outcomes in runs_by_case.values())
        rows.append(("Estabilidad entre corridas", _ratio(stable, len(runs_by_case)), "≥ 90 %"))
    return rows


def write_reports(
    results: list[CaseResult],
    skipped: list[Case],
    out_dir: Path,
    header: dict[str, str],
    secrets: dict[str, str],
) -> tuple[Path, Path]:
    """Escribe `reporte.csv` y `reporte.md` en `out_dir`, sin secretos."""
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path, md_path = out_dir / "reporte.csv", out_dir / "reporte.md"
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(CSV_COLUMNS)
        for result in results:
            writer.writerow([redact(cell, secrets) for cell in _csv_row(result)])
    md_path.write_text(redact(_markdown(results, skipped, header), secrets), encoding="utf-8")
    return csv_path, md_path


def _csv_row(result: CaseResult) -> list[str]:
    return [
        result.case_id,
        str(result.run),
        result.outcome,
        result.expected,
        result.estado or "",
        _yes_no(result.check_pass, empty=""),
        "; ".join(result.failed_checks),
        _yes_no(result.respuesta_ok, empty=""),
        _yes_no(result.claves_ok, empty=""),
        "; ".join(result.leaks),
        _number(result.post_s * 1000 if result.post_s is not None else None, ".0f", empty=""),
        _number(result.duration_s, ".1f", empty=""),
        _number(result.steps, "d", empty=""),
        _number(result.cost_usd, ".4f", empty=""),
        " ".join(result.error_codes),
        result.task_id or "",
        result.trace_file or "",
        "; ".join(result.reasons),
        result.resumen,
    ]


def _markdown(results: list[CaseResult], skipped: list[Case], header: dict[str, str]) -> str:
    lines = [f"# Reporte del arnés · {header.get('fecha', '')}", ""]
    lines += [
        f"- **{key.capitalize()}:** {value}" for key, value in header.items() if key != "fecha"
    ]
    if skipped:
        names = ", ".join(f"{case.id} ({case.pending})" for case in skipped)
        lines.append(f"- **Omitidos por datos pendientes:** {names}")
    lines += ["", "## Métricas", "", "| Métrica | Valor | Objetivo |", "|---|---|---|"]
    lines += [f"| {name} | {value} | {goal} |" for name, value, goal in metrics(results)]
    lines += [
        "",
        "## Resultados",
        "",
        "| Caso | Corrida | Resultado | Estado esperado → obtenido | `__check` | `respuesta:` "
        "| Claves | Fugas | POST | Duración | Pasos | Costo | Errores | Traza |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        trace = f"[traza]({result.trace_file})" if result.trace_file else "—"
        post = result.post_s * 1000 if result.post_s is not None else None
        lines.append(
            f"| {result.case_id} | {result.run} | **{result.outcome}** "
            f"| {result.expected} → {result.estado or '—'} | {_yes_no(result.check_pass)} "
            f"| {_yes_no(result.respuesta_ok)} | {_yes_no(result.claves_ok)} "
            f"| {len(result.leaks)} | {_number(post, '.0f')} ms | {_seconds(result.duration_s)} "
            f"| {_number(result.steps, 'd')} | {_usd(result.cost_usd)} "
            f"| {' '.join(result.error_codes) or '—'} | {trace} |"
        )
    failures = [result for result in results if result.outcome != PASS]
    if failures:
        lines += ["", "## Detalle de lo que no pasó"]
        for result in failures:
            lines += ["", f"### {result.case_id} · corrida {result.run} · {result.outcome}", ""]
            lines += [f"- {reason}" for reason in result.reasons]
            lines += ["", "Resumen del agente:", "", _quote(result.resumen or "(vacío)")]
    return "\n".join(lines) + "\n"


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def _failed_check_count(results: list[CaseResult], name: str) -> str:
    return str(sum(name in result.failed_checks for result in results))


def _ratio(part: int, total: int) -> str:
    return f"{part}/{total} ({part / total:.0%})" if total else "sin datos"


def _yes_no(value: bool | None, empty: str = "—") -> str:
    if value is None:
        return empty
    return "sí" if value else "no"


def _number(value: float | None, spec: str, empty: str = "—") -> str:
    return empty if value is None else format(value, spec)


def _seconds(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f} s"


def _usd(value: float | None) -> str:
    return "—" if value is None else f"US${value:.4f}"


# --- Línea de comandos ---


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("tiene que ser 1 o más")
    return value


async def _main(args: argparse.Namespace, settings: EvalSettings, cases: list[Case]) -> int:
    secrets = {
        "contraseña del escritorio": settings.eval_desktop_password.get_secret_value(),
        "token del escritorio": settings.eval_desktop_token.get_secret_value(),
        "token del agente": settings.agent_token.get_secret_value(),
    }
    escritorio = {
        "url": settings.eval_desktop_url,
        "password": settings.eval_desktop_password.get_secret_value(),
    }
    skipped = [case for case in cases if case.pending and not args.include_pending]
    runnable = [case for case in cases if case not in skipped]
    started = datetime.now()
    out_dir = args.out / started.strftime("%Y%m%d-%H%M%S")
    agent = httpx.AsyncClient(
        base_url=settings.agent_url,
        headers={"Authorization": f"Bearer {secrets['token del agente']}"},
        timeout=10,
    )
    desktop = httpx.AsyncClient(
        base_url=desktop_base_url(settings.eval_desktop_url),
        headers={"Authorization": f"Bearer {secrets['token del escritorio']}"},
        timeout=60,  # el reset reinicia el navegador
    )
    async with agent, desktop:
        harness = Harness(
            agent,
            desktop,
            escritorio,
            secrets,
            reset=not args.no_reset,
            poll_interval_s=args.poll,
            task_timeout_s=args.timeout,
        )
        results = await run_cases(harness, runnable, args.runs, out_dir)
    header = {
        "fecha": started.strftime("%Y-%m-%d %H:%M"),
        "agente": settings.agent_url,
        "reset del escritorio": "no" if args.no_reset else "sí",
        "casos": f"{len(runnable)} · corridas: {args.runs}",
    }
    csv_path, md_path = write_reports(results, skipped, out_dir, header, secrets)
    print(f"\nReporte: {md_path}\n         {csv_path}")
    for name, value, goal in metrics(results):
        print(f"  {name}: {value} (objetivo {goal})")
    return 0 if all(result.outcome == PASS for result in results) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eval.harness",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("ids", nargs="*", help="ids de los casos a correr (por defecto, todos)")
    parser.add_argument("--runs", type=_positive_int, default=1, help="corridas por caso")
    parser.add_argument("--no-reset", action="store_true", help="no llama a /__reset")
    parser.add_argument(
        "--include-pending", action="store_true", help="corre también los casos con `pendiente`"
    )
    parser.add_argument("--cases-dir", type=Path, default=CASES_DIR)
    parser.add_argument("--out", type=Path, default=REPORTS_DIR, help="carpeta de reportes")
    parser.add_argument("--poll", type=float, default=POLL_INTERVAL_S, help="s entre consultas")
    parser.add_argument("--timeout", type=float, default=TASK_TIMEOUT_S, help="s por tarea")
    args = parser.parse_args(argv)
    try:
        cases = load_cases(args.cases_dir, args.ids)
    except ValueError as error:
        parser.error(str(error))
    return asyncio.run(_main(args, EvalSettings(), cases))


if __name__ == "__main__":
    sys.exit(main())
