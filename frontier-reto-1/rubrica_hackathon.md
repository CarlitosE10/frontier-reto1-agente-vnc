# Contexto de Evaluación Hackathon - Reto 1 (Agente VNC)

La evaluación se divide en 4 fases. Para obtener el puntaje máximo (Nivel 4), el sistema y el repositorio deben cumplir con requisitos técnicos estrictos.

## 1. Systems Design (30% del puntaje)
**Cierre:** 12:00
**Entregables:** Documento de diseño y Diagrama de arquitectura.

*   **Entendimiento del problema:** El diseño debe nombrar explícitamente los supuestos asumidos, los casos difíciles (edge cases) y delimitar claramente qué cosas el sistema *no* va a resolver, justificando las razones.
*   **Arquitectura y trade-offs:** No basta con mostrar componentes. Para el puntaje máximo, cada decisión arquitectónica debe explicar qué otra alternativa se descartó y por qué.
*   **Plan para medir:** Se deben definir casos de prueba y métricas concretas desde la fase de diseño para saber si el sistema funciona antes de construirlo.

## 2. Ejecución (40% del puntaje) - Fase Crítica
**Cierre:** 20:00
**Entregables:** Repositorio, Entrypoint (API desplegada) y Video de 2 minutos.

*   **Evaluación Oculta (Entrypoint):** Se probará el bot contra un set de casos que no conoce. Para el puntaje máximo (Nivel 4), el agente debe resolver la mayoría de los casos, incluidos escenarios nuevos no vistos en las pruebas. (Más del 75% de éxito da un puntaje de 4).
*   **¡ALERTA TÉCNICA! Respuesta al incidente:** A las 15:30 habrá un cambio/incidente en el entorno. El sistema debe estar diseñado para detectar que algo se rompió, el equipo debe adaptar el código rápidamente y ser capaz de explicarlo. *Nota para el agente: El código debe ser modular y no depender de coordenadas fijas o flujos rígidos para poder reaccionar a esto.*
*   **Calidad del código:** El proyecto debe poder ejecutarse estrictamente siguiendo las instrucciones del `README` y el código fuente debe explicarse por sí solo (código limpio, bien nombrado y documentado).

## 3. Profundidad Técnica (15% del puntaje)
**Horario:** 20:00 - 21:00
**Entregable:** Debrief (entrevista) individual de 10 minutos.

*   **Lectura de resultados:** El equipo debe ser capaz de explicar cada falla que haya tenido el bot en la evaluación oculta indicando una causa concreta. *Nota para el agente: Es vital implementar buenos logs en el backend (`/tasks/{task_id}`) para poder rastrear exactamente por qué falló una tarea.*
*   **Decisiones y límites:** Se evaluará la capacidad de explicar las fallas, los límites técnicos del sistema construido y qué pasos seguirían para mejorarlo.

## 4. Demo Day (15% del puntaje)
**Horario:** 21:15 - 22:15
**Entregables:** Pitch y material opcional de apoyo.

*   **Claridad y Evidencia:** En pocos minutos debe quedar claro el problema y la solución. Es obligatorio mostrar resultados reales funcionando en la demo, e incluso mostrar abiertamente lo que no funcionó.