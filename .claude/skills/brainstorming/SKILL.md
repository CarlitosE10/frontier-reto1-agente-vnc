---
name: brainstorming
description: Fase de descubrimiento obligatoria antes de escribir código para cualquier desarrollo nuevo. Úsala cuando el usuario pida construir, agregar, implementar o diseñar algo que todavía no existe (una feature, un módulo, un endpoint, una pantalla, una migración, una integración), o cuando diga "quiero empezar X", "vamos a hacer X", "necesito que el sistema haga X". Hace preguntas dirigidas para eliminar ambigüedades y termina presentando 2 o 3 alternativas de implementación con trade-offs para que el usuario elija por dónde arrancar. NO la uses para cambios puntuales sobre código existente (arreglar un bug, renombrar, ajustar copy, refactor localizado) ni cuando el usuario ya eligió explícitamente el enfoque y solo pide ejecutarlo.
---

# Brainstorming — descubrimiento antes de construir

Antes de escribir una línea de código para algo nuevo, el trabajo es **entender**, no adivinar.
Salir de esta fase con supuestos ocultos es más caro que hacer tres preguntas.

## Regla de oro

No propongas ni escribas código hasta que el usuario haya elegido una de las alternativas del paso 4.
Si el usuario insiste en saltarse el proceso, hazlo — pero deja escritos los supuestos que estás asumiendo.

## Paso 1 — Cargar contexto antes de preguntar

Nunca preguntes lo que el repo ya responde. Antes de la primera pregunta, revisa lo relevante.

## Paso 2 — Detectar las ambigüedades reales

Recorre esta lista y quédate solo con los puntos donde **distintas respuestas producen software distinto**:

- **Alcance**: ¿qué queda explícitamente fuera de esta iteración?
- **Actor y permisos**: ¿quién lo usa? ¿dueño del portafolio, administrador de portafolio ajeno, participante?
- **Datos**: ¿qué entra, qué se persiste, qué se deriva? ¿hay tablas o tipos nuevos?
- **Moneda y precisión**: ¿COP, USD o ambas? ¿qué TRM aplica y de qué fecha?
- **Confirmación humana**: ALUNIA no escribe al portafolio sin confirmación. ¿Dónde está el punto de confirmación de esta feature?
- **Trazabilidad**: ¿qué hay que poder auditar después?
- **Estados límite**: sin datos, datos parciales, precio no disponible, extracto ilegible.
- **Superficie**: ¿UI, API, job en background, o varias?
- **Definición de listo**: ¿cómo sabemos que quedó bien? ¿qué se prueba?

## Paso 3 — Preguntar

Usa `AskUserQuestion` en rondas cortas: **máximo 3–4 preguntas por ronda**, empezando por las que más cambian el diseño.
Cada opción debe decir su consecuencia, no solo su nombre. Si una respuesta abre una ambigüedad nueva, haz una segunda ronda.

Para lo que puedas resolver con un default razonable del proyecto, **no preguntes**: decide, dilo en una línea y sigue.
Reserva las preguntas para lo que de verdad está bifurcado.

## Paso 4 — Presentar 2 o 3 alternativas

Cierra siempre con alternativas concretas de por dónde arrancar. Nunca una sola, nunca más de tres.
Deben ser genuinamente distintas — no la misma idea con otro nombre. Formato:

```
### Alternativa A — <nombre corto>
Qué es: 1–2 frases.
Alcance: qué incluye y qué deja fuera.
A favor: …
En contra: …
Primer paso concreto: el archivo o la migración por donde empieza.
```

Marca **una recomendada** y explica en una frase por qué, dado el estado actual del proyecto.
Un eje útil para diferenciarlas: vertical mínima end-to-end vs. capa de datos primero vs. prototipo desechable para validar el flujo.

## Paso 5 — Cerrar

Cuando el usuario elija, resume en 5 líneas o menos: decisión, alcance acordado, supuestos asumidos, primer paso.
Recién ahí empieza la implementación.
