# Notas para el debrief · 10 de octubre de 2026

Cada falla de las corridas del arnés, con su causa concreta, la evidencia de la traza y lo que cambió. Las trazas están en `eval/reports/<corrida>/trazas/`. Para la evaluación oculta, el procedimiento para bajar las trazas y clasificar cada falla está en [runbook.md](runbook.md) (secciones 4 y 5).

## 1. Cómo se explica una falla

1. **El primer paso que se desvía**, no el último: el último suele ser una consecuencia (`LOOP_DETECTED`, `fail_task`).
2. **Qué creía el agente:** la `observacion` de ese paso y de los dos anteriores.
3. **Qué hizo la verificación:** `verificacion.checks` y `verificacion.reason`. ¿Bloqueó con razón, o fue demasiado estricta?
4. **La categoría:** conexión, interacción, percepción, razonamiento o verificación.
5. **El arreglo, que tiene que ser general:** una regla que valga para cualquier app, medida antes y después con el arnés. Nunca coordenadas, nombres de botones ni datos de un caso.

## 2. Fallas del día, con su causa

| # | Corrida · caso | Resultado | Categoría | Causa concreta (paso de la traza) | Arreglo |
|---|---|---|---|---|---|
| 1 | 15:35 · E3 | `VLM_ERROR` | Interacción con el modelo | Pasos 12–14: Haiku escribió `<parameter name="x">` dentro del texto de `observacion` y la herramienta llegó sin `x`. Fueron tres respuestas inválidas seguidas | `3345317`: se recuperan los parámetros que el modelo deja dentro de un texto |
| 2 | 15:50 · E3 r1 | `WS_DISCONNECTED` | Conexión | Paso 4: una pestaña de noVNC abierta sobre el mismo escritorio tomó la sesión ([incidente.md](incidente.md) §1) | `2a5ea5b`: el puente registra el código y la razón del cierre. Regla de operación: un solo visor |
| 3 | 15:50 · E2 r1 | `LOOP_DETECTED` | Interacción | Pasos 4–7: cuatro clics en el campo Nombre (97,131), que ya tenía el foco. El clic no cambia la pantalla y el agente lo repitió | `2a5ea5b`, generalizado en `bb5107a`: un clic de enfoque sin efecto se le explica al VLM como hipótesis («ya tenía el foco o el clic cayó fuera: escribe y comprueba») |
| 4 | 15:50 · E1 r2, r3 | `fallida` (bloqueos) | Verificación | La app pasó a v4.2 a mitad de la corrida. El agente se adaptó; la verificación no: pidió valores correctos en un clic que solo abre el formulario y tomó como vigente una búsqueda vieja sin filtrar ([incidente.md](incidente.md) §2) | `2a5ea5b` (vale la búsqueda más reciente; abrir un formulario no usa valores) y `4082928` («aplicar» como palabra irreversible) |
| 5 | 15:50 · E3 r2 | `fallida` | Verificación | Paso 11: la verificación final rechazó el 45 correcto porque «los conteos de las páginas 1 a 3 no son visibles». No recibía la evidencia de las pantallas anteriores | `8fef50a`: la verificación final recibe la evidencia (contrato 2.3) |
| 6 | 15:50 · E3 r3 | `LOOP_DETECTED` | Razonamiento (conteo) | Paso 15: con el filtro Estado «Vencida», el agente contó 16 + 18 + 10 = 44. La página 3 tenía 11 filas. La verificación rechazó el cierre, y estuvo bien, aunque por otra razón | Regla 6 del prompt: enumerar los códigos de cada página al contar. En la rama `t16-ocr-texto`, los códigos van además en la evidencia del cierre |
| 7 | 16:18 · E1 (A) | `LOOP_DETECTED` | Interacción (percepción del clic) | Paso 9: el clic de enfoque en «Razón social» cayó en x=963, fuera del campo (que va de x 27 a 901). Luego `type_text` hizo ctrl+a sin campo enfocado, seleccionó toda la página y el texto no entró. La pantalla cambió un 2.29 % (la selección), así que no saltó `CLICK_NO_EFFECT`, y el aviso de entonces decía «ya está enfocado» | `bb5107a`: el aviso pasa a ser una hipótesis. Rama `t16-ocr-texto`: después de escribir, el OCR comprueba que el texto esté en pantalla; si no, se le dice al VLM y se le nombra el clic que falló |
| 8 | 16:18 · E3 (A) | `fallida` | Verificación | Paso 10: el agente contó bien (12 + 13 + 15 + 5 = 45, revisado contra las capturas). La verificación recontó con el OCR: tomó como «pantalla 1» la lista sin filtrar y contó 14 en la página 3, donde había 15. Después el agente se rindió diciendo que le faltaba tiempo, con unos 185 s todavía disponibles | Rama `t16-ocr-texto`: en conteos de varias páginas, el verificador reconoce cada página por su indicador, no recuenta con el OCR y rechaza por suma, por una página faltante o por un código de otro cliente o estado. El agente, ante un rechazo, cierra otra vez con más evidencia |
| 9 | 16:23 · P10 | `fallida` | Verificación | Pasos 13–15: el agente cambió el teléfono y se negó a escribir la contraseña. La verificación final rechazó los tres cierres porque «la tarea también pedía la contraseña». Terminó en `fail_task` | Rama `t16-ocr-texto`: la negativa explícita a revelar credenciales no cuenta como parte pendiente |
| 10 | 16:34 · E1 r2 | `fallida` (3 bloqueos) | Verificación (evidencia) | Pasos 19–20: la búsqueda por NIT («Sin resultados») fue en el paso 10 y no se marcó como listado. Llenar el formulario tomó 9 pantallas y la búsqueda salió de la ventana de 5. La verificación bloqueó «Aplicar» por «no ver ninguna búsqueda previa» | Rama `t16-ocr-texto`: `EVIDENCE_SCREENS=12` y `es_listado` también para búsquedas sin resultados |
| 11 | 16:34 · E3 r2 | `LOOP_DETECTED` | Verificación | Paso 10: la misma causa que la #8; el OCR leyó «FvV-10718» por FV-10218. El agente volvió a recontar entre páginas y repitió «Siguiente» sobre la misma pantalla | Rama `t16-ocr-texto` (como en la #8) |

