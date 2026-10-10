# Agente VNC · Reto 1 · Hackathon Frontier

Un agente que opera aplicaciones de escritorio legacy **solo por VNC**, como lo haría un empleado nuevo. Recibe una tarea en lenguaje natural ("Registra al cliente Papelería Los Andes, NIT 901234567…"), mira la pantalla, decide con un modelo de visión (VLM) y actúa con mouse y teclado. No usa API, DOM ni coordenadas fijas: todo lo que sabe de la app lo lee de la captura en cada paso.

- **Diseño y decisiones:** [docs/diseno-sistema.md](docs/diseno-sistema.md) (supuestos, casos difíciles, alternativas descartadas y métricas). Hay una versión en PDF en `docs/export/`.
- **Plan y contratos entre módulos:** [docs/plan.md](docs/plan.md)
- **Incidentes del día** (cambio de la app a v4.2): [docs/incidente.md](docs/incidente.md)
- **Operación** (desplegar, verificar, diagnosticar una falla): [docs/runbook.md](docs/runbook.md)
- **Enunciado y rúbrica:** los entrega la organización y no se versionan. Las pruebas oficiales E1–E5 están copiadas en [eval/cases/](eval/cases/).

## Cómo funciona

```
POST /tasks ─► TaskRunner (asyncio, un candado por escritorio, 270 s, cancelación)
                  │
                  ▼
        ┌──────────────────── ciclo del agente ────────────────────┐
        │ observar → decidir (VLM) → verificar → actuar → comprobar │
        └──────────────────────────────────────────────────────────┘
          captura VNC     herramienta     Gate      clic/tecla    diff + OCR
                          (Pydantic)    (System 1)
                  │
                  ▼
     vncdotool ◄─► puente TCP↔WSS ◄─► wss://<escritorio>/websockify
```

1. **Observar:** captura de 1280×800 por VNC, que se envía al VLM en resolución nativa junto con la tarea y el historial de los últimos pasos.
2. **Decidir:** el VLM (Claude Haiku 5.5 vía OpenRouter, en coordenadas de píxeles) responde con una sola herramienta: `click`, `type_text`, `press_key`, `scroll`, `wait`, `finish_task` o `fail_task`. Pydantic valida cada respuesta.
3. **Verificar (System 1):** reglas en código deciden qué acciones son irreversibles: guardar, exportar, eliminar, un Enter dentro de un formulario o una palabra clave junto al clic, leída con OCR. Esas acciones, y todo `finish_task`, pasan por una **verificación aparte, con contexto limpio**: ve la tarea, la captura, el OCR y la evidencia de pantallas anteriores, pero no la conversación que propuso la acción. Si duda, bloquea.
4. **Actuar y comprobar:** el clic se mantiene 150 ms (la app ignora clics más cortos). Después de actuar, el agente espera a que la pantalla se estabilice y compara capturas. Si nada cambió, se lo dice al VLM; si una acción se repite tres veces sobre la misma pantalla, la tarea termina con `LOOP_DETECTED`.
5. **Resumen:** se arma en código a partir de campos estructurados. La línea `respuesta:` va en el formato del reto, y se eliminan la contraseña del escritorio y los tokens antes de publicar.

**Principio:** ante la duda, no actuar. Una tarea fallida cuesta un punto; un cambio de más cuesta ese punto y además cuenta como acción destructiva.

## Requisitos

