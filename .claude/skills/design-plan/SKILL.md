---
name: design-plan
description: Convierte una spec aprobada en un plan de implementación técnico, guardado en docs/plans/YYYY-MM-DD-titulo.md. Invócala en cuanto el usuario apruebe una spec de docs/specs/ (el approval gate de [design-spec] termina aquí), y también cuando pida "haz el plan", "cómo lo vamos a implementar", "divide esto en tareas" sobre algo ya especificado. Traduce el comportamiento esperado en una lista ordenada de tareas con archivos, dependencias y criterio de listo. NO la uses si no hay spec aprobada — ahí van primero [brainstorming] y [design-spec].
---

# Design plan — de la spec aprobada a las tareas

La spec dice **qué vive el usuario**. El plan dice **qué se construye, en qué orden y cómo sabemos que cada pieza quedó**.
Aquí sí se habla de archivos, paquetes, migraciones y tipos: es el documento técnico.

## Regla de oro

Cada tarea del plan tiene que ser ejecutable sin volver a preguntarle nada al usuario.
Si al escribir una tarea necesitas adivinar algo, no es una tarea: es una decisión pendiente. Resuélvela antes o márcala explícita.

## Antes de escribir

1. **Exige la spec aprobada.** Sin ella no hay plan. Si no existe o no está aprobada, para y ve a [design-spec].
2. Lee la spec completa, sobre todo *Alcance V1* y *Comportamiento esperado*: el plan no puede entregar ni más ni menos que eso.
3. Mira el código real antes de planear sobre él — `architecture.md` para los límites entre paquetes, `plan.md` para lo que ya existe, y los paquetes que vas a tocar (`packages/*`, `supabase/migrations/`, la app web).
4. Si al mirar el código descubres que la spec es inviable como está escrita, dilo ahora. No la implementes a medias en silencio.

## El archivo

Ruta: `docs/plans/YYYY-MM-DD-titulo.md`

- Fecha de hoy en ISO, obtenida con `date +%F`.
- Mismo `titulo` en kebab-case que la spec que implementa, para que el par se lea de un vistazo:
  `docs/specs/2026-03-14-portafolio-compartido-participantes.md` ↔ `docs/plans/2026-03-14-portafolio-compartido-participantes.md`.
- Crea `docs/plans/` si no existe.

## Estructura obligatoria

Cuatro secciones, en este orden, con estos títulos.

```markdown
# Plan — <Título de la feature>

## 1. Objetivo

Qué queda construido al terminar este plan, en dos o tres frases técnicas.
No repitas la spec: aquí se dice qué software existe después, no qué siente el usuario.

## 2. Contexto del problema

Sobre qué se construye: qué hay hoy en el código, qué falta, qué límites impone
`architecture.md` y qué decisiones ya están tomadas y no se reabren aquí.
Si hay deuda o una desviación conocida en el área que se toca, nómbrala.

## 3. Spec de referencia

Ruta del documento que este plan implementa: `docs/specs/YYYY-MM-DD-titulo.md`,
y la fecha en que el usuario lo aprobó.

Debajo, en 3–5 viñetas, los puntos de la spec que más condicionan la implementación:
el punto de confirmación humana, las reglas de moneda y TRM, los permisos por rol,
y cualquier estado límite que obligue a estructurar el código de cierta forma.

Todo lo que este plan haga tiene que poder rastrearse hasta acá.

## 4. Tareas

Lista ordenada por dependencia: si la tarea N necesita la N-1, van en ese orden.
Empieza por los cimientos (datos y tipos), sigue por la lógica, después la superficie,
y cierra con lo que no se puede probar hasta que lo demás exista.

Cada tarea, con este formato:

### T1 — <verbo + objeto, en una línea>

- **Qué:** el cambio concreto, en una o dos frases.
- **Dónde:** archivos o paquetes que se crean o modifican.
- **Depende de:** otras tareas, o "nada".
- **Detalle:** lo que quien implemente necesita saber y no es obvio — reglas de cálculo,
  validaciones, qué pasa en el caso límite, qué política de RLS aplica, qué NO hacer aquí.
- **Listo cuando:** condición verificable. Un test que pasa, una aserción SQL, una pantalla
  que muestra algo concreto. Nunca "cuando funcione".

Tamaño: si una tarea no cabe en una sesión de trabajo, pártela. Si dos tareas siempre se
tocan juntas, únelas. Entre 4 y 12 tareas es lo sano; muchas más suele significar que el
alcance V1 quedó grande.

Al final de la lista, una línea de **Fuera de este plan**: lo que la spec dejó fuera y
alguien podría confundir con parte de esto.
```

## Al terminar

Di la ruta del archivo y resume en 3 líneas: cuántas tareas, por dónde empieza y qué queda fuera.
Después pregunta si arranca la implementación por T1. Cuando la implementación termine, sigue [verify-after-changes].
