"""Trazas para el debrief: identificadores, descarga saneada y fichas por tarea."""

import json

import httpx

from eval.trazas import download, load, summarize, task_ids

ID_A = "a" * 32
ID_B = "0123456789abcdef" * 2

LOG = f"""\
2026-10-10T20:04:09Z [INFO] tarea finalizada task_id="{ID_A}" estado="fallida"
2026-10-10T20:05:10Z [INFO] tarea finalizada task_id="{ID_B}" estado="terminada"
2026-10-10T20:06:10Z [INFO] tarea recibida task_id="{ID_A}"
"""

BLOCKED_SAVE = [
    {"evento": "inicio", "tarea": "Registra al cliente Papelería Los Andes, NIT 901234567."},
    {
        "paso": 1,
        "accion": {
            "kind": "click",
            "x": 963,
            "y": 136,
            "objetivo": "Razón social",
            "efecto": "editar",
        },
        "observacion": "Formulario vacío",
        "resultado": "sin efecto visible en la pantalla",
        "error_code": "CLICK_NO_EFFECT",
    },
    {
        "paso": 2,
        "accion": {"kind": "click", "x": 864, "y": 376, "objetivo": "Aplicar", "efecto": "guardar"},
        "verificacion": {
            "outcome": "block",
            "reason": "no hay búsqueda previa por NIT",
            "checks": {"dentro_de_tarea": True, "registro_correcto": False},
        },
        "resultado": "BLOQUEADA por la verificación",
        "error_code": "GATE_BLOCKED",
    },
    {
        "paso": 3,
        "accion": {"kind": "fail_task", "razon": "no pude guardar"},
        "resultado": "fallida",
    },
    {
        "evento": "fin",
        "estado": "fallida",
        "error_code": None,
        "cost_usd": 0.02,
        "elapsed_s": 90.5,
        "resumen": "No pude guardar.",
    },
]


def test_task_ids_come_from_any_text_in_order_and_once():
    assert task_ids(LOG) == [ID_A, ID_B]
    assert task_ids("sin identificadores") == []


def test_summary_points_at_the_first_deviation_and_the_blocks():
    card = summarize("E1", BLOCKED_SAVE)

    assert "Registra al cliente Papelería Los Andes" in card
    assert "fallida · 3 pasos · 90.5 s · US$0.0200" in card
    assert "Categoría de partida:** verificación (acción bloqueada)" in card
    assert "Primer desvío:** paso 2, acción bloqueada por la verificación" in card
    assert "Avisos menores:** paso 1 CLICK_NO_EFFECT (clic en (963, 136)" in card
    assert "Bloqueo** en el paso 2 (registro_correcto): no hay búsqueda previa por NIT" in card


def test_summary_of_a_rejected_close():
    events = [
        {"evento": "inicio", "tarea": "¿Cuántas facturas vencidas tiene Ferretería Ruiz?"},
        {
            "paso": 1,
            "accion": {"kind": "finish_task", "respuesta": ["45"]},
            "verificacion": {
                "outcome": "block",
                "reason": "no cuadra",
                "checks": {"respuesta_respaldada": False},
            },
            "resultado": "la verificación final RECHAZÓ el cierre",
        },
        {"evento": "fin", "estado": "fallida", "error_code": None, "resumen": "Sin conteo."},
    ]

    card = summarize("E3", events)

    assert "verificación (cierre rechazado)" in card
    assert "paso 1, cierre rechazado por la verificación" in card
    assert "Último cierre:** block · no cuadra" in card


async def test_download_saves_each_trace_without_secrets(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/tasks/{ID_A}/traza":
            return httpx.Response(200, json=[{"evento": "inicio", "tarea": "clave-123 visible"}])
        return httpx.Response(404, json={"detail": "La tarea no existe"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://agente"
    ) as client:
        saved = await download(client, [ID_A, ID_B], tmp_path, {"contraseña": "clave-123"})

    assert saved == [tmp_path / f"{ID_A}.json"]
    data = json.loads(saved[0].read_text())
    assert data == [{"evento": "inicio", "tarea": "*** visible"}]


def test_load_reads_a_list_an_object_with_traza_and_jsonl(tmp_path):
    events = [{"evento": "inicio", "tarea": "t"}, {"evento": "fin", "estado": "fallida"}]
    as_list = tmp_path / "a.json"
    as_list.write_text(json.dumps(events))
    as_object = tmp_path / "b.json"
    as_object.write_text(json.dumps({"estado": {"estado": "fallida"}, "traza": events}))
    as_lines = tmp_path / "c.jsonl"
    as_lines.write_text("\n".join(json.dumps(e) for e in events))

    assert load(as_list) == load(as_object) == load(as_lines) == events
