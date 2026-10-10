# Comparación de modelos por precisión de clic (T13)

10/10/2026 · `anthropic/claude-haiku-5.5` contra `qwen/qwen3.7-plus`, sobre 10 capturas reales de SIGECOM.

## Decisión

**`VLM_MODEL=anthropic/claude-haiku-5.5` con `VLM_COORD_MODE=pixels`.** Queda anotado en la sección 0 de `docs/plan.md`.

| | Haiku 5.5 (`pixels`) | Qwen3.7 Plus (`norm1000`) |
|---|---|---|
| Clics dentro del recuadro | **121/121 (100 %)** | 67/121 (55 %) |
| Tool calls válidas | **141/141** | 121/141 (19 con el punto en `x` como lista) |
| Preguntas de estado | 20/20 | 20/20 |
| Latencia p50 / p95 | **2.5 s / 4.1 s** | 5.2 s / 9.2 s |
| Costo por llamada | **US$0.00034** | US$0.00065 |

Haiku gana en todo lo que se midió. El umbral de la sección 3.4 del diseño (cambiar a Qwen si lo favorece la comparación) no se cumple, y tampoco hace falta el respaldo de cuadrícula (D3), que se activa con menos de 85 % de clics con efecto.

**Qwen3.7 Plus usa la escala 0–1000, no píxeles.** Si alguna vez se usa, tiene que ir con `VLM_COORD_MODE=norm1000`.

## Qué se midió

- **Capturas.** Las 10 de `tests/fixtures/sigecom/`, de 1280×800, tomadas con `DesktopSession` sin guardar ni exportar nada:
  - lista de clientes, búsqueda con las dos Ana Torres, formulario nuevo, formulario con datos y facturas;
  - el menú Comercial con el submenú Ventas abierto;
  - pedidos filtrados como en E4 y pedidos con la lista de Estado desplegada;
  - un formulario con error de validación;
  - la ventana emergente «Descartar cambios».
- **Objetivos.** 121 en total, de 8 a 15 por pantalla, en `eval/grounding/<pantalla>.json`. Cada uno trae una descripción como la escribiría el agente y un recuadro en píxeles (bordes incluidos). Mezclan tres tipos:
  - controles nombrados por su texto ("el botón Buscar");
  - elementos que hay que ubicar razonando sobre la tabla ("el código del cliente Almacén Castro Central", "la fecha de vencimiento de la factura de Ferretería Ruiz por 450.000");
  - elementos en capas: menús, una lista desplegada y el diálogo.
- **Recuadros.** Se sacaron de los píxeles, no a ojo:
  - en campos, botones, celdas y opciones de menú, la región del color de fondo del control;
  - en enlaces y rótulos, la caja de la tinta del texto con 2 px de margen;
  - en la barra de menús, el texto con 12 px a cada lado, que es lo que se resalta al pasar el mouse.

  Todos se revisaron dibujados sobre la captura.
- **Preguntas de estado.** 20 en total, 2 por pantalla, con opciones cerradas. Por ejemplo: "¿el botón Anterior está habilitado?", "«Razón social o nombre *», ¿es un campo editable o una etiqueta?", "¿qué campo muestra el mensaje Dato inválido?".
- **Llamada.** Una por objetivo y por modelo, con la captura en resolución nativa y «Haz clic en <descripción>. Apunta al centro del elemento.».
  - Herramientas: la `click` del agente (`app.agent.tools.TOOLS`) para los clics y `responder` con las opciones para los estados.
  - Prompt del sistema: corto (tamaño de pantalla y el mismo texto de coordenadas que lee el agente), para que todo quepa en el presupuesto.
  - Parámetros: los del cliente del agente, con `reasoning.effort=low` y `provider.require_parameters`.
- **Criterio.** Un clic acierta si `parse_action` acepta la tool call, como haría el ciclo, y el punto, ya convertido a píxeles, cae dentro del recuadro.

## Escala de coordenadas de Qwen

En la primera captura (`clientes-lista`, 15 objetivos) se corrió Qwen dos veces: con el prompt que pide píxeles y con el que pide 0–1000. Para cada punto se revisó si acierta leído en una escala o en la otra.

