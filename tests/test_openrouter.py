"""Cliente de OpenRouter (plan, T05): respuestas HTTP simuladas y una prueba en vivo."""

import base64
import io
import json
import logging

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError

from app.config import Settings
from app.llm import openrouter
from app.llm.openrouter import OPENROUTER_URL, LLMError, OpenRouterClient, image_part
from app.models import ErrorCode
from tests.screens import new_client_form

KEY = "sk-or-v1-llave-de-prueba"

CLICK_TOOL = {
    "type": "function",
    "function": {
        "name": "click",
        "description": "Hace clic en un punto de la pantalla, en píxeles.",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "objetivo": {"type": "string"},
                "observacion": {"type": "string"},
            },
            "required": ["x", "y", "objetivo", "observacion"],
        },
    },
}
MESSAGES = [{"role": "user", "content": "Haz clic en Guardar."}]


def completion(tool_calls=None, content=None, cost=0.0004) -> dict:
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "id": "gen-1",
        "choices": [{"index": 0, "finish_reason": "tool_calls", "message": message}],
        "usage": {"prompt_tokens": 1500, "completion_tokens": 80, "cost": cost},
    }


def call(name: str, arguments: dict | str) -> dict:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {"id": "call_1", "type": "function", "function": {"name": name, "arguments": raw}}


