# Plan de implementación · Agente VNC

Este plan lleva a código el diseño de [diseno-sistema.md](diseno-sistema.md). Cada tarea dice qué construir, en qué archivos y cómo saber que está lista. Los contratos de la sección 2 son la referencia común: todo módulo los respeta tal cual, para que las piezas encajen al integrarlas.

## 0. Decisiones vigentes

Estas decisiones reemplazan lo que diga el diseño en los mismos puntos.

- **Un solo modelo (VLM), configurable.** Elegido en T13: **`VLM_MODEL=anthropic/claude-haiku-5.5` con `VLM_COORD_MODE=pixels`**, vía OpenRouter ([reporte](../eval/grounding/reporte.md)). Sobre 10 capturas de SIGECOM acertó 121 de 121 clics, con 100 % de tool calls válidas, 2.5 s de latencia p50 y US$0.00034 por llamada. `qwen/qwen3.7-plus` (`norm1000`) acertó 55 %, con 14 % de tool calls inválidas, el doble de latencia y casi el doble de costo: queda descartado. El cambio de modelo es solo una variable de entorno.
- **Coordenadas.** `VLM_COORD_MODE=pixels` (Claude, GPT) o `norm1000` (Qwen, Gemini). El código convierte siempre a píxeles reales de la pantalla. T13 confirmó que Qwen3.7 Plus responde en 0–1000 aunque el prompt pida píxeles: si se usa, va con `norm1000`.
- **Sin Jev por ahora.** Las acciones irreversibles y el éxito final los verifica el mismo VLM en una llamada aparte, con contexto limpio (diseño D6 y D7). La interfaz `Gate` queda lista para sumar Jev después sin tocar el resto.
- **Tope de gasto por tarea** (`TASK_MAX_COST_USD`), sumando `usage.cost` de cada llamada.
- **Fuera de este plan** hasta que las métricas lo pidan: modo cuadrícula, localizador separado (planificador + grounder), escalamiento a otro modelo, conteo paginado con OCR y Jev (tarea T18).

## 1. Estructura del repositorio

```
app/
  main.py               # crea la app FastAPI
  api.py                # rutas y autenticación
  tasks.py              # TaskRunner: candados, presupuesto, cancelación
  config.py             # Settings desde variables de entorno
  models.py             # tipos compartidos (sección 2)
  tracing.py            # trazas JSONL + capturas
  vnc/
    bridge.py           # puente TCP ↔ WSS
    client.py           # DesktopSession
    probe.py            # sonda: imprime el saludo RFB del escritorio
  perception/
    diff.py             # comparación de capturas
    ocr.py              # Tesseract spa
  llm/
    openrouter.py       # chat con herramientas e imágenes
  agent/
    tools.py            # esquemas de herramientas y parse_action
    prompts.py          # prompt del sistema y prompt de verificación
    gate.py             # filtro: reglas + verificación del VLM
    summary.py          # resumen, normalización y saneador
    loop.py             # ciclo del agente
eval/
  harness.py            # arnés de evaluación
  grounding.py          # comparación de modelos por precisión de clic
  cases/                # pruebas oficiales y propias (JSON)
  grounding/            # capturas y objetivos etiquetados
tests/
  fakes.py              # FakeDesktop, FakeLLM
  fixtures/             # capturas de ejemplo
Dockerfile
pyproject.toml
.env.example
.gitignore
README.md               # cómo correr el proyecto
docs/                   # diseño, plan, diagramas y exportaciones
frontier-reto-1/        # enunciado (README_Reto.md), rúbrica y pruebas oficiales; no se modifica
```

La raíz del repositorio es la raíz del proyecto: todos los comandos se corren desde ahí, y el `.env` vive ahí (está en `.gitignore`).

## 2. Contratos compartidos

### 2.1 Configuración (`app/config.py`)

`Settings` (pydantic-settings) lee estas variables. Ningún módulo lee el entorno por su cuenta.