- **Con el prompt en píxeles,** Qwen mezcla escalas. 8 de 15 puntos solo aciertan leídos en 0–1000; por ejemplo, el campo Nombre en (83, 174), que en 0–1000 es (106, 139). 3 de esos 8 llegaron como lista en `x`, y por eso la tabla cuenta 5. Otros 5 aciertan como píxeles. Ninguna lectura sirve: 33 % de aciertos.
- **Con el prompt en 0–1000,** los puntos son coherentes. En las 10 pantallas, la recta entre lo que devuelve Qwen y el centro de cada objetivo da `x_px ≈ 1.25·x − 5` y `y_px ≈ 0.78·y + 14`. La conversión esperada es ×1.28 y ×0.80, y la mediana del error es de 5–6 px. La conversión de `parse_action` es correcta, y los fallos de Qwen no son de escala.

## Resultados

<!-- tablas -->
297 llamadas en total, US$0.1486 de gasto.

| Modelo | Escala | Clics | Aciertos | Aciertos leyendo la otra escala | Tool calls válidas | Distancia mediana de los fallos | Estados correctos | Latencia p50 / p95 | Costo | Costo por llamada |
|---|---|---|---|---|---|---|---|---|---|---|
| `anthropic/claude-haiku-5.5` | `pixels` | 121 | 100% | 4% | 100% | — | 100% (20) | 2.5 s / 4.1 s | US$0.0486 | US$0.00034 |
| `qwen/qwen3.7-plus` | `pixels` | 15 | 33% | 33% | 80% | 73 px | — (0) | 5.2 s / 6.8 s | US$0.0086 | US$0.00057 |
| `qwen/qwen3.7-plus` | `norm1000` | 121 | 55% | 15% | 86% | 32 px | 100% (20) | 5.2 s / 9.2 s | US$0.0914 | US$0.00065 |

Aciertos de clic por pantalla:

| Pantalla | `anthropic/claude-haiku-5.5` (pixels) | `qwen/qwen3.7-plus` (pixels) | `qwen/qwen3.7-plus` (norm1000) |
|---|---|---|---|
| `cliente-cl-0005` | 12/12 | — | 8/12 |
| `cliente-nuevo-invalido` | 11/11 | — | 8/11 |
| `cliente-nuevo` | 12/12 | — | 10/12 |
| `clientes-busqueda-ana-torres` | 13/13 | — | 7/13 |
| `clientes-lista` | 15/15 | 5/15 | 8/15 |
| `dialogo-descartar-cambios` | 8/8 | — | 5/8 |
| `facturas-lista` | 13/13 | — | 4/13 |
| `menu-comercial-ventas` | 11/11 | — | 3/11 |
| `pedidos-estado-desplegado` | 12/12 | — | 6/12 |
| `pedidos-filtrados` | 14/14 | — | 8/14 |

Fallos: clics fuera del recuadro, tool calls inválidas y estados incorrectos.

