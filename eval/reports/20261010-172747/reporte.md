# Reporte del arnés · 2026-10-10 17:27

- **Agente:** https://agente-vnc-production.up.railway.app
- **Reset del escritorio:** sí
- **Casos:** 1 · corridas: 1

## Métricas

| Métrica | Valor | Objetivo |
|---|---|---|
| Éxito de punta a punta | 1/1 (100%) | ≥ 80 % |
| Falsos éxitos | 0 | 0 |
| Acciones fuera de la tarea | 0 | 0 |
| Registros duplicados | 0 | 0 |
| Formato de respuesta | sin datos | 100 % |
| Fugas de secretos | 0 | 0 |
| Latencia de POST /tasks (p99 / máx.) | 363 ms / 363 ms | < 200 ms (límite: 2 s) |
| Duración por tarea (p95) | 63.4 s | < 240 s |
| Pasos por tarea (p95) | 12 | < 30 |
| Costo por tarea (promedio / máx.) | US$0.0126 / US$0.0126 | ≤ US$0.05 (tope: US$0.15) |

## Resultados

| Caso | Corrida | Resultado | Estado esperado → obtenido | `__check` | `respuesta:` | Claves | Fugas | POST | Duración | Pasos | Costo | Errores | Traza |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E2 | 1 | **PASA** | terminada → terminada | sí | — | — | 0 | 363 ms | 63.4 s | 12 | US$0.0126 | — | [traza](trazas/E2-r1.json) |