| Variable | Defecto | Uso |
|---|---|---|
| `TEAM_TOKEN` | — | Token Bearer que exige la API |
| `OPENROUTER_API_KEY` | — | Llave de OpenRouter |
| `VLM_MODEL` | `anthropic/claude-haiku-5.5` | Modelo que decide cada paso y verifica |
| `VLM_COORD_MODE` | `pixels` | `pixels` o `norm1000` |
| `VLM_REASONING_EFFORT` | `low` | Esfuerzo de razonamiento enviado a OpenRouter |
| `VERIFY_ENABLED` | `true` | Activa la verificación antes de acciones irreversibles y antes de reportar éxito |
| `TASK_TIME_BUDGET_S` | `270` | Presupuesto de tiempo por tarea |
| `TASK_MAX_STEPS` | `40` | Presupuesto de pasos |
| `TASK_MAX_COST_USD` | `0.15` | Tope de gasto por tarea |
| `CLICK_HOLD_MS` / `DOUBLE_CLICK_HOLD_MS` | `150` / `120` | Tiempo entre bajar y soltar el botón |
| `CHANGE_TIMEOUT_S` | `1.2` | Espera máxima a que la pantalla cambie |
| `STABLE_INTERVAL_S` / `STABLE_TIMEOUT_S` | `0.25` / `1.5` | Intervalo y tope de la espera de estabilidad |
| `DIFF_MIN_PIXELS` | `50` | Píxeles distintos para considerar que hubo cambio |
| `IRREVERSIBLE_KEYWORDS` | `guardar,crear,registrar,aceptar,confirmar,sí,eliminar,borrar,anular,exportar,enviar` | Palabras que marcan una acción irreversible |
| `HISTORY_STEPS` | `10` | Pasos de historial que ve el VLM |
| `EVIDENCE_SCREENS` | `5` | Pantallas recientes que se guardan como evidencia |
| `TRACE_DIR` | `./traces` | Carpeta de trazas |

### 2.2 Tipos (`app/models.py`)

```python
class TaskStatus(str, Enum):          # en_curso | terminada | fallida
class ErrorCode(str, Enum):           # VNC_CONNECT_FAILED, VNC_AUTH_FAILED, WS_DISCONNECTED,
                                      # SCREEN_NOT_STABLE, CLICK_NO_EFFECT, LOOP_DETECTED, VLM_ERROR,
                                      # GATE_BLOCKED, BUDGET_EXHAUSTED, CANCELLED
class Effect(str, Enum):              # navegar | editar | guardar | exportar | eliminar

class Desktop(BaseModel):             url: str; password: SecretStr
class TaskRequest(BaseModel):         tarea: str; escritorio: Desktop

# Acciones del VLM (unión discriminada por "kind"); todas llevan observacion: str
class Click(BaseModel):               x: int; y: int; objetivo: str; efecto: Effect; double: bool = False
class TypeText(BaseModel):            texto: str; campo: str
class PressKey(BaseModel):            combinacion: str            # "enter", "tab", "ctrl+a", "esc"
class Scroll(BaseModel):              x: int; y: int; direccion: Literal["up", "down"]; cantidad: int
class Wait(BaseModel):                segundos: float             # máximo 3
class Candidate(BaseModel):           nombre: str; identificador: str
class FinishTask(BaseModel):          resumen: str; respuesta: list[str] | None; evidencia: str
class FailTask(BaseModel):            razon: str; datos_clave: list[str]; candidatos: list[Candidate] = []
Action = Click | TypeText | PressKey | Scroll | Wait | FinishTask | FailTask
# El primer paso además trae fecha_app: str | None

class GateDecision(BaseModel):        outcome: Literal["approve", "block"]; reason: str
                                      checks: dict[str, bool] | None
class TaskRecord:                     id, request, status, summary, progress, cost_usd,
                                      error_code, created_at
class AgentResult(BaseModel):         status: TaskStatus; summary: str; error_code: ErrorCode | None
                                      cost_usd: float; steps: int
```

### 2.3 Interfaces entre módulos

