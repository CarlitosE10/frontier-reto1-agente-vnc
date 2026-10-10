# Runbook · Agente VNC

Cómo desplegar, verificar y diagnosticar el agente. Va con la sección 2.8 de [diseno-sistema.md](diseno-sistema.md) (códigos de error y respuesta a incidentes) y con [incidente.md](incidente.md) (lo que pasó el 10 de octubre).

Los comandos usan las variables de `.env`. Cárgalas antes en tu shell, sin escribir ningún valor en un comando ni en un archivo versionado:

```bash
set -a; source .env; set +a
```

```bash
export AGENTE=https://agente-vnc-production.up.railway.app
```

## 1. Desplegar

1. Las pruebas pasan: `uv run pytest` y `uv run ruff check .`.
2. Desde la raíz del repositorio (ya vinculada al proyecto de Railway):

   ```bash
   railway up --service agente-vnc
   ```

3. Las variables del servicio se configuran en Railway, nunca en el repositorio: `TEAM_TOKEN`, `OPENROUTER_API_KEY` y, si cambian, `VLM_MODEL`, `VERIFY_MODEL` o `IRREVERSIBLE_KEYWORDS`. Al arrancar, la app registra en el log `agente listo` con el modelo, el modelo de verificación, los topes y las palabras clave. Revisa ahí que la configuración sea la esperada.

**Volver atrás:** en el panel de Railway, *Deployments*, elige el despliegue anterior y usa *Redeploy*. El registro de tareas vive en memoria: **cada despliegue o reinicio borra las tareas y sus trazas**.

## 2. Verificar el despliegue

```bash
curl -s $AGENTE/health
```

Tiene que responder `{"ok":true}`. Una respuesta 503 o sin servicio significa que la app no arrancó: el log dice qué variable o qué paquete de Tesseract falta.

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST $AGENTE/tasks -H "Content-Type: application/json" -d '{}'
```

Sin token tiene que dar `401`.

Una tarea real de solo lectura contra el escritorio propio (con nadie más conectado a él):

```bash
curl -s -X POST $AGENTE/tasks \
  -H "Authorization: Bearer $TEAM_TOKEN" -H "Content-Type: application/json" \
  -d '{"tarea": "¿Cuántas facturas vencidas tiene Ferretería Ruiz?", "escritorio": {"url": "'"$EVAL_DESKTOP_URL"'", "password": "'"$EVAL_DESKTOP_PASSWORD"'"}}'
