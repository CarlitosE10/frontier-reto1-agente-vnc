# Reporte del arnés · 2026-10-10 16:34

- **Agente:** http://localhost:8000
- **Reset del escritorio:** sí
- **Casos:** 5 · corridas: 3

## Métricas

| Métrica | Valor | Objetivo |
|---|---|---|
| Éxito de punta a punta | 13/15 (87%) | ≥ 80 % |
| Falsos éxitos | 0 | 0 |
| Acciones fuera de la tarea | 0 | 0 |
| Registros duplicados | 0 | 0 |
| Formato de respuesta | 5/6 (83%) | 100 % |
| Fugas de secretos | 0 | 0 |
| Latencia de POST /tasks (p99 / máx.) | 16 ms / 16 ms | < 200 ms (límite: 2 s) |
| Duración por tarea (p95) | 130.2 s | < 240 s |
| Pasos por tarea (p95) | 24 | < 30 |
| Costo por tarea (promedio / máx.) | US$0.0150 / US$0.0263 | ≤ US$0.05 (tope: US$0.15) |
| Estabilidad entre corridas | 3/5 (60%) | ≥ 90 % |

## Resultados

| Caso | Corrida | Resultado | Estado esperado → obtenido | `__check` | `respuesta:` | Claves | Fugas | POST | Duración | Pasos | Costo | Errores | Traza |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E1 | 1 | **PASA** | terminada → terminada | sí | — | — | 0 | 16 ms | 95.2 s | 18 | US$0.0184 | — | [traza](trazas/E1-r1.json) |
| E2 | 1 | **PASA** | terminada → terminada | sí | — | — | 0 | 4 ms | 70.1 s | 12 | US$0.0125 | — | [traza](trazas/E2-r1.json) |
| E3 | 1 | **PASA** | terminada → terminada | sí | sí | — | 0 | 2 ms | 125.2 s | 16 | US$0.0213 | — | [traza](trazas/E3-r1.json) |
| E4 | 1 | **PASA** | terminada → terminada | sí | — | — | 0 | 2 ms | 80.1 s | 13 | US$0.0147 | — | [traza](trazas/E4-r1.json) |
| E5 | 1 | **PASA** | fallida → fallida | sí | sí | sí | 0 | 4 ms | 45.1 s | 9 | US$0.0080 | CLICK_NO_EFFECT | [traza](trazas/E5-r1.json) |
| E1 | 2 | **FALLA** | terminada → fallida | no | — | — | 0 | 5 ms | 130.2 s | 24 | US$0.0263 | CLICK_NO_EFFECT GATE_BLOCKED | [traza](trazas/E1-r2.json) |
| E2 | 2 | **PASA** | terminada → terminada | sí | — | — | 0 | 2 ms | 70.1 s | 13 | US$0.0135 | — | [traza](trazas/E2-r2.json) |
| E3 | 2 | **FALLA** | terminada → fallida | sí | no | — | 0 | 3 ms | 120.2 s | 16 | US$0.0203 | LOOP_DETECTED | [traza](trazas/E3-r2.json) |
| E4 | 2 | **PASA** | terminada → terminada | sí | — | — | 0 | 3 ms | 80.1 s | 13 | US$0.0146 | — | [traza](trazas/E4-r2.json) |
| E5 | 2 | **PASA** | fallida → fallida | sí | sí | sí | 0 | 2 ms | 35.0 s | 8 | US$0.0069 | — | [traza](trazas/E5-r2.json) |
| E1 | 3 | **PASA** | terminada → terminada | sí | — | — | 0 | 2 ms | 100.2 s | 20 | US$0.0205 | CLICK_NO_EFFECT | [traza](trazas/E1-r3.json) |
| E2 | 3 | **PASA** | terminada → terminada | sí | — | — | 0 | 4 ms | 70.1 s | 13 | US$0.0135 | — | [traza](trazas/E2-r3.json) |
| E3 | 3 | **PASA** | terminada → terminada | sí | sí | — | 0 | 5 ms | 80.1 s | 11 | US$0.0135 | — | [traza](trazas/E3-r3.json) |
| E4 | 3 | **PASA** | terminada → terminada | sí | — | — | 0 | 3 ms | 75.1 s | 13 | US$0.0145 | — | [traza](trazas/E4-r3.json) |
| E5 | 3 | **PASA** | fallida → fallida | sí | sí | sí | 0 | 4 ms | 35.0 s | 8 | US$0.0071 | — | [traza](trazas/E5-r3.json) |

## Detalle de lo que no pasó

### E1 · corrida 2 · FALLA

- estado: se esperaba terminada y llegó fallida
- __check: cambios esperados

Resumen del agente:

> No pude completar el registro de forma segura. El formulario Crear cliente está completo (Razón social Papelería Los Andes, NIT 901234567, Teléfono 3157654321, Ciudad Pereira) pero NO está guardado. Los intentos de guardar fueron bloqueados por la verificación porque no hay una búsqueda por NIT 901234567 confirmada en la evidencia, y el paso 10 que lo mencionaba no se puede verificar. Antes de crear conviene buscar el NIT 901234567 en el listado de clientes para descartar un duplicado.
> Datos clave: Razón social: Papelería Los Andes, NIT: 901234567, Teléfono: 3157654321, Ciudad: Pereira, Estado: sin guardar.

### E3 · corrida 2 · FALLA

- estado: se esperaba terminada y llegó fallida
- respuesta: se esperaba «45» y llegó ninguna línea respuesta:

Resumen del agente:

> No se completó la tarea.
> Código de error: LOOP_DETECTED (se repitió la misma acción sin avanzar).
