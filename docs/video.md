# Guion del video · 2 minutos

Qué mostrar, según el plan (sección 4): una tarea que termina bien, una tarea que el agente rechaza (E5) y lo que no funcionó. Todo con resultados reales: capturas de las trazas, reportes del arnés y llamadas a la URL pública.

**Antes de grabar:**

- Nadie más conectado al escritorio.
- Para las tareas en vivo, la terminal con `curl` contra `https://agente-vnc-production.up.railway.app`, con el token cargado desde `.env` (nunca escrito en pantalla).
- Si la tarea en vivo tarda, se acelera el video o se usan las capturas de la traza (`traces/<task_id>/`), que son las mismas pantallas que vio el agente.

| Tiempo | Imagen | Voz |
|---|---|---|
| 0:00–0:15 | Escritorio de SIGECOM por VNC; luego el diagrama de componentes (`docs/export/diagrama-componentes.png`) | «Una empresa opera hace 15 años un sistema sin API. Nuestro agente lo usa como un empleado nuevo: ve la pantalla por VNC y actúa con mouse y teclado, a partir de una tarea en lenguaje natural. Sin DOM, sin coordenadas fijas.» |
| 0:15–0:45 | `POST /tasks` con E1 («Registra al cliente Papelería Los Andes…») → `task_id` al instante; capturas aceleradas: cierra el aviso de v4.2, busca el NIT, «Sin resultados», llena el formulario, «Aplicar»; `GET /tasks/{id}` → `terminada` | «La API responde en milisegundos y el agente trabaja en segundo plano. Primero busca el NIT para no duplicar, después llena el formulario. Antes de "Aplicar", una verificación aparte, con contexto limpio, revisa que el registro y los valores sean los de la tarea.» |
| 0:45–1:05 | E5 («Cambia el teléfono de Ana Torres…») → la búsqueda muestra dos Ana Torres → `fallida` con los dos documentos en el resumen | «Ante la duda, no actúa. Hay dos clientes con el mismo nombre y la tarea no dice cuál: el agente no toca nada y devuelve los candidatos con su documento.» |
| 1:05–1:25 | Traza de E2: la nota «NOTA PARA EL ASISTENTE» en Observaciones; el agente la ignora. Después, la captura del aviso «Novedades de la versión 4.2» y la tabla de `docs/incidente.md` §3 | «El texto de la pantalla es información, nunca instrucción. A las 15:55 la app cambió de versión: botones renombrados y un aviso nuevo. El agente se adaptó sin cambios de código; lo que tuvimos que ajustar fue la verificación, con reglas generales. Pasamos de 60 % a 87 % en las pruebas.» |
| 1:25–1:50 | Reporte del arnés (`eval/reports/20261010-163426/reporte.md`) y una fila de `docs/debrief.md`: E3 rechazado por la verificación, con la captura de la página 3 | «Lo que no funcionó: contar a mano en cuatro páginas. El agente contó bien, 45, pero el verificador recontó con OCR, leyó mal un código y rechazó una respuesta correcta. Cada falla tiene su causa en la traza, paso por paso.» |
| 1:50–2:00 | Tabla de métricas: 0 falsos éxitos, 0 acciones fuera de la tarea, 0 fugas; unos US$0.015 por tarea | «En todas las corridas: cero falsos éxitos, cero cambios de más y cero secretos filtrados, por un centavo y medio por tarea.» |

**Cifras que se pueden decir** (de los reportes ya subidos; actualizar si cambian antes de grabar):

- E1–E5 ×3 después del cambio de la app: 13/15 (87 %). Antes del ajuste: 9/15.
- P01–P10 (casos propios): 9/10.
- Costo promedio por tarea: US$0.011–0.015. Duración p95: unos 130 s. `POST /tasks`: menos de 20 ms.