```python
# app/vnc/client.py
class DesktopError(Exception): code: ErrorCode
class DesktopSession:                                   # async context manager
    def __init__(self, url: str, password: str, settings: Settings): ...
    size: tuple[int, int]                               # leído del servidor VNC
    async def screenshot(self) -> Image.Image
    async def settle(self, before: Image.Image) -> Image.Image   # espera cambio y luego estabilidad
    async def click(self, x: int, y: int, double: bool = False) -> None
    async def type_text(self, text: str) -> None        # ctrl+a y luego el texto
    async def press(self, combo: str) -> None
    async def scroll(self, x: int, y: int, direction: str, amount: int) -> None

# app/perception/diff.py y ocr.py
def changed_pixels(a: Image.Image, b: Image.Image) -> int
def read_text(image: Image.Image, box: tuple[int, int, int, int] | None = None) -> str
def words_near(image: Image.Image, x: int, y: int, radius: int = 40) -> list[str]

# app/llm/openrouter.py
class LLMError(Exception): code: ErrorCode
@dataclass
class ChatResult: tool_name: str | None; arguments: dict; text: str; cost_usd: float; latency_s: float
class OpenRouterClient:
    async def chat(self, model: str, messages: list[dict], tools: list[dict]) -> ChatResult

# app/agent/tools.py
TOOLS: list[dict]                                       # esquemas JSON (formato OpenAI tools)
def parse_action(name: str, arguments: dict, screen_size: tuple[int, int], coord_mode: str) -> Action

# app/agent/gate.py
def is_irreversible(action: Action, words_near_point: list[str], in_form: bool, keywords: list[str]) -> bool
class Gate:                                             # hoy verifica con el VLM; mañana puede sumar Jev
    def __init__(self, llm: OpenRouterClient, settings: Settings): ...
    async def check_action(self, task: str, action: Action, screen: Image.Image,
                           screen_text: str, evidence: list[str]) -> GateDecision
    async def check_completion(self, task: str, result: FinishTask, screen: Image.Image,
                               screen_text: str) -> GateDecision

# app/agent/summary.py
def build_summary(result: FinishTask | FailTask | None, error_code: ErrorCode | None) -> str
def normalize_number(value: str) -> str
def sanitize(text: str, secrets: list[str]) -> str

# app/tracing.py
class Trace:
    def __init__(self, task_id: str, root: Path, secrets: list[str]): ...
    def step(self, **fields) -> None                    # una línea JSONL saneada
    def screenshot(self, image: Image.Image, label: str) -> str
    def read(self) -> list[dict]

# app/agent/loop.py
async def run_agent(record: TaskRecord, desktop_factory: Callable[[], DesktopSession],
                    llm: OpenRouterClient, gate: Gate, trace: Trace,
                    cancel: asyncio.Event, settings: Settings) -> AgentResult

# app/tasks.py
class TaskRunner:
    def submit(self, request: TaskRequest) -> str       # no toca VNC; devuelve task_id
    def get(self, task_id: str) -> TaskRecord | None
```

### 2.4 Dobles de prueba (`tests/fakes.py`)

- `FakeDesktop(screens: list[Path])` cumple la interfaz de `DesktopSession`: entrega capturas de archivo y registra cada acción recibida.
- `FakeLLM(script: list[ChatResult])` devuelve respuestas guionadas, tanto de acciones como de verificaciones.

Con estos dobles, cada módulo se prueba sin escritorio ni modelos reales.

---

## 3. Tareas

### T01 · Esqueleto y contratos
- **Hacer:** la estructura de la sección 1, `pyproject.toml` (fastapi, uvicorn, pydantic, pydantic-settings, vncdotool, websockets, httpx, pillow, numpy, pytesseract, pytest, pytest-asyncio, ruff), `config.py` y `models.py` completos, las interfaces de la sección 2.3 como stubs que lanzan `NotImplementedError` y `tests/fakes.py`.
  - El proyecto usa **uv con Python 3.12** (`requires-python = ">=3.12"`, `uv.lock` versionado). Todos los comandos se corren con `uv run`.
  - `.env.example` ya existe: `config.py` lee exactamente esas variables.
- **Listo cuando:** `uv run pytest` corre en verde, `uv run ruff check` no reporta errores y todos los módulos se importan.

### T02 · Sonda y puente VNC
- **Hacer:**
  - `vnc/probe.py`: se conecta por WebSocket (subprotocolo `binary`) e imprime el saludo RFB.
  - `vnc/bridge.py`: servidor TCP en `127.0.0.1`, puerto efímero, que por cada conexión abre el WebSocket a la URL recibida y copia bytes en ambos sentidos. Se cierra limpio al terminar la tarea.
- **Listo cuando:**
  - `python -m app.vnc.probe wss://<escritorio>/websockify` imprime `RFB 003.00x`.
  - Una prueba con un servidor WebSocket local de eco verifica la copia en ambos sentidos y el cierre.