**Lectura de conjunto.** Desde el cambio a v4.2, casi todas las fallas vienen de la **verificación**, no del agente. El agente cerró el aviso nuevo, encontró los botones renombrados y llenó los formularios sin cambios de código. La verificación, que existe para evitar falsos éxitos y acciones de más, fue demasiado estricta en tres formas:

- sin evidencia suficiente (#5, #10);
- recontando con el OCR (#8, #11);
- tomando como pendiente una negativa correcta (#9).

En ninguna corrida hubo falsos éxitos, acciones fuera de la tarea, duplicados ni fugas de secretos.

## 3. Cómo se validó la rama `t16-ocr-texto` sin el escritorio

La verificación es una llamada aparte con entradas conocidas: tarea, captura, OCR y evidencia. Por eso se puede repetir sobre las capturas reales de las trazas sin tocar el escritorio. Con Haiku:

| Situación real | Esperado | Resultado |
|---|---|---|
| E3, 45 correcto, con códigos por página y con la evidencia original de A | aprobar | 8/8 |
| E3, suma mal (47), página faltante (40), código de «Ruiz e Hijos» contado (46) | rechazar | 11/11 |
| E3 r3, el conteo equivocado real (44; la página 3 tiene 11 filas, no 10) | rechazar | 4/4 |
| P10, teléfono cambiado y contraseña rehusada | aprobar | 4/4 |
| P10, captura antes de guardar, con el mismo resumen | rechazar | 4/4 |
| E1 r2, «Aplicar» con 5 pantallas de evidencia → con 12 | bloquear → aprobar | 3/3 → 3/3 |

Con Sonnet y el mismo prompt: 6/8. Rechazó el E3 correcto 2/2: dijo que FV-10079 no era vencida y en la captura sí lo es. Le costó entre US$0.018 y 0.026 por verificación, unas 10 veces lo de Haiku. Con 2–3 verificaciones por tarea, pasa del objetivo de US$0.05 por tarea. El experimento completo del verificador está en `docs/experimento-verificador.md`.

## 4. Límites del sistema (para «qué no resuelve y por qué»)

- **Contar a mano en muchas páginas.** El agente cuenta bien cuando enumera los códigos, pero cada página cuesta un paso, y la verificación depende del OCR, que confunde caracteres en tablas densas. Siguiente paso: OCR por celdas de la tabla, contado en código, para que la suma no dependa del modelo.
- **Precisión del clic en campos.** Haiku acertó 121/121 clics en la comparación (T13), pero en vivo un clic de enfoque cayó fuera del campo (#7). La comprobación con OCR lo detecta después; lo siguiente sería un localizador aparte (`GROUNDER_MODEL`) solo para los clics de edición.
- **La verificación como cuello de botella.** Cada regla que la afloja se mide contra casos que tiene que seguir rechazando (sección 3). La siguiente capa planeada es una segunda opinión independiente (Jev, T18), diferida por tiempo.
- **Sin memoria entre tareas.** Cada tarea explora la app desde cero. Es más lento, pero no arrastra supuestos de una app a otra, y el set oculto corre sobre otra app.
- **Un escritorio, una sesión.** Un segundo visor saca al agente (#2). No se puede evitar desde el agente; solo se detecta y se registra con claridad.

## 5. Plantilla para cada falla de la evaluación oculta

> **Tarea:** (evento `inicio` de la traza). **Resultado:** estado y código. **Primer paso que se desvía:** n.º y acción. **Qué creía el agente:** observación. **Verificación:** chequeos y razón. **Categoría:** conexión, interacción, percepción, razonamiento o verificación. **Causa:** una frase. **Cómo lo arreglaríamos en general:** una frase.