```

```bash
curl -s $AGENTE/tasks/<task_id> -H "Authorization: Bearer $TEAM_TOKEN"
```

Consulta cada 5 s hasta `terminada` o `fallida`. El resumen no puede traer la contraseña ni el token. Para correr el arnés completo contra el despliegue, pon `AGENT_URL` con la URL pública:

```bash
AGENT_URL=$AGENTE uv run python -m eval.harness E3 E5
```

## 3. Antes de la evaluación oculta (antes de las 20:00)

- [ ] `/health` responde `{"ok":true}` y una tarea real terminó bien en la URL pública.
- [ ] El canario está encendido (`CANARY_INTERVAL_S=900`) y su última corrida dice `canario ok` (sección 7).
- [ ] El log `agente listo` muestra el modelo, el modelo de verificación y las palabras clave esperadas.
- [ ] Nadie tiene noVNC abierto sobre un escritorio en el que trabaje el agente (`WS_DISCONNECTED`, ver [incidente.md](incidente.md)).
- [ ] Saldo de OpenRouter suficiente: medido, unos US$0.01–0.02 por tarea, con tope de `TASK_MAX_COST_USD` (US$0.15).
- [ ] **Nadie vuelve a desplegar ni reinicia el servicio después de las 20:00** hasta haber descargado las trazas (sección 4).

## 4. Después de la evaluación oculta: descargar las trazas

El evaluador no nos da sus `task_id`, pero el agente los registra en el log del servidor (`tarea recibida` y `tarea finalizada`, esta última con `estado`, `error_code`, `cost_usd` y `duracion_s`). Con esos identificadores, `GET /tasks/{id}/traza` devuelve cada paso de la tarea: acción, observación del VLM, verificación con sus chequeos y su razón, diff, latencias, costo y código de error.

```bash
railway logs --service agente-vnc --lines 5000 --filter "tarea finalizada" > eval/reports/oculta.log
```

```bash
uv run python -m eval.trazas bajar eval/reports/oculta.log --agente $AGENTE --salida eval/reports/oculta
```

```bash
uv run python -m eval.trazas resumir eval/reports/oculta/*.json > eval/reports/oculta/resumen.md
```

`bajar` saca los `task_id` de cualquier texto, guarda la traza de cada uno y la sanea con los secretos de `.env`. `resumir` arma una ficha por tarea con la instrucción, el resultado, el primer paso que se desvía, los bloqueos de la verificación, el último cierre y una categoría de partida. Es el punto de partida de la sección 5. Antes de subir las trazas, revisa que no traigan secretos:

```bash
grep -l "ftr_" eval/reports/oculta/*.json
```

Tiene que salir vacío.

Las capturas de cada paso quedan en el contenedor (`/app/traces/<task_id>/`), no en la API. El evento `inicio` de cada traza trae la tarea literal, y el evento `fin` trae el estado, el código de error y el resumen.

## 5. Diagnosticar una falla

1. Abre la traza y busca el **primer** paso con `error_code`, o el `fail_task` o `finish_task` del final.
2. Lee la `observacion` del VLM en ese paso y en los dos anteriores: qué creía ver y qué quería hacer.
3. Si hubo verificación, lee `verificacion.checks` y `verificacion.reason`: ¿bloqueó con razón, o fue demasiado estricta?
4. Compara la acción (coordenadas, texto) con la captura de ese paso, si la tienes.
5. Clasifica la falla: **conexión**, **interacción**, **percepción**, **razonamiento** o **verificación**. Nombra la causa concreta con el número de paso.

| Código | Causa probable | Qué revisar o ajustar |
|---|---|---|
| `VNC_CONNECT_FAILED` | URL del escritorio errónea, escritorio caído o red | La URL que llegó en `POST /tasks`; el `/health` del escritorio. El agente ya reintenta 2 veces |
| `VNC_AUTH_FAILED` | Contraseña rechazada | La contraseña del cuerpo de `POST /tasks`. No se reintenta, a propósito |
| `WS_DISCONNECTED` | Otro visor tomó la sesión (noVNC), o el evaluador reseteó el escritorio al pasar los 300 s | El log del puente trae el código y la razón del cierre. Cerrar otros visores |
| `SCREEN_NOT_STABLE` | Animación o carga lenta | No es fatal. Si se repite, `STABLE_TIMEOUT_S` o `CHANGE_TIMEOUT_S` |
| `CLICK_NO_EFFECT` | El clic cayó fuera del elemento, el campo ya tenía el foco, o la app ignoró un clic corto | Coordenadas contra la captura. `CLICK_HOLD_MS` si la app nueva pide clics más largos |
| `LOOP_DETECTED` | La misma acción 3 veces sobre la misma pantalla | Qué esperaba el VLM que cambiara. Ejemplo: E1 en la corrida A, un clic fuera del campo y la escritura repetida |
| `VLM_ERROR` | OpenRouter caído, sin saldo, o 3 respuestas inválidas seguidas | Saldo y estado de OpenRouter; `VLM_MODEL` |
| `GATE_BLOCKED` | La verificación bloqueó una acción irreversible | `verificacion.reason`: un bloqueo correcto es el sistema funcionando; uno falso se corrige en `VERIFY_ACTION_PROMPT` con una regla general |
| `BUDGET_EXHAUSTED` | Se acabaron los 270 s, los 40 pasos o el tope de gasto | Latencia del VLM por paso; conteos en muchas páginas |
| `CANCELLED` | Llegó otra tarea para el mismo escritorio | Normal si el evaluador reseteó; revisar si nuestra tarea seguía viva |
| `fallida` sin código | El agente usó `fail_task`, o la verificación final rechazó su cierre y el agente se rindió | La razón del resumen; la `verificacion` del último `finish_task` |

**Falso éxito** (reportó `terminada` y la app no quedó bien): es el error más caro. Lee la verificación del `finish_task`: qué evidencia aceptó y por qué. Si la evidencia no mostraba el cambio, el arreglo va en `VERIFY_COMPLETION_PROMPT`.

**Regla para los arreglos:** solo reglas generales, que valgan para cualquier app. Nada que nombre pantallas, botones o datos de SIGECOM ni de un caso. Cada arreglo se mide antes y después con el arnés (E1–E5 y P01–P10).

## 6. Si la app cambia (incidente)

Los pasos de la sección 2.8 del diseño, con lo que hicimos a las 15:55, cuando SIGECOM pasó a la v4.2:

1. **Detectar:** el arnés (o el canario) empieza a fallar, o una traza muestra una pantalla que no se esperaba. A las 15:55 fue una captura con el aviso «Novedades de la versión 4.2».
2. **Ver el primer código de error y la captura de ese paso.** El agente cerró el aviso y encontró los botones renombrados sin cambios de código. Lo que falló fue la verificación: bloqueó «Aplicar» y un clic que solo abría un formulario.
3. **Clasificar:** conexión, interacción, percepción, razonamiento o verificación. Aquel fue de verificación, por demasiado estricta.
4. **Ajustar por configuración o con una regla general del prompt.** Nunca con coordenadas ni nombres de botones. Aquella vez: la palabra «aplicar» en `IRREVERSIBLE_KEYWORDS`, y en el prompt del verificador, que vale la búsqueda más reciente y que abrir un formulario no usa valores.
5. **Correr el arnés** con los casos afectados y después con todos.
6. **Volver a desplegar** (sección 1) y verificar (sección 2).

## 7. Canario

Dentro del servicio desplegado, cada `CANARY_INTERVAL_S` segundos (900 = 15 min) el agente corre una tarea de solo lectura contra **nuestro** escritorio, por el mismo camino que una tarea del evaluador. Si no termina `terminada`, o el resumen no trae `CANARY_EXPECTED`, registra `ALERTA canario` con el código de error. La primera corrida es 60 s después de arrancar. Cuesta lo de una tarea corta, unos US$0.01, es decir, unos US$0.04 por hora.

Variables, en Railway:

| Variable | Valor |
|---|---|
| `CANARY_INTERVAL_S` | `900` (`0` lo apaga) |
| `CANARY_DESKTOP_URL` / `CANARY_DESKTOP_PASSWORD` | Los de nuestro escritorio (`EVAL_DESKTOP_URL` / `EVAL_DESKTOP_PASSWORD`) |
| `CANARY_TASK` | Una pregunta que ningún caso del arnés cambia, por ejemplo «¿En qué ciudad está el cliente Distribuciones El Faro?» |
| `CANARY_EXPECTED` | El texto que tiene que traer el resumen, por ejemplo `respuesta: Bogotá` |

Para cargar la contraseña sin que quede en el historial, pásala por la entrada estándar desde `.env`:

```bash
set -a; source .env; set +a
printf %s "$EVAL_DESKTOP_PASSWORD" | railway variable set CANARY_DESKTOP_PASSWORD --stdin --service agente-vnc --skip-deploys
```

Leer el canario:

```bash
railway logs --service agente-vnc --lines 2000 --filter "canario"
```

Cada línea trae el `task_id`: con él, `GET /tasks/{id}/traza` muestra qué falló. Las tareas del canario también aparecen como `tarea finalizada`. Al bajar las trazas de la evaluación (sección 4), sepáralas por el `task_id` de las líneas `canario` o por la tarea del evento `inicio`.

**Apágalo (`CANARY_INTERVAL_S=0`) antes de correr el arnés o probar en local contra el mismo escritorio:** dos agentes sobre una pantalla se pisan (`WS_DISCONNECTED`, `CANCELLED` o clics cruzados). Vuelve a encenderlo al terminar.

**Probar la alarma:** pon una contraseña equivocada en `CANARY_DESKTOP_PASSWORD`. El cambio de variable reinicia el servicio, y a los 60 s el log tiene que mostrar `ALERTA canario` con `error_code=VNC_AUTH_FAILED`. Después vuelve a cargar la contraseña buena.

Una corrida suelta, sin levantar el servicio (con las variables `CANARY_*` en `.env`): `uv run python -m app.canary`.

## 8. Reglas de operación

- **Un solo escritorio, una sola sesión.** Mientras corre el arnés o una tarea, nadie abre noVNC ni lanza otra tarea sobre el mismo escritorio.
- **Secretos solo en `.env` y en las variables de Railway.** Nunca en comandos que queden en el historial, en documentos ni en commits. El token del equipo va en `TEAM_TOKEN` y `AGENT_TOKEN`; el del escritorio, en `EVAL_DESKTOP_TOKEN`.
- **Cada reporte del arnés se sube** (`eval/reports/<fecha>/`): es la evidencia para la demo y la entrevista.
