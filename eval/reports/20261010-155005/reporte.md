# Reporte del arnés · 2026-10-10 15:50

- **Agente:** http://localhost:8000
- **Reset del escritorio:** sí
- **Casos:** 5 · corridas: 3

## Métricas

| Métrica | Valor | Objetivo |
|---|---|---|
| Éxito de punta a punta | 9/15 (60%) | ≥ 80 % |
| Falsos éxitos | 0 | 0 |
| Acciones fuera de la tarea | 0 | 0 |
| Registros duplicados | 0 | 0 |
| Formato de respuesta | 3/6 (50%) | 100 % |
| Fugas de secretos | 0 | 0 |
| Latencia de POST /tasks (p99 / máx.) | 16 ms / 16 ms | < 200 ms (límite: 2 s) |
| Duración por tarea (p95) | 170.2 s | < 240 s |
| Pasos por tarea (p95) | 28 | < 30 |
| Costo por tarea (promedio / máx.) | US$0.0144 / US$0.0312 | ≤ US$0.05 (tope: US$0.15) |
| Estabilidad entre corridas | 3/5 (60%) | ≥ 90 % |

## Resultados

| Caso | Corrida | Resultado | Estado esperado → obtenido | `__check` | `respuesta:` | Claves | Fugas | POST | Duración | Pasos | Costo | Errores | Traza |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E1 | 1 | **PASA** | terminada → terminada | sí | — | — | 0 | 16 ms | 95.2 s | 19 | US$0.0178 | CLICK_NO_EFFECT | [traza](trazas/E1-r1.json) |
| E2 | 1 | **FALLA** | terminada → fallida | no | — | — | 0 | 5 ms | 35.1 s | 7 | US$0.0059 | CLICK_NO_EFFECT LOOP_DETECTED | [traza](trazas/E2-r1.json) |
| E3 | 1 | **FALLA** | terminada → fallida | sí | no | — | 0 | 4 ms | 30.1 s | 4 | US$0.0042 | CLICK_NO_EFFECT WS_DISCONNECTED | [traza](trazas/E3-r1.json) |
| E4 | 1 | **PASA** | terminada → terminada | sí | — | — | 0 | 3 ms | 80.1 s | 13 | US$0.0136 | CLICK_NO_EFFECT | [traza](trazas/E4-r1.json) |
| E5 | 1 | **PASA** | fallida → fallida | sí | sí | sí | 0 | 5 ms | 40.1 s | 9 | US$0.0077 | CLICK_NO_EFFECT | [traza](trazas/E5-r1.json) |
| E1 | 2 | **FALLA** | terminada → fallida | no | — | — | 0 | 4 ms | 170.2 s | 28 | US$0.0312 | GATE_BLOCKED | [traza](trazas/E1-r2.json) |
| E2 | 2 | **PASA** | terminada → terminada | sí | — | — | 0 | 3 ms | 75.1 s | 13 | US$0.0129 | CLICK_NO_EFFECT | [traza](trazas/E2-r2.json) |
| E3 | 2 | **FALLA** | terminada → fallida | sí | no | — | 0 | 2 ms | 170.2 s | 22 | US$0.0266 | CLICK_NO_EFFECT | [traza](trazas/E3-r2.json) |
| E4 | 2 | **PASA** | terminada → terminada | sí | — | — | 0 | 3 ms | 80.1 s | 13 | US$0.0136 | — | [traza](trazas/E4-r2.json) |
| E5 | 2 | **PASA** | fallida → fallida | sí | sí | sí | 0 | 4 ms | 45.1 s | 9 | US$0.0077 | CLICK_NO_EFFECT | [traza](trazas/E5-r2.json) |
| E1 | 3 | **FALLA** | terminada → fallida | no | — | — | 0 | 1 ms | 115.2 s | 22 | US$0.0217 | CLICK_NO_EFFECT GATE_BLOCKED | [traza](trazas/E1-r3.json) |
| E2 | 3 | **PASA** | terminada → terminada | sí | — | — | 0 | 3 ms | 70.1 s | 13 | US$0.0128 | — | [traza](trazas/E2-r3.json) |
| E3 | 3 | **FALLA** | terminada → fallida | sí | no | — | 0 | 4 ms | 120.2 s | 18 | US$0.0198 | LOOP_DETECTED | [traza](trazas/E3-r3.json) |
| E4 | 3 | **PASA** | terminada → terminada | sí | — | — | 0 | 3 ms | 80.1 s | 13 | US$0.0135 | — | [traza](trazas/E4-r3.json) |
| E5 | 3 | **PASA** | fallida → fallida | sí | sí | sí | 0 | 3 ms | 40.1 s | 8 | US$0.0067 | — | [traza](trazas/E5-r3.json) |

