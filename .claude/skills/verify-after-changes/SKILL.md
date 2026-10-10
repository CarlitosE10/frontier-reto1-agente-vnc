---
name: verify-after-changes
description: Verifica en el navegador que lo implementado realmente funciona, antes de darlo por terminado. Invócala tú mismo en cuanto creas que terminaste de implementar un plan o una feature de ALUNIA, y también cuando el usuario diga "pruébalo", "verifica que funcione", "ya terminaste?" o "dale, ciérralo". Levanta el servidor, elige cinco casos de prueba importantes, los ejecuta en el navegador real, compara lo observado contra la spec (`docs/specs/`) y el plan (`docs/plans/`), arregla lo que falle dentro del alcance y, si todo queda correcto, da luz verde de forma explícita. NO la uses a mitad de la implementación ni para correr solo tests automáticos.
---

# Verify after changes — probarlo de verdad antes de cantar victoria

"Compila" y "los tests pasan" no son evidencia de que la feature funciona.
La evidencia es haberla usado en el navegador y haber visto lo que la spec dice que se debe ver.

## Regla de oro

No digas que algo funciona sin haberlo observado en esta sesión.
Si no lo probaste, dilo: "no verificado" es una respuesta honesta; "debería funcionar" no lo es.

## Paso 1 — Levantar el entorno

1. Si hace falta base de datos local: `pnpm db:start` y `pnpm db:reset`.
2. Levanta la app con `preview_start`. Si `.claude/launch.json` no existe, créalo — `pnpm dev` en el puerto 3000, según el README.
3. Revisa los logs del arranque (`preview_logs`) antes de tocar nada. Un servidor que arrancó con errores invalida todo lo que venga después.

Si el servidor no levanta, ese es el primer bug. Arréglalo antes de seguir.

## Paso 2 — Elegir cinco casos

**Escríbelos antes de probar**, con su resultado esperado tomado de la spec (`docs/specs/`) y de los **Listo cuando** del plan (`docs/plans/`), no de tu memoria de lo que codeaste.
Cinco, no más: el objetivo es cubrir lo que importa, no inflar la lista.

Para elegirlos, cubre estos ángulos en orden de prioridad:

1. **El camino feliz completo** de la feature, de punta a punta.
2. **El punto de confirmación humana** — que nada se escriba al portafolio sin confirmar, y que cancelar no deje rastro.
3. **Un caso negativo de permisos** — otro usuario no debe ver ni tocar lo ajeno.
4. **Un estado límite** de la sección *Posibles errores* de la spec: sin datos, dato faltante, precio o TRM no disponible.
5. **Una regresión** del flujo vecino que tocaste y que antes funcionaba.

Si el dominio incluye dinero, al menos un caso debe verificar moneda, TRM y fecha de TRM visibles.

Formato:

| # | Caso | Resultado esperado (según spec) |
|---|---|---|

## Paso 3 — Probar en el navegador

Ejecuta cada caso con las herramientas del navegador. Realmente: navegar, escribir, hacer clic, leer la página.

- `read_page` / `get_page_text` para verificar contenido y estructura — es más fiable que mirar un screenshot.
- Un screenshot cuando lo que importa es cómo se ve.
- `read_console_messages` y `read_network_requests` después de cada caso: un error en consola o un 500 silencioso cuentan como falla aunque la pantalla se vea bien.
- Agrupa pasos predecibles con `browser_batch` para no gastar un viaje por clic.

Anota lo **observado**, no lo esperado. Si un caso no se puede ejecutar (falta una precondición, no hay datos de prueba), dilo — no lo des por bueno.

## Paso 4 — Comparar contra spec y plan

Contrasta lo observado con:

- La spec en `docs/specs/YYYY-MM-DD-titulo.md` — el comportamiento esperado y la tabla de errores.
- El plan en `docs/plans/YYYY-MM-DD-titulo.md` — mismo `titulo` que la spec — tarea por tarea: cada
  una declara un **Listo cuando**, y eso es exactamente lo que hay que comprobar.

Si no encuentras el par spec/plan, búscalo por el nombre de la feature en esas dos carpetas antes de
seguir. Verificar contra tu memoria de lo que codeaste no sirve: el punto es contrastar con lo acordado.

Resultado por caso: **verde** (hace lo que la spec dice), **rojo** (no lo hace) o **fuera de alcance** (falla real, pero pertenece a algo que la spec dejó explícitamente fuera).

Si lo observado es correcto pero la spec decía otra cosa, el que está mal puede ser el documento: dilo y propón corregirlo, no lo ajustes en silencio.

## Paso 5 — Cerrar: arreglar, o dar luz verde

Hay exactamente dos salidas de esta fase. Elige según lo que muestre la comparación.

### Si algo quedó en rojo → arreglar

- Arregla **solo lo que está dentro del alcance**. Lo de fuera se anota y se reporta; no se arregla de contrabando.
- Después de cada arreglo, **vuelve a ejecutar ese caso en el navegador**. Un fix sin re-prueba no es un fix.
- Si un mismo caso falla dos veces seguidas, detente y reporta: diagnóstico, qué intentaste y qué necesitas decidir. Mejor eso que una tercera corrección a ciegas.
- Vuelve a esta comparación hasta que no queden rojos dentro del alcance.

### Si todo está correcto → luz verde

Solo cuando los cinco casos pasaron y no queda nada rojo dentro del alcance, da la luz verde de forma explícita.
No es una palmadita: es una afirmación verificable de que la feature cumple la spec. Dila así:

> **Luz verde.** Los 5 casos pasaron en el navegador. <Feature> cumple lo que dice la spec `<ruta>`.
> Fuera de alcance y sin resolver: <lista, o "nada">.

Reglas de la luz verde:

- Solo se da sobre lo que observaste en esta sesión. Un caso que no pudiste ejecutar **no es verde**.
- Si quedaron fallas fuera de alcance, la luz verde sigue siendo válida, pero **tienen que ir nombradas** en la misma frase. Nunca calladas.
- Si no puedes dar luz verde, dilo con la misma claridad: qué quedó rojo y por qué no se pudo cerrar.

Cierra el servidor de preview si ya no se necesita.

## Reporte final

Cinco líneas o menos: qué probaste, qué falló y arreglaste, qué quedó fuera de alcance y qué sigue pendiente.
Si algo quedó en rojo, va primero en el reporte — nunca enterrado al final.
