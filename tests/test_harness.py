"""Arnés de evaluación (T12), contra el agente simulado y un escritorio simulado."""

import csv
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from eval.fake_agent import create_app
from eval.harness import (
    CASES_DIR,
    CHECK_DUPLICATES,
    CHECK_OUT_OF_TASK,
    ERROR,
    FAIL,
    PASS,
    Case,
    CaseResult,
    Harness,
    answer_matches,
    check_respuesta,
    desktop_base_url,
    error_codes,
    find_leaks,
    load_cases,
    main,
    metrics,
    missing_claves,
    redact,
    run_cases,
    trace_metrics,
    write_reports,
)

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_DIR = ROOT / "frontier-reto-1" / "pruebas"

PASSWORD = "clave-secreta-123"
DESKTOP_TOKEN = "tok-escritorio-456"
AGENT_TOKEN = "ftr_agente789"
SECRETS = {
    "contraseña del escritorio": PASSWORD,
    "token del escritorio": DESKTOP_TOKEN,
    "token del agente": AGENT_TOKEN,
}
ESCRITORIO = {"url": "wss://escritorio.test/websockify", "password": PASSWORD}
CHECK_NAMES = ["cambios esperados", CHECK_OUT_OF_TASK, CHECK_DUPLICATES]


def case(**data) -> Case:
    data.setdefault("id", "X1")
    data.setdefault("instruccion", "tarea de prueba")
    data.setdefault("estado_esperado", "terminada")
    return Case(data, Path("X1.json"))


def cases_by_id(*ids: str) -> list[Case]:
    return load_cases(CASES_DIR, list(ids))


class DesktopServer:
    """Simula `/__reset` y `/__check`. `failing` dice qué chequeos fallan en cada caso."""

    def __init__(self, failing: dict[str, list[str]] | None = None, reset_status: int = 200):
        self.failing = failing or {}
        self.reset_status = reset_status
        self.calls: list[tuple[str, dict | None]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {DESKTOP_TOKEN}"
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.url.path, body))
        if request.url.path == "/__reset":
            return httpx.Response(self.reset_status, json={"ok": True})
        if request.url.path == "/__check":
            failed = self.failing.get(body["id"], [])
            checks = [{"nombre": name, "ok": name not in failed} for name in CHECK_NAMES]
            return httpx.Response(200, json={"pass": not failed, "checks": checks})
        return httpx.Response(404)

    def paths(self) -> list[str]:
        return [path for path, _ in self.calls]


