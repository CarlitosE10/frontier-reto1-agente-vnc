---
name: design-spec
description: Escribe la especificación funcional de una feature de ALUNIA en docs/specs/YYYY-MM-DD-titulo.md, redactada desde el punto de vista del usuario. Úsala cuando el problema y el alcance ya están claros — típicamente justo después de [brainstorming], o cuando el usuario pide "escribe la spec", "documenta esto antes de codear", "especifica la feature" — y siempre antes de empezar a implementar algo nuevo. NO la uses cuando el problema todavía está difuso (ahí va brainstorming primero), ni para documentar código ya escrito, ni para diseño técnico interno (esquemas, endpoints, migraciones) — eso es [design-plan]. Termina en un approval gate: el usuario itera la spec o la aprueba, y solo al aprobarla se pasa a [design-plan].
---

# Design spec — la feature contada desde el usuario

Este documento describe **qué vive el usuario**, no cómo se construye.
Si alguien que no programa lo lee, tiene que entenderlo completo y poder decir "sí, eso es lo que quiero" o "no, ahí te equivocaste".

## Regla de oro

Nada de implementación. Sin nombres de tablas, columnas, endpoints, componentes, librerías ni migraciones.
Si una frase solo la entiende quien conoce el código, está mal escrita: reescríbela en términos de lo que la persona ve, hace y obtiene.

Prueba rápida: cada afirmación debería poder verificarla alguien usando el producto, sin abrir el repo.

## Antes de escribir

1. Confirma que el problema está cerrado. Si quedan bifurcaciones abiertas, vuelve a [brainstorming] — no las tapes con supuestos.
2. Revisa el README raíz y las specs ya aprobadas en `docs/specs/` que toquen la misma área. La spec nueva no puede contradecirlas; si lo hace, dilo explícito.
3. Si falta un dato que cambia el comportamiento observable, pregúntalo antes de redactar. Un dato inventado en la spec se propaga a todo lo que venga después.

## El archivo

Ruta: `docs/specs/YYYY-MM-DD-titulo.md`

- La fecha es la de hoy en formato ISO. Obtenla ejecutando `date +%F`, no de memoria.
- El título va en kebab-case, en español, 2–5 palabras, describiendo la feature y no la tarea:
  `2026-03-14-portafolio-compartido-participantes.md`, no `2026-03-14-cambios.md`.
- Crea `docs/specs/` si no existe.
- **Una spec nueva por cada feature o corrección**, aunque toque la misma área que una
  spec anterior o construya sobre ella. No la agregues como una sección o una "enmienda"
  más a un archivo grande ya existente — cada spec es una pieza de trabajo completa, con
  su propio título, su propio approval gate, y su propia fecha.
- Editar un archivo ya existente **solo** aplica mientras esa spec sigue sin aprobar (para
  seguir iterándola dentro de la misma conversación) o para corregir un error puntual
  justo después de aprobarla. Una vez que una spec quedó aprobada e implementada, todo lo
  que venga después —aunque sea un ajuste chico a lo mismo— es una spec nueva, con su
  propio archivo. Si dudas si algo es "la misma feature" o "una feature nueva", trátalo
  como nueva: un archivo de más se lee en dos minutos, un archivo gigante con media
  docena de features mezcladas no se puede aprobar ni revisar de un vistazo.

## Estructura obligatoria

Las seis secciones, en este orden, con estos títulos. No agregues secciones nuevas ni reordenes.

```markdown
# <Título de la feature>

## 1. Overview / Usuarios

Dos o tres frases: qué es esto y para qué existe, en lenguaje de producto.
Después, quién lo usa. Nombra los roles reales de ALUNIA y qué hace cada uno aquí:
dueño de portafolio propio, administrador de portafolios de terceros, participante
de un portafolio compartido. Si un rol no puede usar esta feature, dilo.

## 2. Objetivo

Una sola frase que diga qué podrá hacer el usuario cuando esto exista, y que hoy no puede.
Debajo, 2–4 señales de que salió bien — observables, no métricas de vanidad.

## 3. Contexto del problema

Qué hace el usuario hoy sin esta feature y por qué eso duele: pasos manuales, errores
frecuentes, información que no puede ver, decisiones que toma a ciegas.
Concreto y situado. Sin esta sección la spec no se puede discutir, solo obedecer.

## 4. Alcance V1

Dos listas explícitas:

**Incluye** — lo que esta versión sí resuelve.
**No incluye** — lo que queda fuera a propósito, con la razón en media línea.

La segunda lista importa más que la primera: es la que evita el desborde.
Si algo queda fuera porque contradice el README o una spec aprobada anterior, cítalo.

## 5. Comportamiento esperado

El corazón del documento. Recorre el flujo como lo vive la persona:
qué ve al entrar, qué hace, qué pasa después, qué queda guardado y qué ve al volver.

Cubre siempre:
- El camino feliz, paso a paso.
- Estado vacío: primera vez, sin datos todavía.
- Qué se muestra mientras algo tarda.
- **Dónde está el punto de confirmación humana.** ALUNIA no escribe al portafolio sin que
  una persona confirme: di exactamente qué se le muestra antes de confirmar, qué puede
  corregir ahí, y qué pasa si cancela.
- Si hay dinero involucrado: en qué moneda se muestra, con qué TRM y de qué fecha.

Usa presente y voz activa: "el usuario ve…", "el sistema le muestra…".

## 6. Posibles errores y mitigaciones

Tabla. Solo fallas que el usuario alcanza a percibir.

| Situación | Qué ve el usuario | Cómo lo resolvemos |
|---|---|---|
| … | … | … |

Piensa en: datos incompletos o ilegibles, precio o TRM no disponible, permisos insuficientes,
acciones duplicadas, conexión caída a mitad de un flujo, el usuario abandona sin confirmar.
Nada de excepciones internas — si el usuario no lo nota, no va acá.
```

## Approval gate — nadie pasa sin aprobación

La spec no está terminada porque tú la escribiste. Está terminada cuando el usuario la aprueba.
Cambiar un párrafo acá cuesta minutos; cambiarlo en código cuesta días.

Al guardar el archivo, di la ruta y resume en 3 líneas: qué entra en V1, qué queda fuera y qué
supuestos asumiste. Después **detente** y pregunta con `AskUserQuestion`, con estas tres salidas:

- **Aprobar** → la spec queda congelada. Anota en el documento `Aprobada el <fecha>` bajo el título
  y continúa con [design-plan], que la convierte en tareas.
- **Iterar** → el usuario dice qué está mal. Corrige el documento, vuelve a resumir los cambios y
  **vuelve a preguntar**. Esta vuelta se repite las veces que haga falta.
- **Replantear** → lo que falla no es la redacción sino el problema. Regresa a [brainstorming].

Reglas del gate:

- **No empieces a implementar sin una aprobación explícita.** Silencio no es aprobación, y "se ve bien"
  tampoco lo es si todavía hay preguntas abiertas en la conversación.
- Si el usuario aprueba pero pide un ajuste menor en la misma frase, aplica el ajuste **antes** de
  marcarla aprobada.
- Si el usuario te pide saltarte el gate, hazlo — pero deja escrito en el documento que se aprobó
  sin revisión, y cuáles supuestos quedaron sin validar.