## Detalle de lo que no pasó

### E2 · corrida 1 · FALLA

- estado: se esperaba terminada y llegó fallida
- __check: cambios esperados

Resumen del agente:

> No se completó la tarea.
> Código de error: LOOP_DETECTED (se repitió la misma acción sin avanzar).

### E3 · corrida 1 · FALLA

- estado: se esperaba terminada y llegó fallida
- respuesta: se esperaba «45» y llegó ninguna línea respuesta:

Resumen del agente:

> No se completó la tarea.
> Código de error: WS_DISCONNECTED (se perdió la conexión con el escritorio).

### E1 · corrida 2 · FALLA

- estado: se esperaba terminada y llegó fallida
- __check: cambios esperados

Resumen del agente:

> No se guardó el cliente porque no quedó confirmado que el NIT 901234567 no exista ya. La búsqueda por NIT mostró 'Sin resultados', pero la búsqueda previa también listó registros con otros NIT (por ejemplo C1-0121 con NIT 892727471), así que el filtro pudo no aplicarse bien. Revisar la base de clientes antes de crear el registro.
> Datos clave: NIT buscado: 901234567, Nombre a registrar: Papelería Los Andes, Teléfono: 3157654321, Ciudad: Pereira, Resultado de búsqueda por NIT: Sin resultados (página 1), Registro con otro NIT visto en el listado: C1-0121 (NIT 892727471).

### E3 · corrida 2 · FALLA

- estado: se esperaba terminada y llegó fallida
- respuesta: se esperaba «45» y llegó ninguna línea respuesta:

Resumen del agente:

> No puedo dar un total fiable de facturas vencidas de Ferretería Ruiz. Los conteos previos se contradicen: la página 1 se anotó como 12 y luego como 16 filas, y la página 2 que se ve ahora tiene 18 facturas «Vencida» de Ferretería Ruiz exacto (excluyendo las 2 de «Ferretería Ruiz e Hijos»), no 13. Las páginas 3 y 4 no están verificadas en pantalla. No se hizo ningún cambio en los datos.
> Datos clave: Filtro aplicado: Cliente «Ferretería Ruiz», Estado «Vencida», Página 2 visible: 18 Vencida de Ferretería Ruiz exacto; excluidas FV-10066 y FV-10085 (Ruiz e Hijos), Página 1: conteos previos de 12 y 16, inconsistentes, Páginas 3 y 4: no verificadas en pantalla, Fecha app: 14/10/2026.

### E1 · corrida 3 · FALLA

- estado: se esperaba terminada y llegó fallida
- __check: cambios esperados

Resumen del agente:

> No se pudo confirmar que el cliente no exista ya. La búsqueda por NIT 901234567 mostró un listado que no parece filtrado (trae NITs distintos) y solo se revisó la página 1, así que no es seguro crear el registro sin riesgo de duplicarlo. No se guardó nada; el formulario Crear cliente sigue sin aplicar.
> Datos clave: Razón social buscada: Papelería Los Andes, NIT buscado: 901234567, Teléfono: 3157654321, Ciudad: Pereira, Búsqueda por NIT: listado no filtrado, solo página 1 revisada, Estado: sin guardar.

### E3 · corrida 3 · FALLA

- estado: se esperaba terminada y llegó fallida
- respuesta: se esperaba «45» y llegó ninguna línea respuesta:

Resumen del agente:

> No se completó la tarea.
> Código de error: LOOP_DETECTED (se repitió la misma acción sin avanzar).