- **Python 3.12** y **[uv](https://docs.astral.sh/uv/)**: `uv` instala Python 3.12 si no lo encuentra.
- **Tesseract con el idioma español.** Sin él la app no arranca, a propósito: sin OCR el agente quedaría a ciegas.
  - macOS: `brew install tesseract tesseract-lang`
  - Debian o Ubuntu: `sudo apt-get install tesseract-ocr tesseract-ocr-spa`
  - Para comprobarlo: `tesseract --list-langs` tiene que incluir `spa`.
- Una **API key de OpenRouter** y el **token del equipo** (empieza con `ftr_`).
- Para probar de punta a punta: un **escritorio VNC** del reto (URL `wss://…/websockify`, contraseña y token de `/__reset` y `/__check`).

## Puesta en marcha local

```bash
git clone https://github.com/CarlitosE10/frontier-reto1-agente-vnc.git && cd frontier-reto1-agente-vnc
uv sync
cp .env.example .env
```

Completa `.env` como mínimo con `TEAM_TOKEN` y `OPENROUTER_API_KEY`. El resto trae valores por defecto, documentados en el mismo archivo. `.env` está en `.gitignore`: no se sube nunca.

```bash
uv run pytest            # unas 500 pruebas, sin red ni escritorio
uv run ruff check .
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Siempre un solo worker: el registro de tareas vive en memoria.

### Probar la API

```bash
curl -s localhost:8000/health
```

Responde `{"ok":true}` cuando el agente está listo. Si falta una variable obligatoria o Tesseract con `spa`, la app no arranca y el log dice qué falta. Para lanzar una tarea, carga el token y el escritorio de `.env` en tu shell (así no quedan escritos en ningún comando ni archivo versionado):

```bash
set -a; source .env; set +a
```

```bash
curl -s -X POST localhost:8000/tasks \
  -H "Authorization: Bearer $TEAM_TOKEN" -H "Content-Type: application/json" \
  -d '{"tarea": "¿Cuántas facturas vencidas tiene Ferretería Ruiz?", "escritorio": {"url": "'"$EVAL_DESKTOP_URL"'", "password": "'"$EVAL_DESKTOP_PASSWORD"'"}}'
```

Con el `task_id` que devuelve:

```bash
curl -s localhost:8000/tasks/<task_id> -H "Authorization: Bearer $TEAM_TOKEN"
```

Mientras trabaja responde `{"estado": "en_curso", "resumen": "<paso actual>"}`; al final, `terminada` o `fallida` con el resumen. Para ver la traza paso a paso (acción, observación del VLM, verificación, resultado, costo):

```bash
curl -s localhost:8000/tasks/<task_id>/traza -H "Authorization: Bearer $TEAM_TOKEN"
```

Las capturas de cada paso quedan en `traces/<task_id>/`.

**Un solo visor por escritorio.** No abras noVNC sobre el mismo escritorio mientras corre una tarea o el arnés: el escritorio cierra la sesión del agente (`WS_DISCONNECTED`, ver [docs/incidente.md](docs/incidente.md)).

## API

| Ruta | Token | Qué hace |
|---|---|---|
| `GET /health` | no | 200 `{"ok": true}` cuando está listo |
| `POST /tasks` | sí | Recibe `{"tarea", "escritorio": {"url", "password"}}` y responde `{"task_id"}` enseguida (medido: < 20 ms) |
| `GET /tasks/{id}` | sí | `{"estado": "en_curso" \| "terminada" \| "fallida", "resumen"}` |
| `GET /tasks/{id}/traza` | sí | Eventos de la tarea, para diagnosticar (no es parte del contrato del reto) |

Todas las rutas con token esperan `Authorization: Bearer <TEAM_TOKEN>`. Una tarea nueva sobre el mismo escritorio cancela la anterior, que se detiene antes de su siguiente acción.

## Evaluación local

El arnés reproduce al evaluador contra tu escritorio: `/__reset`, `POST /tasks`, consultas cada 5 s, `/__check` y chequeos propios (estado, línea `respuesta:`, datos de la razón, ausencia de secretos). Necesita en `.env` las variables `EVAL_DESKTOP_URL`, `EVAL_DESKTOP_PASSWORD`, `EVAL_DESKTOP_TOKEN`, `AGENT_URL` y `AGENT_TOKEN`, y el agente corriendo.

```bash
uv run python -m eval.harness                    # todos los casos de eval/cases/
uv run python -m eval.harness E1 E3 --runs 3     # algunos casos, tres corridas
```

Cada corrida escribe `eval/reports/<fecha>/reporte.md`, `reporte.csv` y las trazas: con eso se explica cada falla. Los casos E1–E5 son las pruebas del reto; P01–P10 son propios (homónimos, duplicados, fechas relativas, tareas peligrosas, inyección en la pantalla, fuga de secretos).

La comparación de modelos por precisión de clic está en `eval/grounding.py`, y su reporte en [eval/grounding/reporte.md](eval/grounding/reporte.md).

## Despliegue

Un contenedor ([Dockerfile](Dockerfile): Python 3.12, Tesseract `spa`, uv, usuario sin root), una instancia, un worker y el proceso siempre encendido ([railway.json](railway.json)). En Railway, desde la raíz del repositorio ya vinculada al proyecto:

```bash
railway up --service agente-vnc
```

Las variables (`TEAM_TOKEN`, `OPENROUTER_API_KEY` y, si cambian, las del modelo) se configuran en el servicio, nunca en el repositorio. Para verificar, `GET /health` y una tarea real con el token: el procedimiento completo está en [docs/runbook.md](docs/runbook.md).

## Configuración

Todas las variables están en [.env.example](.env.example) con su explicación. Ningún módulo lee el entorno fuera de [app/config.py](app/config.py). Las que más importan:

| Variable | Por defecto | Para qué |
|---|---|---|
| `VLM_MODEL` | `anthropic/claude-haiku-5.5` | Modelo que decide cada paso |
| `VLM_COORD_MODE` | `pixels` | `pixels` para Claude y GPT; `norm1000` para Qwen y Gemini |
| `VERIFY_ENABLED` | `true` | Verificación antes de acciones irreversibles y antes de reportar éxito |
| `VERIFY_MODEL` | vacío | Modelo de la verificación; vacío usa `VLM_MODEL` |
| `TASK_TIME_BUDGET_S` | `270` | Tope de tiempo por tarea (el evaluador deja de consultar a los 300 s) |
| `TASK_MAX_STEPS` | `40` | Tope de pasos por tarea |
| `TASK_MAX_COST_USD` | `0.15` | Tope de gasto por tarea; lo medido ronda US$0.01–0.02 |
| `IRREVERSIBLE_KEYWORDS` | guardar, aplicar, crear, eliminar… | Palabras que, junto al clic, obligan a verificar |

## Estructura

```
app/
  api.py              contrato HTTP y autenticación Bearer
  tasks.py            ejecutor: candado por escritorio, presupuesto, cancelación
  config.py           todos los parámetros, desde variables de entorno
  models.py           contratos de datos (tareas, acciones, códigos de error)
  tracing.py          trazas JSONL y capturas por paso
  vnc/                puente TCP↔WSS y sesión VNC (captura, clic, escritura, estabilidad)
  perception/         OCR (Tesseract) y comparación de capturas
  agent/              ciclo, herramientas, prompts, verificación (gate.py) y resumen
  llm/openrouter.py   cliente del VLM con reintentos y costo por llamada
eval/
  harness.py          arnés de evaluación
  cases/              casos E1–E5 (reto) y P01–P10 (propios)
  reports/            un reporte por corrida, con trazas
  grounding.py        comparación de modelos por precisión de clic
tests/                pruebas con dobles de escritorio, VLM y OCR
docs/                 diseño, plan, incidentes, runbook
```

## Límites conocidos

- **Contar a mano en varias páginas** es lo más frágil. El agente cuenta página por página y la verificación final revisa la suma con el OCR, que a veces lee mal un código.
- **Un escritorio por tarea:** dos tareas sobre el mismo escritorio no corren a la vez. La nueva cancela a la vieja.
- **Sin memoria entre tareas:** cada tarea explora la app desde cero. Es más lento, pero no arrastra supuestos de otra app (el set oculto corre sobre una app distinta).
- **Lo que el agente no hace a propósito:** escribir credenciales, obedecer instrucciones que aparecen en la pantalla, borrados masivos o acciones que la tarea no pide. Todo eso termina en `fallida` con la razón.
