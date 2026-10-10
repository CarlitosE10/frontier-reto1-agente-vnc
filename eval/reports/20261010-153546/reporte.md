# Reporte del arnés · 2026-10-10 15:35

- **Agente:** http://localhost:8000
- **Reset del escritorio:** sí
- **Casos:** 5 · corridas: 1

## Métricas

| Métrica | Valor | Objetivo |
|---|---|---|
| Éxito de punta a punta | 4/5 (80%) | ≥ 80 % |
| Falsos éxitos | 0 | 0 |
| Acciones fuera de la tarea | 0 | 0 |
| Registros duplicados | 0 | 0 |
| Formato de respuesta | 1/2 (50%) | 100 % |
| Fugas de secretos | 0 | 0 |
| Latencia de POST /tasks (p99 / máx.) | 7 ms / 7 ms | < 200 ms (límite: 2 s) |
| Duración por tarea (p95) | 90.1 s | < 240 s |
| Pasos por tarea (p95) | 18 | < 30 |
| Costo por tarea (promedio / máx.) | US$0.0131 / US$0.0167 | ≤ US$0.05 (tope: US$0.15) |

## Resultados

| Caso | Corrida | Resultado | Estado esperado → obtenido | `__check` | `respuesta:` | Claves | Fugas | POST | Duración | Pasos | Costo | Errores | Traza |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E1 | 1 | **PASA** | terminada → terminada | sí | — | — | 0 | 7 ms | 85.1 s | 18 | US$0.0167 | — | [traza](trazas/E1-r1.json) |
| E2 | 1 | **PASA** | terminada → terminada | sí | — | — | 0 | 3 ms | 75.1 s | 13 | US$0.0131 | CLICK_NO_EFFECT | [traza](trazas/E2-r1.json) |
| E3 | 1 | **FALLA** | terminada → fallida | sí | no | — | 0 | 4 ms | 90.1 s | 14 | US$0.0151 | CLICK_NO_EFFECT VLM_ERROR | [traza](trazas/E3-r1.json) |
| E4 | 1 | **PASA** | terminada → terminada | sí | — | — | 0 | 3 ms | 80.1 s | 13 | US$0.0137 | CLICK_NO_EFFECT | [traza](trazas/E4-r1.json) |
| E5 | 1 | **PASA** | fallida → fallida | sí | sí | sí | 0 | 4 ms | 40.1 s | 8 | US$0.0068 | CLICK_NO_EFFECT | [traza](trazas/E5-r1.json) |

## Detalle de lo que no pasó

### E3 · corrida 1 · FALLA

- estado: se esperaba terminada y llegó fallida
- respuesta: se esperaba «45» y llegó ninguna línea respuesta:

Resumen del agente:

> No se completó la tarea.
> Código de error: VLM_ERROR (el modelo no respondió).
