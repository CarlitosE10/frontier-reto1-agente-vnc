"""Comparación de modelos por precisión de clic (T13), con `FakeLLM`."""

import json
from pathlib import Path

import pytest
from PIL import Image

from app.llm.openrouter import LLMError
from eval.grounding import (
    GROUNDING_DIR,
    TABLES_END,
    TABLES_START,
    Budget,
    ModelConfig,
    Screen,
    StateQuestion,
    Target,
    box_distance,
    load_screens,
    main,
    plan_jobs,
    read_results,
    render_tables,
    run_jobs,
    score_click,
    score_state,
    write_report,
)
from tests.fakes import FakeLLM, tool_call, write_screen

SIZE = (1280, 800)
BUSCAR = Target("buscar", "el botón Buscar", (509, 119, 578, 140))
ESTADO = StateQuestion("habilitado", "¿El botón Anterior está habilitado?", ("sí", "no"), "no")
HAIKU = ModelConfig("anthropic/claude-haiku-5.5", "pixels")
QWEN = ModelConfig("qwen/qwen3.7-plus", "norm1000")


def click(x, y, **extra):
    arguments = {"observacion": "veo el filtro", "objetivo": "Buscar", "efecto": "navegar"}
    return tool_call("click", {**arguments, "x": x, "y": y, **extra}, cost_usd=0.001)


@pytest.fixture
def screen(tmp_path):
    path = write_screen(tmp_path / "clientes.png", "white")
    return Screen("clientes", path, "Clientes", (BUSCAR,), (ESTADO,))


# --- Etiquetas


def test_labels_are_consistent():
    screens = load_screens()
    assert len(screens) >= 10
    for screen in screens:
        width, height = Image.open(screen.captura).size
        ids = [t.id for t in screen.objetivos] + [q.id for q in screen.estados]
        assert len(ids) == len(set(ids)), screen.name
        for target in screen.objetivos:
            x1, y1, x2, y2 = target.box
            assert 0 <= x1 < x2 < width and 0 <= y1 < y2 < height, (screen.name, target.id)
        for question in screen.estados:
            assert question.respuesta in question.opciones, (screen.name, question.id)


# --- Puntaje


def test_click_inside_the_box_hits():
    row = score_click(click(544, 130), BUSCAR, SIZE, "pixels")
    assert row["valida"] and row["acierto"]
    assert (row["x"], row["y"], row["distancia_px"]) == (544, 130, 0)


def test_click_outside_the_box_misses_with_distance():
    row = score_click(click(544, 160), BUSCAR, SIZE, "pixels")
    assert row["valida"] and not row["acierto"]
    assert row["distancia_px"] == 20


def test_norm1000_is_converted_and_the_other_scale_is_checked():
    # (425, 162) en 0-1000 es (544, 130) en píxeles; leído como píxeles cae fuera.
    row = score_click(click(425, 162), BUSCAR, SIZE, "norm1000")
    assert row["acierto"] and not row["acierto_otra_escala"]

    # Un modelo que responde en 0-1000 aunque el prompt pida píxeles.
    row = score_click(click(425, 162), BUSCAR, SIZE, "pixels")
    assert not row["acierto"] and row["acierto_otra_escala"]


@pytest.mark.parametrize(
    "chat",
    [
        click([544, 130], None),  # el punto entero en x
        click(544, 130, efecto="clic"),
        tool_call("type_text", {"texto": "hola", "campo": "Nombre", "observacion": ""}),
    ],
)
def test_invalid_tool_calls_never_hit(chat):
    row = score_click(chat, BUSCAR, SIZE, "pixels")
    assert not row["valida"] and not row["acierto"]
    assert row["error"]


def test_state_answers():
    assert score_state(tool_call("responder", {"opcion": "no"}), ESTADO)["correcta"]
    wrong = score_state(tool_call("responder", {"opcion": "sí"}), ESTADO)
    assert wrong["valida"] and not wrong["correcta"]
    invalid = score_state(tool_call("responder", {"opcion": "quizás"}), ESTADO)
    assert not invalid["valida"] and not invalid["correcta"]


def test_box_distance():
    assert box_distance((10, 10), (0, 0, 20, 20)) == 0
    assert box_distance((23, 24), (0, 0, 20, 20)) == 5


# --- Ejecución


def test_jobs_interleave_models_target_by_target(screen):
    jobs = plan_jobs([screen], [HAIKU, QWEN])
    assert [(j.config, j.kind) for j in jobs] == [
        (HAIKU, "clic"),
        (QWEN, "clic"),
        (HAIKU, "estado"),
        (QWEN, "estado"),
    ]
    assert [j.kind for j in plan_jobs([screen], [HAIKU], clicks_only=True)] == ["clic"]