| Modelo | Pantalla | Objetivo o pregunta | Qué pasó |
|---|---|---|---|
| `qwen/qwen3.7-plus` (pixels) | `clientes-lista` | el campo de texto Nombre del filtro de búsqueda | (83, 174) a 34 px de [24, 122, 171, 140] |
| `qwen/qwen3.7-plus` (norm1000) | `clientes-lista` | el campo de texto Nombre del filtro de búsqueda | (128, 92) a 30 px de [24, 122, 171, 140] |
| `qwen/qwen3.7-plus` (pixels) | `clientes-lista` | el desplegable Ciudad del filtro | (330, 127) a 18 px de [348, 122, 495, 140] |
| `qwen/qwen3.7-plus` (norm1000) | `clientes-lista` | el desplegable Ciudad del filtro | (429, 110) a 12 px de [348, 122, 495, 140] |
| `qwen/qwen3.7-plus` (pixels) | `clientes-lista` | el botón Limpiar | inválida: x debe ser un número, llegó [487, 169] |
| `qwen/qwen3.7-plus` (norm1000) | `clientes-lista` | el botón Buscar | inválida: x debe ser un número, llegó [427, 169] |
| `qwen/qwen3.7-plus` (norm1000) | `clientes-lista` | el botón Limpiar | inválida: x debe ser un número, llegó [486, 171] |
| `qwen/qwen3.7-plus` (pixels) | `clientes-lista` | el botón Nuevo cliente | (65, 235) a 40 px de [15, 175, 127, 195] |
| `qwen/qwen3.7-plus` (pixels) | `clientes-lista` | el botón Exportar | inválida: x debe ser un número, llegó [152, 234] |
| `qwen/qwen3.7-plus` (pixels) | `clientes-lista` | el enlace del código CL-0080 | (38, 433) a 73 px de [19, 346, 76, 360] |
| `qwen/qwen3.7-plus` (norm1000) | `clientes-lista` | el enlace del código CL-0080 | (51, 270) a 76 px de [19, 346, 76, 360] |
| `qwen/qwen3.7-plus` (pixels) | `clientes-lista` | el código del cliente Almacén Castro Central | inválida: x debe ser un número, llegó [39, 763] |
| `qwen/qwen3.7-plus` (pixels) | `clientes-lista` | la celda con el teléfono de Abarrotes Ramírez Ltda. | (790, 500) a 168 px de [930, 387, 1128, 408] |
| `qwen/qwen3.7-plus` (pixels) | `clientes-lista` | la celda de la ciudad del cliente CL-0111 | (640, 645) a 74 px de [714, 617, 928, 638] |
| `qwen/qwen3.7-plus` (pixels) | `clientes-lista` | el encabezado de la columna Teléfono | (797, 269) a 140 px de [930, 204, 1128, 224] |
| `qwen/qwen3.7-plus` (norm1000) | `clientes-lista` | el botón Siguiente de la paginación | (211, 684) a 9 px de [165, 693, 250, 713] |
| `qwen/qwen3.7-plus` (norm1000) | `clientes-lista` | el menú Cartera de la barra de menús | (282, 46) a 42 px de [168, 35, 240, 61] |
| `qwen/qwen3.7-plus` (norm1000) | `cliente-cl-0005` | el campo Razón social o nombre, con el valor Ana Torres | (461, 120) a 28 px de [28, 148, 899, 168] |
| `qwen/qwen3.7-plus` (norm1000) | `cliente-cl-0005` | el desplegable Ciudad, que muestra Bogotá | (184, 305) a 47 px de [28, 236, 450, 258] |
| `qwen/qwen3.7-plus` (norm1000) | `cliente-cl-0005` | el campo NIT | (241, 272) a 60 px de [28, 192, 450, 212] |
| `qwen/qwen3.7-plus` (norm1000) | `cliente-cl-0005` | el botón Volver | (182, 388) a 6 px de [113, 388, 176, 408] |
| `qwen/qwen3.7-plus` (norm1000) | `cliente-nuevo-invalido` | el desplegable Ciudad, marcado con error | (237, 272) a 36 px de [28, 214, 450, 236] |
| `qwen/qwen3.7-plus` (norm1000) | `cliente-nuevo-invalido` | el campo Teléfono | (870, 136) a 34 px de [477, 170, 899, 190] |
| `qwen/qwen3.7-plus` (norm1000) | `cliente-nuevo-invalido` | el botón Volver | (186, 388) a 10 px de [113, 379, 176, 399] |
| `qwen/qwen3.7-plus` (norm1000) | `cliente-nuevo` | el campo NIT | (294, 136) a 34 px de [28, 170, 450, 190] |
| `qwen/qwen3.7-plus` (norm1000) | `cliente-nuevo` | el botón Guardar | (83, 616) a 230 px de [27, 365, 105, 386] |
| `qwen/qwen3.7-plus` (norm1000) | `clientes-busqueda-ana-torres` | el enlace CL-0031 de la Ana Torres de Cali | (51, 252) a 2 px de [19, 254, 76, 268] |
| `qwen/qwen3.7-plus` (norm1000) | `clientes-busqueda-ana-torres` | el campo Nombre del filtro, que contiene «Ana Torres» | (96, 104) a 18 px de [24, 122, 171, 140] |
| `qwen/qwen3.7-plus` (norm1000) | `clientes-busqueda-ana-torres` | el campo NIT del filtro de búsqueda | inválida: x debe ser un número, llegó [202, 127] |
| `qwen/qwen3.7-plus` (norm1000) | `clientes-busqueda-ana-torres` | el encabezado de la columna NIT de la tabla | inválida: x debe ser un número, llegó [514, 262] |
| `qwen/qwen3.7-plus` (norm1000) | `clientes-busqueda-ana-torres` | la celda con el teléfono de la Ana Torres de Cali | (998, 208) a 41 px de [908, 249, 1129, 270] |
| `qwen/qwen3.7-plus` (norm1000) | `clientes-busqueda-ana-torres` | el menú Comercial de la barra de menús | inválida: x debe ser un número, llegó [93, 56] |
| `qwen/qwen3.7-plus` (norm1000) | `dialogo-descartar-cambios` | el botón No del diálogo | (1018, 442) a 203 px de [774, 436, 815, 456] |
| `qwen/qwen3.7-plus` (norm1000) | `dialogo-descartar-cambios` | la barra de título del diálogo «Descartar cambios» | (819, 276) a 58 px de [451, 334, 828, 360] |
| `qwen/qwen3.7-plus` (norm1000) | `dialogo-descartar-cambios` | el campo Razón social o nombre del formulario, detrás del diálogo | (467, 104) a 22 px de [28, 126, 899, 146] |
| `qwen/qwen3.7-plus` (norm1000) | `facturas-lista` | el campo Cliente del filtro | (102, 96) a 26 px de [24, 122, 171, 140] |
| `qwen/qwen3.7-plus` (norm1000) | `facturas-lista` | el desplegable Estado del filtro | (266, 104) a 18 px de [186, 122, 333, 140] |
| `qwen/qwen3.7-plus` (norm1000) | `facturas-lista` | el botón Buscar | (474, 100) a 61 px de [347, 119, 416, 140] |
| `qwen/qwen3.7-plus` (norm1000) | `facturas-lista` | el botón Exportar | (77, 132) a 24 px de [15, 156, 94, 176] |
| `qwen/qwen3.7-plus` (norm1000) | `facturas-lista` | el enlace de la factura FV-10107 | (51, 220) a 61 px de [19, 281, 84, 295] |
| `qwen/qwen3.7-plus` (norm1000) | `facturas-lista` | la celda Valor de la factura FV-10080 | (986, 316) a 75 px de [950, 391, 1107, 412] |
| `qwen/qwen3.7-plus` (norm1000) | `facturas-lista` | la fecha de vencimiento de la factura de Ferretería Ruiz por 450.000 | inválida: x debe ser un número, llegó [668, 284] |
| `qwen/qwen3.7-plus` (norm1000) | `facturas-lista` | el botón Siguiente de la paginación | (218, 564) a 110 px de [165, 674, 250, 694] |
| `qwen/qwen3.7-plus` (norm1000) | `facturas-lista` | el menú Herramientas de la barra de menús | (371, 46) a 19 px de [241, 35, 352, 61] |
| `qwen/qwen3.7-plus` (norm1000) | `menu-comercial-ventas` | la opción Pedidos del submenú Ventas | inválida: x debe ser un número, llegó [242, 138] |
| `qwen/qwen3.7-plus` (norm1000) | `menu-comercial-ventas` | la opción Maestros del menú Comercial | inválida: x debe ser un número, llegó [107, 97] |
| `qwen/qwen3.7-plus` (norm1000) | `menu-comercial-ventas` | la opción Ventas del menú Comercial | (192, 80) a 10 px de [80, 90, 287, 116] |
| `qwen/qwen3.7-plus` (norm1000) | `menu-comercial-ventas` | el menú Cartera de la barra de menús | (294, 50) a 54 px de [168, 35, 240, 61] |
| `qwen/qwen3.7-plus` (norm1000) | `menu-comercial-ventas` | el botón Limpiar | inválida: x debe ser un número, llegó [362, 176] |
| `qwen/qwen3.7-plus` (norm1000) | `menu-comercial-ventas` | el enlace de la factura FV-10159 | (58, 184) a 28 px de [19, 212, 84, 226] |
| `qwen/qwen3.7-plus` (norm1000) | `menu-comercial-ventas` | el desplegable Estado del filtro de facturas | inválida: x debe ser un número, llegó [210, 140] |
| `qwen/qwen3.7-plus` (norm1000) | `menu-comercial-ventas` | el campo Cliente del filtro de facturas | inválida: x debe ser un número, llegó [85, 187] |
| `qwen/qwen3.7-plus` (norm1000) | `pedidos-estado-desplegado` | la opción Entregado de la lista desplegada | inválida: x debe ser un número, llegó [209, 278] |
| `qwen/qwen3.7-plus` (norm1000) | `pedidos-estado-desplegado` | la opción Anulado de la lista desplegada | inválida: x debe ser un número, llegó [180, 289] |
| `qwen/qwen3.7-plus` (norm1000) | `pedidos-estado-desplegado` | la opción Confirmado de la lista desplegada | inválida: x debe ser un número, llegó [209, 250] |
| `qwen/qwen3.7-plus` (norm1000) | `pedidos-estado-desplegado` | la opción Borrador de la lista desplegada | inválida: x debe ser un número, llegó [211, 174] |
| `qwen/qwen3.7-plus` (norm1000) | `pedidos-estado-desplegado` | el código del pedido de Distribuciones El Faro | inválida: x debe ser un número, llegó [40, 631] |
| `qwen/qwen3.7-plus` (norm1000) | `pedidos-estado-desplegado` | la celda Estado del pedido PD-0233 | (998, 314) a 31 px de [893, 345, 1087, 366] |
| `qwen/qwen3.7-plus` (norm1000) | `pedidos-filtrados` | el desplegable Estado, que muestra Entregado | (275, 108) a 14 px de [186, 122, 333, 140] |
| `qwen/qwen3.7-plus` (norm1000) | `pedidos-filtrados` | el campo Fecha hasta | inválida: x debe ser un número, llegó [456, 162] |
| `qwen/qwen3.7-plus` (norm1000) | `pedidos-filtrados` | el enlace del pedido PD-0141 | inválida: x debe ser un número, llegó [50, 340] |
| `qwen/qwen3.7-plus` (norm1000) | `pedidos-filtrados` | la celda Total del pedido PD-0064 | (1139, 384) a 53 px de [1083, 437, 1263, 458] |
| `qwen/qwen3.7-plus` (norm1000) | `pedidos-filtrados` | la fecha del pedido de Miscelánea Vargas S.A.S. | inválida: x debe ser un número, llegó [620, 681] |
| `qwen/qwen3.7-plus` (norm1000) | `pedidos-filtrados` | el campo Fecha desde | inválida: herramienta None en vez de click |
<!-- /tablas -->