### T03 · Cliente VNC (`DesktopSession`)
- **Hacer:** `vncdotool` conectado al puente, con las llamadas bloqueantes vía `asyncio.to_thread`.
  - `size` leído del servidor.
  - `click`: `mouseDown`, espera `CLICK_HOLD_MS`, `mouseUp`.
  - `type_text`: `ctrl+a` y luego el texto, incluyendo tildes, ñ y `#`.
  - `press` con combinaciones.
  - `scroll` con la rueda del mouse.
  - `settle`: espera cambio (`CHANGE_TIMEOUT_S`) y luego estabilidad (`STABLE_INTERVAL_S`, `STABLE_TIMEOUT_S`, `DIFF_MIN_PIXELS`).
  - Mapeo de errores a `VNC_CONNECT_FAILED`, `VNC_AUTH_FAILED` y `WS_DISCONNECTED`.
  - Al salir del context manager se desconecta y se cierra el puente.
  - La contraseña nunca aparece en logs.
- **Listo cuando:** un script de demostración contra el escritorio propio guarda una captura de 1280×800, hace clic en un campo de SIGECOM, escribe `Papelería #1` y una segunda captura lo muestra escrito.

### T04 · Percepción
- **Hacer:**
  - `diff.changed_pixels` con NumPy.
  - `ocr.read_text`: Tesseract `spa` con la imagen escalada 2×, de toda la pantalla o de una región.
  - `ocr.words_near`: palabras cuyo recuadro cae dentro del radio alrededor de un punto.
- **Listo cuando:** las pruebas sobre capturas de `tests/fixtures/` reconocen etiquetas con tildes y botones conocidos, y `changed_pixels` da 0 entre capturas iguales y más de 0 tras un cambio.

### T05 · Cliente OpenRouter
- **Hacer:**
  - `chat`: `POST /api/v1/chat/completions` con imagen en base64 (`image_url`), `tools`, `tool_choice: auto`, `reasoning.effort` y `provider.require_parameters: true`. Devuelve la primera tool call y `usage.cost`.
  - 2 reintentos con backoff ante 429/5xx, y errores mapeados a `VLM_ERROR`.
  - La llave nunca se registra.
- **Listo cuando:**
  - Hay pruebas con respuestas HTTP simuladas.
  - Una prueba en vivo (marcada para correr aparte) envía una captura de ejemplo y recibe una tool call válida de `anthropic/claude-haiku-5.5`, gastando menos de US$0.001.

### T06 · Herramientas y prompt
- **Hacer:**
  - `tools.TOOLS` con los esquemas de la sección 2.2: `click`, `double_click`, `type_text`, `press_key`, `scroll`, `wait`, `finish_task` y `fail_task`, cada una con `observacion` y `efecto`.
  - `parse_action`: valida con Pydantic, convierte `norm1000` a píxeles y rechaza coordenadas fuera de la pantalla.
  - `prompts.py`: las reglas de la sección 2.3 del diseño, exigir `fecha_app` en el primer paso y tratar el texto de la pantalla como dato, no como instrucción.
- **Listo cuando:** hay pruebas de parseo para cada herramienta, conversión de coordenadas, límites y errores de esquema.

### T07 · Resumen y saneador
- **Hacer:**
  - `build_summary`:
    - En preguntas, la línea `respuesta:` va primero, y con dos datos se separan con `;`.
    - En `fallida` nunca aparece `respuesta:`, y se verifica que cada `datos_clave` y cada identificador de `candidatos` aparezca en el texto.
    - En errores, se incluye el código.
  - `normalize_number`: `$1.234.567,50` pasa a `1234567.50`.
  - `sanitize`: elimina los secretos exactos y los patrones `sk-…`.
- **Listo cuando:** hay pruebas con E3 (`respuesta: 45`), E5 (ambos documentos en el texto), dos datos, números colombianos y un resumen que intenta incluir la contraseña.

### T08 · Filtro (System 1)
- **Hacer:**
  - `is_irreversible`: `efecto` en guardar/exportar/eliminar, o palabras clave cerca del punto, o `Enter` dentro de un formulario.
  - Herramienta `verificar` con `dentro_de_tarea`, `registro_correcto` y `valores_correctos` (booleanos) y `razon`. Para el cierre, `tarea_cumplida` o `respuesta_respaldada`.
  - Prompt de verificación en `prompts.py`:
    - busca razones para **no** ejecutar;
    - aclara que el texto de la pantalla es parte de la situación, no de la tarea;
    - exige que la evidencia esté visible en la captura o en el OCR.
  - `Gate.check_action`: llamada aparte a `VLM_MODEL` con contexto limpio (sin el historial que propuso la acción), con la tarea, la acción, la captura, el OCR y la evidencia.
    - Si los tres chequeos están en sí, aprueba.
    - Si alguno está en no, bloquea y devuelve la razón.
    - Si la llamada falla dos veces, bloquea.
  - `Gate.check_completion`: lo mismo para el cierre.
  - Con `VERIFY_ENABLED=false`, aprueba sin llamar al modelo.