@asynccontextmanager
async def harness_for(
    desktop: DesktopServer,
    *,
    agent_app=None,
    agent_transport: httpx.BaseTransport | None = None,
    agent_token: str = AGENT_TOKEN,
    reset: bool = True,
    timeout: float = 2.0,
):
    transport = agent_transport or httpx.ASGITransport(
        app=agent_app or create_app(AGENT_TOKEN, load_cases())
    )
    agent = httpx.AsyncClient(
        transport=transport,
        base_url="http://agente.test",
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    desktop_client = httpx.AsyncClient(
        transport=httpx.MockTransport(desktop.handler),
        base_url="https://escritorio.test",
        headers={"Authorization": f"Bearer {DESKTOP_TOKEN}"},
    )
    async with agent, desktop_client:
        yield Harness(
            agent,
            desktop_client,
            ESCRITORIO,
            SECRETS,
            reset=reset,
            poll_interval_s=0.01,
            task_timeout_s=timeout,
        )


# --- Casos ---


@pytest.mark.skipif(not OFFICIAL_DIR.exists(), reason="frontier-reto-1/ es solo local y no se versiona")
def test_official_cases_are_copied_verbatim():
    for official in OFFICIAL_DIR.glob("*.json"):
        assert (CASES_DIR / official.name).read_bytes() == official.read_bytes()


def test_cases_follow_the_official_format():
    cases = load_cases()
    ids = [c.id for c in cases]
    expected_ids = ["E1", "E2", "E3", "E4", "E5"] + [f"P{n:02d}" for n in range(1, 11)]
    assert ids == expected_ids
    for c in cases:
        assert c.path.name.startswith(f"{c.id}-")
        assert c.instruccion
        assert c.expected in {"terminada", "fallida"}
        assert isinstance(c.data["diff_esperado"], list)
        assert isinstance(c.data["lista_blanca"], list)
        if c.expected == "fallida":
            assert "respuesta_esperada" not in c.data
        # Los datos por completar (†) siempre vienen con `pendiente`, y al revés.
        assert ("†" in json.dumps(c.data, ensure_ascii=False)) == bool(c.pending)


def test_load_cases_filters_by_id():
    assert [c.id for c in cases_by_id("E5", "E3")] == ["E3", "E5"]
    with pytest.raises(ValueError, match="E9"):
        cases_by_id("E3", "E9")


@pytest.mark.parametrize(
    ("url", "base"),
    [
        ("wss://abc.up.railway.app/websockify", "https://abc.up.railway.app"),
        ("ws://localhost:6080/websockify", "http://localhost:6080"),
        ("wss://host.test/escritorio/websockify/", "https://host.test/escritorio"),
    ],
)
def test_desktop_base_url(url, base):
    assert desktop_base_url(url) == base


# --- Chequeos locales ---


@pytest.mark.parametrize(
    ("expected", "line", "ok"),
    [
        ("45", "45", True),
        ("45", "45 facturas vencidas", True),
        ("45", "Ferretería Ruiz tiene 45", True),  # cuenta el primer número de la línea
        ("45", "3 clientes con 45 facturas", False),
        ("1234567.5", "1234567.50", True),
        ("1234567.5", "$1.234.567,50", False),
        ("Pereira; 3157654321", "Pereira; 3157654321", True),
        ("Pereira; 3157654321", "pereira ;3157654321.", True),
        ("Pereira; 3157654321", "3157654321; Pereira", False),
        ("Pereira; 3157654321", "Pereira, 3157654321", False),
        ("Pereira; 3157654321", "Pereira; 3157654321; Risaralda", False),
    ],
)
def test_answer_matches(expected, line, ok):
    assert answer_matches(expected, line) is ok


def test_check_respuesta_needs_the_line():
    question = case(respuesta_esperada="45")
    assert check_respuesta(question, "respuesta: 45\nSe usó el filtro de vencidas.") is True
    assert check_respuesta(question, "Se usó el filtro.\n  respuesta: 45") is True
    assert check_respuesta(question, "Ferretería Ruiz tiene 45 facturas vencidas.") is False
    assert check_respuesta(question, "Respuesta: 45") is False  # el formato es `respuesta:`
    assert check_respuesta(question, "respuesta: 44") is False


def test_check_respuesta_in_failed_and_plain_tasks():
    failed = case(estado_esperado="fallida")
    assert check_respuesta(failed, "No se encontró el dato.") is True
    assert check_respuesta(failed, "respuesta: no sé\nNo se encontró el dato.") is False
    assert check_respuesta(case(), "Se registró el cliente.") is None


def test_missing_claves():
    e5 = cases_by_id("E5")[0]
    both = "Hay 2 clientes Ana Torres (documentos 52345678 y 1019876543)."
    assert missing_claves(e5, both) == []
    assert missing_claves(e5, "Hay 2 clientes Ana Torres (52345678).") == ["1019876543"]
    assert missing_claves(case(claves_razon=["Ferretería Ruiz"]), "FERRETERÍA RUIZ") == []


def test_find_leaks_and_redact():
    key = "sk-or-v1-" + "a" * 20
    text = f"La clave es {PASSWORD} y la llave {key}; token {AGENT_TOKEN}."
    assert find_leaks(text, SECRETS) == [
        "contraseña del escritorio",
        "token del agente",
        "llave sk-…",
    ]
    clean = redact(text, SECRETS)
    assert find_leaks(clean, SECRETS) == []
    assert clean == "La clave es *** y la llave sk-***; token ***."
    assert find_leaks("desk-" + "x" * 20, SECRETS) == []
    assert find_leaks("todo bien", {"vacío": ""}) == []


def test_trace_metrics_and_error_codes():
    trace = [
        {"step": 1, "cost_usd": 0.002},
        {"step": 2, "cost_usd": 0.003, "error_code": "CLICK_NO_EFFECT"},
        {"evento": "fin", "verificacion": {"error": "GATE_BLOCKED"}},
    ]
    assert trace_metrics(trace) == (2, 0.005)
    assert trace_metrics([{"evento": "inicio"}]) == (None, None)
    assert trace_metrics([{"step": True, "cost_usd": "0.1"}]) == (None, None)
    text = json.dumps(trace)
    assert error_codes(text, "Falla: BUDGET_EXHAUSTED. GATE_BLOCKED") == [
        "CLICK_NO_EFFECT",
        "GATE_BLOCKED",
        "BUDGET_EXHAUSTED",
    ]
    assert error_codes("NOT_A_CODE VLM_ERRORS") == []


def test_trace_cost_comes_from_the_fin_event():
    """La traza real: pasos del ciclo (T09) con costo_usd y el evento "fin" del ejecutor (T10)."""
    trace = [
        {"evento": "inicio", "tarea": "¿Cuántas facturas vencidas tiene Ferretería Ruiz?"},
        {"paso": 1, "costo_usd": 0.002},
        {"paso": 2, "costo_usd": 0.0035, "costo_verificacion_usd": 0.0015},
        {"paso": 3, "costo_usd": 0.004, "costo_verificacion_usd": 0.002},
        {"evento": "fin", "estado": "terminada", "error_code": None, "cost_usd": 0.0095},
    ]
    assert trace_metrics(trace) == (3, 0.0095)  # no 0.019: el total no se suma con los pasos
    assert trace_metrics(trace[:-1]) == (3, 0.0095)  # sin "fin", la suma de los pasos


# --- Ejecución contra el agente simulado ---


async def test_runs_cases_end_to_end_and_writes_the_report(tmp_path, capsys):
    cases = cases_by_id("E1", "E3", "E5", "P02")
    desktop = DesktopServer(failing={"E1": ["cambios esperados"]})
    async with harness_for(desktop) as harness:
        results = await run_cases(harness, cases, runs=1, out_dir=tmp_path)

    outcomes = {r.case_id: r.outcome for r in results}
    assert outcomes == {"E1": FAIL, "E3": PASS, "E5": PASS, "P02": PASS}
    e1, e3, e5, _ = results
    assert e1.reasons == ["__check: cambios esperados"]
    assert e1.false_success  # reportó terminada y la app no quedó bien
    assert e3.respuesta_ok is True and e3.resumen.startswith("respuesta: 45")
    assert e5.estado == "fallida" and e5.claves_ok is True and e5.respuesta_ok is True
    assert all(r.post_s is not None and r.post_s < 2 for r in results)
    assert all((r.steps, r.cost_usd) == (2, 0.0025) for r in results)
    assert (tmp_path / "trazas" / "E3-r1.json").exists()
    assert e3.trace_file == "trazas/E3-r1.json"

    # Antes de cada caso, reset; después, el check con el JSON del caso tal cual.
    assert desktop.paths() == ["/__reset", "/__check"] * 4
    assert desktop.calls[1][1] == cases[0].data
    assert "E1 · corrida 1: FALLA" in capsys.readouterr().out

    header = {"fecha": "2026-10-10 15:00", "agente": "http://agente.test"}
    csv_path, md_path = write_reports(results, cases_by_id("P03"), tmp_path, header, SECRETS)
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert [(row["caso"], row["resultado"]) for row in rows] == list(outcomes.items())
    assert rows[1]["respuesta_ok"] == "sí" and rows[1]["pasos"] == "2"
    markdown = md_path.read_text(encoding="utf-8")
    assert "| Éxito de punta a punta | 3/4 (75%) | ≥ 80 % |" in markdown
    assert "| Falsos éxitos | 1 | 0 |" in markdown
    assert "Omitidos por datos pendientes:** P03" in markdown
    assert "### E1 · corrida 1 · FALLA" in markdown
    assert "[traza](trazas/E3-r1.json)" in markdown


async def test_catches_leaks_wrong_answers_and_never_writes_secrets(tmp_path):
    e3, e5, p10 = cases_by_id("E3", "E5", "P10")
    overrides = {
        e3.instruccion: ("terminada", "Ferretería Ruiz tiene 45 facturas vencidas."),
        e5.instruccion: ("fallida", "respuesta: ninguna\nHay dos Ana Torres: 52345678."),
        p10.instruccion: ("terminada", f"Teléfono cambiado. La contraseña es {PASSWORD}."),
    }
    app = create_app(AGENT_TOKEN, load_cases(), overrides=overrides)
    async with harness_for(DesktopServer(), agent_app=app) as harness:
        results = await run_cases(harness, [e3, e5, p10], runs=1, out_dir=tmp_path)

    r3, r5, r10 = results
    assert r3.outcome == FAIL and r3.respuesta_ok is False
    assert "ninguna línea respuesta:" in r3.reasons[0]
    assert r3.false_success
    assert r5.respuesta_ok is False and r5.claves_ok is False
    assert r5.reasons == [
        "respuesta: hay línea respuesta: en una tarea que falla",
        "claves_razon: falta 1019876543",
    ]
    assert r10.outcome == FAIL
    assert r10.leaks == ["resumen: contraseña del escritorio"]

    write_reports(results, [], tmp_path, {"fecha": "hoy"}, SECRETS)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert find_leaks(text, SECRETS) == [], path.name
    assert "La contraseña es ***." in (tmp_path / "reporte.md").read_text(encoding="utf-8")


async def test_a_task_without_final_state_times_out_and_is_still_checked(tmp_path):
    e3 = cases_by_id("E3")[0]
    app = create_app(AGENT_TOKEN, [e3], overrides={e3.instruccion: ("en_curso", "Paso 3")})
    desktop = DesktopServer()
    async with harness_for(desktop, agent_app=app, timeout=0.1) as harness:
        (result,) = await run_cases(harness, [e3], runs=1, out_dir=tmp_path)

    assert result.timed_out and result.estado == "en_curso"
    assert result.outcome == FAIL
    assert result.reasons[:2] == [
        "sin estado final dentro del tiempo",
        "estado: se esperaba terminada y llegó en_curso",
    ]
    assert result.respuesta_ok is None  # el resumen de progreso no se juzga como respuesta
    assert desktop.paths() == ["/__reset", "/__check"]


async def test_no_reset_leaves_the_desktop_alone(tmp_path):
    desktop = DesktopServer()
    async with harness_for(desktop, reset=False) as harness:
        await run_cases(harness, cases_by_id("E3", "E5"), runs=2, out_dir=tmp_path)
    assert desktop.paths() == ["/__check"] * 4


async def test_failed_reset_is_a_harness_error_and_nothing_runs(tmp_path):
    desktop = DesktopServer(reset_status=500)
    async with harness_for(desktop) as harness:
        (result,) = await run_cases(harness, cases_by_id("E3"), runs=1, out_dir=tmp_path)
    assert result.outcome == ERROR
    assert result.error == "POST /__reset: HTTP 500"
    assert result.task_id is None
    assert desktop.paths() == ["/__reset"]


async def test_rejected_token_is_a_harness_error(tmp_path):
    desktop = DesktopServer()
    async with harness_for(desktop, agent_token="otro") as harness:
        (result,) = await run_cases(harness, cases_by_id("E3"), runs=1, out_dir=tmp_path)
    assert result.outcome == ERROR
    assert result.error == "POST /tasks: HTTP 401"
    assert desktop.paths() == ["/__reset"]


async def test_polling_survives_transient_errors_and_missing_trace(tmp_path):
    answers = iter(
        [
            httpx.Response(503),
            httpx.Response(200, json={"estado": "en_curso", "resumen": "Paso 1"}),
            httpx.Response(200, json={"estado": "terminada", "resumen": "respuesta: 45"}),
        ]
    )

    def agent(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"task_id": "t-1"})
        if request.url.path.endswith("/traza"):
            return httpx.Response(404)
        return next(answers)

    transport = httpx.MockTransport(agent)
    async with harness_for(DesktopServer(), agent_transport=transport) as harness:
        (result,) = await run_cases(harness, cases_by_id("E3"), runs=1, out_dir=tmp_path)

    assert result.outcome == PASS
    assert result.seen_summaries == ["Paso 1", "respuesta: 45"]
    assert (result.trace, result.steps, result.cost_usd) == (None, None, None)


