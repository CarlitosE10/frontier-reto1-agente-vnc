# Reporte del arnés · 2026-10-10 16:18

- **Agente:** http://localhost:8000
- **Reset del escritorio:** sí
- **Casos:** 2 · corridas: 1

## Métricas

| Métrica | Valor | Objetivo |
|---|---|---|
| Éxito de punta a punta | 0/2 (0%) | ≥ 80 % |
| Falsos éxitos | 0 | 0 |
| Acciones fuera de la tarea | 0 | 0 |
| Registros duplicados | 0 | 0 |
| Formato de respuesta | 0/1 (0%) | 100 % |
| Fugas de secretos | 0 | 0 |
| Latencia de POST /tasks (p99 / máx.) | 17 ms / 17 ms | < 200 ms (límite: 2 s) |
| Duración por tarea (p95) | 85.1 s | < 240 s |
| Pasos por tarea (p95) | 14 | < 30 |
| Costo por tarea (promedio / máx.) | US$0.0136 / US$0.0139 | ≤ US$0.05 (tope: US$0.15) |

## Resultados

| Caso | Corrida | Resultado | Estado esperado → obtenido | `__check` | `respuesta:` | Claves | Fugas | POST | Duración | Pasos | Costo | Errores | Traza |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E1 | 1 | **FALLA** | terminada → fallida | no | — | — | 0 | 17 ms | 70.1 s | 14 | US$0.0132 | CLICK_NO_EFFECT LOOP_DETECTED | [traza](trazas/E1-r1.json) |
| E3 | 1 | **FALLA** | terminada → fallida | sí | no | — | 0 | 2 ms | 85.1 s | 11 | US$0.0139 | — | [traza](trazas/E3-r1.json) |

## Detalle de lo que no pasó

### E1 · corrida 1 · FALLA

- estado: se esperaba terminada y llegó fallida
- __check: cambios esperados

Resumen del agente:

> No se completó la tarea.
> Código de error: LOOP_DETECTED (se repitió la misma acción sin avanzar).

### E3 · corrida 1 · FALLA

- estado: se esperaba terminada y llegó fallida
- respuesta: se esperaba «45» y llegó ninguna línea respuesta:

Resumen del agente:

> No puedo dar un conteo verificado. La verificación rechazó mi respuesta anterior (45) porque mis subtotales por página no cuadran con el detalle, y en el filtro aparecen filas «Ferretería Ruiz e Hijos» que no supe separar. Esta pantalla (página 4) muestra 5 vencidas de Ferretería Ruiz (FV-10053, FV-10131, FV-10184, FV-10061, FV-10094), pero no pude rehacer el recuento de las páginas 1 a 3 con certeza y el tiempo restante es corto.
> Datos clave: Filtro Cliente: Ferretería Ruiz, Estado: Todos, Página 4 vencidas: FV-10053, FV-10131, FV-10184, FV-10061, FV-10094 (5), Página 4 pendientes: FV-10087, FV-10089, Respuesta anterior 45 rechazada por la verificación.
