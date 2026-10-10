# Incidentes · 10 de octubre de 2026

Registro de lo que pasó durante las corridas del arnés de T16 (reporte `eval/reports/20261010-155005/`). Las horas son de Bogotá (UTC−5).

## 1. `WS_DISCONNECTED` en E3 · 15:52

| | |
|---|---|
| **Qué se vio** | E3 (corrida 1) terminó `fallida` con `WS_DISCONNECTED` a los 27 s, en el paso 4. La verificación aprobó un clic en el campo Cliente y, al ir a ejecutarlo, la sesión VNC ya estaba cerrada. |
| **Causa** | Una pestaña de **noVNC abierta en el navegador** del equipo, conectada al mismo escritorio. Lo confirmó el equipo; no fue una falla del agente, del puente ni del escritorio. |
| **Impacto** | Una tarea perdida (1 de 15 en la corrida). Ninguna acción quedó a medias: el agente revisa la conexión antes de enviar cada acción, así que el clic no se envió. |
| **Por qué no se supo en el momento** | El puente no registraba quién cerraba el WebSocket ni con qué código. La traza solo mostraba `WS_DISCONNECTED`. |
| **Qué cambió** | Si el que cierra es el escritorio, el puente registra el código y la razón del cierre (`Puente: el escritorio cerró el WebSocket (código …, razón …)`), commit `2a5ea5b`. |
| **Cómo evitarlo** | No tener noVNC ni otro visor abierto sobre el escritorio mientras corre el arnés o el canario. Si hace falta mirar, abrirlo después de la corrida. |

## 2. SIGECOM pasa a la versión 4.2 · 15:55

| | |
|---|---|
| **Qué se vio** | En la corrida 2 de E1, un clic en «Nuevo cliente» terminó en la pantalla de bienvenida con el aviso «Novedades de la versión 4.2». El encabezado cambió de `v3.9` a `v4.2`. |
| **Qué cambió en la app** | Un aviso de novedades al entrar, que se cierra con «Entendido». Botones con otros nombres: «Filtrar» en vez de «Buscar», «Crear cliente» en vez de «Nuevo cliente» y «Aplicar» en vez de «Guardar». La barra de acciones pasó a la derecha. Los formularios se aplican sin cerrarse. |
| **Impacto** | El agente se adaptó sin cambios: cerró el aviso, volvió a navegar y encontró los botones nuevos. Las dos tareas perdidas (E1, corridas 2 y 3) las bloqueó la verificación, que fue demasiado estricta con la interfaz nueva: <br>- pidió `valores_correctos` sobre un clic que solo abre el formulario; <br>- tomó como vigente una búsqueda vieja sin filtrar, aunque la más reciente por NIT decía «Sin resultados». |
| **Detección** | El arnés, al revisar las trazas. El canario de T17 todavía no existía. |
| **Qué cambió** | Commit `2a5ea5b`: el prompt de verificación aclara que vale la pantalla más reciente, qué cuenta como duplicado y que abrir un formulario no usa valores. Commit `4082928`: lista de palabras irreversibles ampliada, con «aplicar». |