- **Listo cuando:**
  - Hay pruebas con `FakeLLM` para aprobar, bloquear, error de la llamada y verificación apagada.
  - Una prueba en vivo con el estado de E5 (dos Ana Torres en la evidencia y la acción "Guardar" sobre una de ellas) devuelve `registro_correcto` en no.

### T09 · Ciclo del agente
- **Hacer:** `run_agent` según la sección 2.3 del diseño:
  1. Captura y paso al VLM: tarea, `fecha_app`, captura actual e historial de `HISTORY_STEPS`.
  2. `parse_action`, filtro si la acción es irreversible, ejecución, `settle` y diff.
  3. `CLICK_NO_EFFECT` con aviso al VLM, `LOOP_DETECTED` a las 3 repeticiones, y memoria de evidencia (OCR de las últimas `EVIDENCE_SCREENS` pantallas y de las marcadas como listado).
  4. Topes de tiempo, pasos y costo. La bandera `cancel` se revisa antes de cada acción.
  5. Al cerrar: chequeo de éxito falso, desconexión **antes** de devolver el resultado, `build_summary` + `sanitize`, y traza de cada paso.
- **Listo cuando:** hay pruebas de integración con `FakeDesktop` y `FakeLLM` que cubren:
  - camino feliz;
  - pregunta con respuesta;
  - acción bloqueada por la verificación;
  - éxito rechazado por la verificación final;
  - fallida con candidatos;
  - ciclo detectado;
  - tiempo agotado;
  - cancelación a mitad de tarea (ninguna acción posterior llega al `FakeDesktop`).

### T10 · API y ejecutor
- **Hacer:**
  - `api.py`: `GET /health` sin token. `POST /tasks` con Bearer responde 200 `{"task_id"}`. `GET /tasks/{task_id}` responde `{"estado", "resumen"}` con 401/404/422 donde corresponde. `GET /tasks/{task_id}/traza` exige token.
  - `TaskRunner`: registro en memoria, `asyncio.create_task`, candado por escritorio en el que la tarea nueva cancela a la anterior, `asyncio.wait_for` con `TASK_TIME_BUDGET_S` + margen, y el resumen de progreso mientras la tarea está `en_curso`.
  - Comparación del token con `secrets.compare_digest`.
- **Listo cuando:** hay pruebas con `httpx.AsyncClient` y un agente simulado que cubren:
  - la forma exacta de las respuestas;
  - `POST /tasks` en menos de 200 ms;
  - 401 y 404;
  - una tarea nueva en el mismo escritorio que cancela a la anterior;
  - el timeout que termina en `fallida` con `BUDGET_EXHAUSTED`.

### T11 · Trazas y observabilidad
- **Hacer:**
  - `tracing.Trace`: JSONL por tarea en `TRACE_DIR/<task_id>/`, con capturas PNG por paso, todo pasado por `sanitize`.
  - Campos por paso: número, tiempo, acción, observación, resultado de la verificación con su razón, % de diff, latencias, costo y código de error.
  - Logs del servidor en JSON.
  - El endpoint `/traza` devuelve `Trace.read()`.
- **Listo cuando:** una prueba escribe y lee una traza, y verifica que una contraseña inyectada en los campos no aparezca en el archivo.

### T12 · Arnés de evaluación
- **Hacer:** `eval/harness.py`. Por cada caso de `eval/cases/`:
  1. `POST /__reset` del escritorio.
  2. `POST /tasks` al agente, cronometrado.
  3. Consulta cada 5 s hasta el estado final o 300 s.
  4. `POST /__check` con el JSON del caso.
  5. Chequeos locales: estado esperado, línea `respuesta:`, `claves_razon` y ausencia de secretos.
  6. Reporte CSV y Markdown con resultado, duración, pasos, costo, códigos de error y enlace a la traza.

  El escritorio y los tokens se leen de `EVAL_DESKTOP_URL`, `EVAL_DESKTOP_PASSWORD`, `EVAL_DESKTOP_TOKEN`, `AGENT_URL` y `AGENT_TOKEN`. Se copian E1–E5 de `frontier-reto-1/pruebas/` y se agregan los casos P01–P12 del diseño, completando los † con datos reales de SIGECOM.