## Lectura

- **Haiku 5.5** acertó los 121 clics y apuntó casi siempre al centro: la mediana de la distancia al centro del recuadro es 0.5 px, y ningún punto quedó a menos de 6 px del borde. Acertó también los objetivos que exigen leer la tabla, las opciones de la lista desplegada y los botones del diálogo.
- **Qwen3.7 Plus** falla de cuatro maneras:
  - hace clic en la etiqueta que está sobre un campo en vez del campo (Nombre, Cliente, Estado, Ciudad);
  - elige la fila o el elemento vecino en tablas y menús (Herramientas en vez de Cartera, la factura de otra fila);
  - a veces cae lejos (Guardar a 230 px, el botón No del diálogo a 203 px);
  - en 19 de 121 clics manda el punto entero en `x` (`"x": [427, 169]`), que `parse_action` rechaza.

  Aun aceptando ese formato, llegaría a 64 %. Además tarda el doble y cuesta casi el doble por llamada.
- **Las preguntas de estado no separan a los modelos:** los dos contestan 20/20. Sirven como piso, no para decidir.

## Límites

- **Una corrida por modelo,** sin fijar temperatura. Con 121 objetivos, el 100 % de Haiku deja un intervalo de confianza del 95 % de aproximadamente 97–100 %.
- **Prompt corto.** No es el prompt completo del agente ni un ciclo real. La métrica que lo confirma en operación es "clics con efecto" de las trazas (T16, objetivo ≥ 90 %).
- **Una sola app.** La evaluación usa otra app. SIGECOM tiene una interfaz web limpia, con texto de 12–14 px; una app con íconos sin texto o fuentes más pequeñas puede bajar la precisión.
- **Recuadros con criterio.** En la barra de menús, el margen es un criterio propio (12 px). Ningún acierto de Haiku depende de él: todos sus clics en la barra caen sobre el texto del menú. En Qwen, 3 fallos caen en el menú vecino y 1 acierto depende del margen.

## Gasto

US$0.1486 de un tope de US$0.30: Haiku US$0.0486 y Qwen US$0.1000, incluida la sonda de escala. Cada llamada queda en `eval/grounding/resultados.jsonl`.

## Cómo reproducir

```bash
# Comparación completa (lo que ya está en resultados.jsonl no se repite ni se paga dos veces)
uv run python -m eval.grounding --modelo anthropic/claude-haiku-5.5=pixels \
    --modelo qwen/qwen3.7-plus=norm1000 --max-costo 0.30

# Sonda de escala en la primera captura
uv run python -m eval.grounding --modelo qwen/qwen3.7-plus=pixels \
    --modelo qwen/qwen3.7-plus=norm1000 --pantalla clientes-lista --solo-clics

# Rehacer las tablas de este reporte sin llamar a los modelos
uv run python -m eval.grounding --solo-reporte
```