async def test_run_jobs_scores_and_appends_results(screen, tmp_path):
    results = tmp_path / "resultados.jsonl"
    llm = FakeLLM([click(544, 130), tool_call("responder", {"opcion": "no"}, cost_usd=0.002)])

    done, skipped = await run_jobs(plan_jobs([screen], [HAIKU]), llm, Budget(1.0), results, 1)

    assert (done, skipped) == (2, 0)
    rows = read_results(results)
    assert [(r["tipo"], r["id"], r["costo_usd"]) for r in rows] == [
        ("clic", "buscar", 0.001),
        ("estado", "habilitado", 0.002),
    ]
    assert rows[0]["acierto"] and rows[1]["correcta"]
    system, user = llm.calls[0]["messages"]
    assert "x e y son píxeles" in system["content"]
    assert user["content"][0]["type"] == "image_url"
    assert "el botón Buscar" in user["content"][1]["text"]
    assert [t["function"]["name"] for t in llm.calls[0]["tools"]] == ["click"]
    assert llm.calls[1]["tools"][0]["function"]["parameters"]["properties"]["opcion"]["enum"] == [
        "sí",
        "no",
    ]


async def test_llm_errors_are_recorded_as_failures(screen, tmp_path):
    results = tmp_path / "resultados.jsonl"
    llm = FakeLLM([LLMError(message="HTTP 500"), LLMError(message="HTTP 500")])

    await run_jobs(plan_jobs([screen], [HAIKU]), llm, Budget(1.0), results, 1)

    clic, estado = read_results(results)
    assert not clic["valida"] and not clic["acierto"] and clic["error"] == "HTTP 500"
    assert not estado["correcta"]
    assert render_tables([clic, estado], [screen])  # el reporte no se cae con fallas


async def test_budget_stops_before_spending_more(screen, tmp_path):
    results = tmp_path / "resultados.jsonl"
    llm = FakeLLM([click(544, 130)])
    budget = Budget(0.0015, spent_usd=0.0)

    # La primera llamada reserva 0.001 (el costo conocido); la segunda ya no cabe.
    done, skipped = await run_jobs(
        plan_jobs([screen], [HAIKU]), llm, budget, results, 1, {HAIKU.model: 0.001}
    )

    assert (done, skipped) == (1, 1)
    assert llm.remaining == 0
    assert budget.spent_usd == pytest.approx(0.001)


# --- Reporte


def test_report_tables_keep_the_conclusions(screen, tmp_path):
    rows = [
        {
            "modelo": HAIKU.model,
            "coord_mode": "pixels",
            "pantalla": "clientes",
            "tipo": "clic",
            "id": "buscar",
            "valida": True,
            "acierto": False,
            "acierto_otra_escala": False,
            "x": 544,
            "y": 160,
            "distancia_px": 20.0,
            "latencia_s": 2.0,
            "costo_usd": 0.001,
        },
        {
            "modelo": HAIKU.model,
            "coord_mode": "pixels",
            "pantalla": "clientes",
            "tipo": "estado",
            "id": "habilitado",
            "valida": True,
            "respuesta": "sí",
            "esperada": "no",
            "correcta": False,
            "latencia_s": 1.0,
            "costo_usd": 0.001,
        },
    ]
    report = tmp_path / "reporte.md"
    report.write_text(
        f"# Reporte\n\nAntes.\n\n{TABLES_START}\nviejo\n{TABLES_END}\n\nConclusión.\n"
    )

    write_report(rows, [screen], report)

    text = report.read_text()
    assert text.startswith("# Reporte\n\nAntes.") and text.endswith("Conclusión.\n")
    assert "viejo" not in text
    assert "| `clientes` | 0/1 |" in text
    assert "(544, 160) a 20 px de [509, 119, 578, 140]" in text
    assert "respondió «sí»; se esperaba «no»" in text


def test_main_only_report_does_not_call_models(tmp_path, monkeypatch):
    def no_settings():
        raise AssertionError("--solo-reporte no debe crear el cliente")

    monkeypatch.setattr("eval.grounding.Settings", no_settings)
    results = tmp_path / "resultados.jsonl"
    results.write_text("")
    report = tmp_path / "reporte.md"

    assert main(["--solo-reporte", "--resultados", str(results), "--reporte", str(report)]) == 0
    assert TABLES_START in report.read_text()


def test_committed_results_match_the_labels():
    """Cada resultado versionado corresponde a un objetivo o pregunta que existe."""
    path = GROUNDING_DIR / "resultados.jsonl"
    if not path.exists():
        pytest.skip("todavía no hay resultados")
    items = {
        (s.name, kind, item.id)
        for s in load_screens()
        for kind, items in (("clic", s.objetivos), ("estado", s.estados))
        for item in items
    }
    for row in read_results(path):
        assert (row["pantalla"], row["tipo"], row["id"]) in items
        json.dumps(row)  # serializable


def test_labels_point_to_versioned_captures():
    for screen in load_screens():
        assert screen.captura.is_relative_to(Path(__file__).resolve().parent / "fixtures")