class Server:
    """Responde en orden con lo guionado; una excepción se lanza como falla de red."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def body(self, index: int = 0) -> dict:
        return json.loads(self.requests[index].content)


@pytest.fixture
def settings():
    return Settings(
        _env_file=None, team_token="ftr_prueba", openrouter_api_key=KEY, vlm_reasoning_effort="low"
    )


@pytest.fixture
def sleeps(monkeypatch):
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(openrouter, "_sleep", fake_sleep)
    return waits


def client_for(settings: Settings, server: Server) -> OpenRouterClient:
    return OpenRouterClient(settings, transport=httpx.MockTransport(server))


async def test_request_shape_and_first_tool_call(settings, sleeps):
    first = call("click", {"x": 640, "y": 410, "objetivo": "Guardar", "observacion": "veo"})
    second = call("wait", {"segundos": 1})
    server = Server(httpx.Response(200, json=completion([first, second], content="Voy")))
    llm = client_for(settings, server)

    result = await llm.chat("anthropic/claude-haiku-5.5", MESSAGES, [CLICK_TOOL])

    assert result.tool_name == "click"
    assert result.arguments == {"x": 640, "y": 410, "objetivo": "Guardar", "observacion": "veo"}
    assert result.text == "Voy"
    assert result.cost_usd == pytest.approx(0.0004)
    assert result.latency_s >= 0
    assert sleeps == []

    request = server.requests[0]
    assert request.method == "POST"
    assert str(request.url) == OPENROUTER_URL
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = server.body()
    assert body["model"] == "anthropic/claude-haiku-5.5"
    assert body["messages"] == MESSAGES
    assert body["tools"] == [CLICK_TOOL]
    assert body["tool_choice"] == "auto"
    assert body["reasoning"] == {"effort": "low"}
    assert body["provider"] == {"require_parameters": True}
    # El modelo no acepta temperature: con require_parameters, enviarla dejaría sin proveedor.
    assert "temperature" not in body
    await llm.aclose()


async def test_answer_without_tool_call(settings):
    server = Server(httpx.Response(200, json=completion(content="No sé qué hacer.")))

    result = await client_for(settings, server).chat("m", MESSAGES, [CLICK_TOOL])

    assert (result.tool_name, result.arguments, result.text) == (None, {}, "No sé qué hacer.")


async def test_missing_cost_counts_as_zero(settings):
    data = completion([call("click", {"x": 1, "y": 2})])
    del data["usage"]
    server = Server(httpx.Response(200, json=data))

    result = await client_for(settings, server).chat("m", MESSAGES, [CLICK_TOOL])

    assert result.cost_usd == 0.0


@pytest.mark.parametrize("status", [429, 500, 502, 503])
async def test_retries_transient_errors_with_backoff(settings, sleeps, status):
    ok = httpx.Response(200, json=completion([call("click", {"x": 1, "y": 2})]))
    server = Server(httpx.Response(status, json={"error": {"message": "ocupado"}}), ok)

    result = await client_for(settings, server).chat("m", MESSAGES, [CLICK_TOOL])

    assert result.tool_name == "click"
    assert len(server.requests) == 2
    assert sleeps == [1.0]


async def test_gives_up_after_two_retries(settings, sleeps):
    server = Server(*[httpx.Response(503, text="no disponible") for _ in range(3)])

    with pytest.raises(LLMError) as error:
        await client_for(settings, server).chat("m", MESSAGES, [CLICK_TOOL])

    assert error.value.code is ErrorCode.VLM_ERROR
    assert "503" in str(error.value)
    assert len(server.requests) == 3
    assert sleeps == [1.0, 2.0]


async def test_network_errors_are_retried(settings, sleeps):
    request = httpx.Request("POST", OPENROUTER_URL)
    server = Server(
        httpx.ConnectError("sin red", request=request),
        httpx.ReadTimeout("lento", request=request),
        httpx.Response(200, json=completion([call("click", {"x": 1, "y": 2})])),
    )

    result = await client_for(settings, server).chat("m", MESSAGES, [CLICK_TOOL])

    assert result.tool_name == "click"
    assert sleeps == [1.0, 2.0]


async def test_retry_after_is_respected_and_capped(settings, sleeps):
    ok = httpx.Response(200, json=completion([call("click", {"x": 1, "y": 2})]))
    server = Server(
        httpx.Response(429, headers={"retry-after": "4"}, json={}),
        httpx.Response(429, headers={"retry-after": "600"}, json={}),
        ok,
    )

    await client_for(settings, server).chat("m", MESSAGES, [CLICK_TOOL])

    assert sleeps == [4.0, openrouter.MAX_RETRY_AFTER_S]


@pytest.mark.parametrize("status", [400, 401, 402, 404])
async def test_client_errors_fail_without_retry(settings, sleeps, status):
    server = Server(httpx.Response(status, json={"error": {"code": status, "message": "mal"}}))

    with pytest.raises(LLMError) as error:
        await client_for(settings, server).chat("m", MESSAGES, [CLICK_TOOL])

    assert error.value.code is ErrorCode.VLM_ERROR
    assert str(status) in str(error.value)
    assert len(server.requests) == 1
    assert sleeps == []


async def test_provider_error_inside_a_200(settings, sleeps):
    ok = httpx.Response(200, json=completion([call("click", {"x": 1, "y": 2})]))
    server = Server(
        httpx.Response(200, json={"error": {"code": 502, "message": "proveedor caído"}}), ok
    )

    result = await client_for(settings, server).chat("m", MESSAGES, [CLICK_TOOL])

    assert result.tool_name == "click"
    assert len(server.requests) == 2


@pytest.mark.parametrize("body", [b"<html>gateway</html>", b'{"choices": []}'])
async def test_malformed_bodies_are_retried_then_fail(settings, sleeps, body):
    server = Server(*[httpx.Response(200, content=body) for _ in range(3)])

    with pytest.raises(LLMError):
        await client_for(settings, server).chat("m", MESSAGES, [CLICK_TOOL])

    assert len(server.requests) == 3


@pytest.mark.parametrize("arguments", ['{"x": 1, "y":', "[1, 2]"])
async def test_invalid_tool_arguments_are_asked_again(settings, sleeps, arguments):
    server = Server(
        httpx.Response(200, json=completion([call("click", arguments)], cost=0.001)),
        httpx.Response(200, json=completion([call("click", {"x": 1, "y": 2})], cost=0.002)),
    )

    result = await client_for(settings, server).chat("m", MESSAGES, [CLICK_TOOL])

    assert (result.tool_name, result.arguments) == ("click", {"x": 1, "y": 2})
    assert result.cost_usd == pytest.approx(0.003)  # la respuesta descartada también se cobró
    assert len(server.requests) == 2
    assert sleeps == []


@pytest.mark.parametrize(
    ("arguments", "message"),
    [('{"x": 1, "y":', "no son JSON válido"), ("[1, 2]", "no son un objeto")],
)
async def test_invalid_tool_arguments_twice_return_no_tool(settings, arguments, message):
    """Sin excepción: el ciclo lo trata como una respuesta inválida y sigue."""
    bad = httpx.Response(200, json=completion([call("click", arguments)], cost=0.001))
    server = Server(bad, bad)

    result = await client_for(settings, server).chat("m", MESSAGES, [CLICK_TOOL])

    assert result.tool_name is None
    assert result.arguments == {}
    assert result.text == f"los argumentos de click {message}"
    assert result.cost_usd == pytest.approx(0.002)
    assert len(server.requests) == 2


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        pytest.param(
            # Tal como llegó en E3: la observación se tragó la `x`.
            {
                "observacion": 'Página 2; sigo.</observacion>\n<parameter name="x">208',
                "y": 684,
                "objetivo": "Siguiente",
            },
            {
                "observacion": "Página 2; sigo.",
                "y": 684,
                "objetivo": "Siguiente",
                "x": 208,
            },
            id="E3",
        ),
        pytest.param(
            {
                "resumen": 'Hay 45.</resumen>\n<parameter name="respuesta">["45"]</parameter>\n'
                '<parameter name="es_listado">true',
                "evidencia": "Página 3",
            },
            {
                "resumen": "Hay 45.",
                "evidencia": "Página 3",
                "respuesta": ["45"],
                "es_listado": True,
            },
            id="varios-y-json",
        ),
        pytest.param(
            {"observacion": 'veo</observacion>\n<parameter name="x">9', "x": 208, "y": 684},
            {"observacion": "veo", "x": 208, "y": 684},
            id="no-pisa-lo-que-ya-vino",
        ),
        pytest.param(
            {"x": 208, "y": 684, "observacion": "Página 2.</observacion>"},
            {"x": 208, "y": 684, "observacion": "Página 2."},
            id="cierre-suelto",
        ),
    ],
)
async def test_parameters_leaked_inside_a_text_are_recovered(settings, arguments, expected):
    server = Server(httpx.Response(200, json=completion([call("click", arguments)])))

    result = await client_for(settings, server).chat("m", MESSAGES, [CLICK_TOOL])

    assert result.arguments == expected
    assert len(server.requests) == 1  # se arregla sin volver a preguntar


async def test_transient_errors_are_retried_inside_each_attempt(settings, sleeps):
    server = Server(
        httpx.Response(200, json=completion([call("click", "{")])),
        httpx.Response(503, json={"error": {"message": "ocupado"}}),
        httpx.Response(200, json=completion([call("click", {"x": 1, "y": 2})])),
    )

    result = await client_for(settings, server).chat("m", MESSAGES, [CLICK_TOOL])

    assert result.tool_name == "click"
    assert len(server.requests) == 3
    assert sleeps == [openrouter.BACKOFF_S]


async def test_key_never_reaches_logs_or_errors(settings, sleeps, caplog):
    caplog.set_level(logging.DEBUG)
    echo = {"error": {"message": f"llave rechazada: Bearer {KEY}"}}
    server = Server(
        httpx.Response(500, json=echo),
        httpx.Response(200, json=completion([call("click", {"x": 1, "y": 2})])),
        httpx.Response(401, json=echo),
    )
    llm = client_for(settings, server)

    await llm.chat("m", MESSAGES, [CLICK_TOOL])
    with pytest.raises(LLMError) as error:
        await llm.chat("m", MESSAGES, [CLICK_TOOL])

    assert KEY not in str(error.value)
    assert "***" in str(error.value)
    assert caplog.records
    assert KEY not in caplog.text
    assert KEY not in repr(llm.settings)


def test_image_part_is_a_png_data_url():
    image = Image.new("RGB", (1280, 800), "white")

    part = image_part(image)

    assert part["type"] == "image_url"
    prefix, data = part["image_url"]["url"].split(",", 1)
    assert prefix == "data:image/png;base64"
    with Image.open(io.BytesIO(base64.b64decode(data))) as decoded:
        assert decoded.format == "PNG"
        assert decoded.size == (1280, 800)


# --- En vivo -------------------------------------------------------------------------------


def live_settings() -> Settings:
    try:
        return Settings()
    except ValidationError:
        pytest.skip("falta OPENROUTER_API_KEY o TEAM_TOKEN en el entorno o en .env")


@pytest.mark.live
async def test_live_tool_call_from_a_screenshot():
    settings = live_settings()
    image, button = new_client_form()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Haz clic en el botón Guardar usando la herramienta."},
                image_part(image),
            ],
        }
    ]
    llm = OpenRouterClient(settings)
    try:
        result = await llm.chat(settings.vlm_model, messages, [CLICK_TOOL])
    finally:
        await llm.aclose()

    print(
        f"\n[en vivo] modelo={settings.vlm_model} herramienta={result.tool_name} "
        f"args={result.arguments} botón={button} costo=US${result.cost_usd:.6f} "
        f"latencia={result.latency_s:.1f}s"
    )
    assert result.tool_name == "click"
    assert isinstance(result.arguments["x"], int) and isinstance(result.arguments["y"], int)
    assert 0 <= result.arguments["x"] < 1280 and 0 <= result.arguments["y"] < 800
    assert 0 < result.cost_usd < 0.001