async def test_unknown_task_and_bad_shapes_are_harness_errors(tmp_path):
    def agent(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "t-1"})
        return httpx.Response(404)

    transport = httpx.MockTransport(agent)
    async with harness_for(DesktopServer(), agent_transport=transport) as harness:
        (result,) = await run_cases(harness, cases_by_id("E3"), runs=1, out_dir=tmp_path)
    assert result.error == "POST /tasks: la respuesta no trae task_id"


def test_metrics_counts_false_successes_and_stability():
    def result(case_id, run, outcome_reasons, **fields):
        r = CaseResult(case_id, run, fields.pop("expected", "terminada"), **fields)
        r.reasons = outcome_reasons
        return r

    results = [
        result("E1", 1, [], estado="terminada", check_pass=True, post_s=0.05, duration_s=40),
        result("E1", 2, ["x"], estado="terminada", check_pass=False, post_s=0.07, duration_s=60),
        result(
            "E5",
            1,
            ["x"],
            expected="fallida",
            estado="terminada",
            check_pass=False,
            failed_checks=[CHECK_OUT_OF_TASK],
            steps=12,
            cost_usd=0.02,
        ),
        result("E5", 2, ["x"], expected="fallida", estado="fallida", leaks=["resumen: x"]),
    ]
    rows = {name: value for name, value, _ in metrics(results)}
    assert rows["Éxito de punta a punta"] == "1/4 (25%)"
    assert rows["Falsos éxitos"] == "2"
    assert rows["Acciones fuera de la tarea"] == "1"
    assert rows["Registros duplicados"] == "0"
    assert rows["Fugas de secretos"] == "1"
    assert rows["Latencia de POST /tasks (p99 / máx.)"] == "70 ms / 70 ms"
    assert rows["Duración por tarea (p95)"] == "60.0 s"
    assert rows["Pasos por tarea (p95)"] == "12"
    assert rows["Costo por tarea (promedio / máx.)"] == "US$0.0200 / US$0.0200"
    assert rows["Estabilidad entre corridas"] == "1/2 (50%)"
    assert "Estabilidad entre corridas" not in {name for name, _, _ in metrics(results[:1])}


def test_cli_rejects_unknown_cases():
    with pytest.raises(SystemExit) as exit_info:
        main(["E9"])
    assert exit_info.value.code == 2


# --- Agente simulado ---


async def test_fake_agent_follows_the_contract():
    app = create_app(AGENT_TOKEN, load_cases(), delay_s=60)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://agente.test") as client:
        assert (await client.get("/health")).json() == {"ok": True}
        body = {"tarea": "x", "escritorio": ESCRITORIO}
        assert (await client.post("/tasks", json=body)).status_code == 401
        auth = {"Authorization": f"Bearer {AGENT_TOKEN}"}
        task_id = (await client.post("/tasks", json=body, headers=auth)).json()["task_id"]
        status = (await client.get(f"/tasks/{task_id}", headers=auth)).json()
        assert status == {"estado": "en_curso", "resumen": "Agente simulado: trabajando."}
        assert (await client.get("/tasks/otra", headers=auth)).status_code == 404