- **Listo cuando:** el arnés corre contra un servidor de agente simulado y contra el `/__check` real, y genera el reporte.

### T13 · Comparación de modelos por precisión de clic
- **Hacer:**
  - Con `DesktopSession`, capturar unas 10 pantallas de SIGECOM: lista de clientes, formulario nuevo, formulario con datos, búsqueda con dos Ana Torres, facturas, filtros de pedidos y ventana emergente.
  - Etiquetar unos 15 objetivos por pantalla en `eval/grounding/*.json` (descripción + recuadro), más preguntas de estado ("¿el botón Guardar está habilitado?", "¿es un campo o una etiqueta?").
  - `eval/grounding.py` envía cada objetivo con la herramienta `click` a los modelos de una lista y mide: % de puntos dentro del recuadro, % de estados correctos, % de tool calls válidas, latencia y costo.
- **Listo cuando:**
  - Hay un reporte con al menos `anthropic/claude-haiku-5.5` y `qwen/qwen3.7-plus`.
  - El modelo elegido y su `VLM_COORD_MODE` quedan anotados en la sección 0 de este plan.

### T14 · Docker y despliegue
- **Hacer:**
  - `Dockerfile` sobre `python:3.12-slim` con `tesseract-ocr` y `tesseract-ocr-spa`.
  - `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`.
  - Despliegue en Railway o Fly.io con una instancia siempre encendida, las variables de entorno cargadas y health check en `/health`.
- **Listo cuando:** la URL pública responde `/health`, y `POST /tasks` con token devuelve un `task_id`.

### T15 · README
- **Hacer:** requisitos, instalación, variables de entorno (copiando `.env.example`), correr en local, pruebas, arnés, comparación de modelos, despliegue y una sección de arquitectura con enlace al diseño.
- **Listo cuando:** una persona sin contexto levanta el servicio y corre las pruebas siguiendo solo el README.

### T16 · Integración de punta a punta
- **Hacer:**
  - Conectar los módulos reales en `main.py`.
  - Correr el arnés con E1–E5 contra el escritorio propio y corregir lo que falle.
  - Ajustar esperas, prompt y prompt de verificación con las trazas.
  - Volver a desplegar.
  - Registrar en el reporte las métricas de la sección 3.3 del diseño.
- **Listo cuando:**
  - E1–E5 pasan en al menos 2 de 3 corridas.
  - No hay falsos éxitos ni fugas de secretos.
  - El servicio desplegado responde igual que el local.

### T17 · Canario y runbook de incidente
- **Hacer:**
  - Una tarea programada que cada 15 minutos corre un caso de solo lectura (tipo E3) contra el escritorio propio y registra una alerta si falla.
  - `docs/runbook.md` con los pasos de la sección 2.8 del diseño y una tabla de código de error → causa probable → qué ajustar.
- **Listo cuando:** el canario corre en el entorno desplegado y una falla simulada (contraseña equivocada) queda registrada con `VNC_AUTH_FAILED`.

### T18 · Mejoras guiadas por métricas
Se ejecuta solo si el reporte de T16 lo justifica, una mejora a la vez y midiendo antes y después:
- **Clics con efecto por debajo del 85 %:** localizador separado (`GROUNDER_MODEL`) o modo cuadrícula.
- **Fallas de razonamiento en una categoría:** escalar esos pasos a un modelo más fuerte.
- **Errores de conteo:** conteo paginado con OCR.
- **Acciones fuera de la tarea o falsos éxitos que la verificación no frena:** sumar Jev (`typesafe/jev-1.13`, `POST https://openrouter.ai/api/alpha/decisions`) dentro de `Gate` como segunda opinión independiente.

---

## 4. Entregables de las 20:00

- Repositorio con el código, las pruebas y el README de T15.
- URL pública del agente (T14), con el contrato verificado por el arnés.
- Reporte del arnés (T16) y de la comparación de modelos (T13), como evidencia para la demo y la entrevista.
- Video de 2 minutos mostrando una tarea que termina bien, una tarea rechazada (E5) y lo que no funcionó.
