"""Ciclo del agente (plan, T09; diseño, sección 2.3).

Cada paso: observar → decidir (VLM) → controlar (esquema y filtro) → actuar → verificar (diff).

`run_agent` deja el progreso y el costo en el `TaskRecord` mientras trabaja, pero nunca publica
el estado final: se desconecta del escritorio y recién entonces devuelve el `AgentResult`, que
publica el ejecutor. Así, cuando alguien lee `terminada` o `fallida`, no queda ninguna acción en
vuelo.
"""

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from PIL import Image

from app.agent.gate import Gate, is_irreversible
from app.agent.prompts import system_prompt
from app.agent.summary import build_summary, sanitize
from app.agent.tools import TOOLS, ActionError, parse_action
from app.config import Settings
from app.llm.openrouter import ChatResult, LLMError, OpenRouterClient, image_part
from app.models import (
    Action,
    AgentResult,
    Click,
    Effect,
    ErrorCode,
    FailTask,
    FinishTask,
    GateDecision,
    PressKey,
    Scroll,
    TaskRecord,
    TaskStatus,
    TypeText,
    Wait,
)
from app.perception.diff import changed_pixels
from app.perception.ocr import read_text, words_near
from app.tracing import Trace
from app.vnc.client import DesktopError, DesktopSession

logger = logging.getLogger(__name__)

LOOP_REPEATS = 3  # la misma acción sobre la misma pantalla, a la tercera vez: LOOP_DETECTED
LOOP_WINDOW = 20  # intentos recientes que se comparan para detectar ciclos
NO_EFFECT_WARNING = 2  # acciones seguidas sin efecto antes de avisarle al VLM
MAX_INVALID_REPLIES = 3  # respuestas inválidas seguidas antes de terminar con VLM_ERROR
EVIDENCE_PINNED = 10  # listados marcados por el VLM que se conservan como evidencia
EVIDENCE_MAX_CHARS = 20_000  # tope del texto de evidencia que recibe la verificación
TEXT_CHARS = 200  # largo máximo de observaciones y textos en el historial y el progreso


async def run_agent(
    record: TaskRecord,
    desktop_factory: Callable[[], DesktopSession],
    llm: OpenRouterClient,
    gate: Gate,
    trace: Trace,
    cancel: asyncio.Event,
    settings: Settings,
) -> AgentResult:
    """Ejecuta la tarea de `record` en el escritorio que abre `desktop_factory`.

    `cancel` se revisa antes de cada acción: una vez puesta, ninguna acción más llega al
    escritorio. El resultado se devuelve siempre después de desconectarse.
    """
    return await _Run(record, llm, gate, trace, cancel, settings).execute(desktop_factory)


class _Stop(Exception):
    """Termina la tarea como fallida con un código de error."""

    def __init__(self, code: ErrorCode, message: str = "") -> None:
        super().__init__(message or code.value)
        self.code = code


class _Run:
    """Estado de una tarea mientras corre el ciclo."""

    def __init__(
        self,
        record: TaskRecord,
        llm: OpenRouterClient,
        gate: Gate,
        trace: Trace,
        cancel: asyncio.Event,
        settings: Settings,
    ) -> None:
        self.record = record
        self.task = record.request.tarea
        self.llm = llm
        self.gate = gate
        self.trace = trace
        self.cancel = cancel
        self.settings = settings
        secrets = (
            record.request.escritorio.password.get_secret_value(),
            settings.team_token.get_secret_value(),
            settings.openrouter_api_key.get_secret_value(),
        )
        self.secrets = [secret for secret in secrets if secret]
        self.evidence = _Evidence(settings.evidence_screens, enabled=settings.verify_enabled)
        self.history: deque[str] = deque(maxlen=settings.history_steps)
        self.attempts: deque[tuple[dict, Image.Image]] = deque(maxlen=LOOP_WINDOW)
        self.steps = 0
        self.vlm_cost = 0.0
        self.gate_cost_start = gate.cost_usd  # Gate acumula lo que gastan sus verificaciones
        self.invalid_replies = 0
        self.no_effect = 0
        self.in_form = False  # hubo escritura desde el último clic: Enter puede guardar
        self.fecha_app: str | None = None
        self.fecha_app_known = False
        self.size = (0, 0)
        self.system = ""
        self.clock = asyncio.get_running_loop().time
        self.started = self.clock()
        self.deadline = self.started + settings.task_time_budget_s

    @property
    def cost(self) -> float:
        """Gasto de la tarea: las decisiones del VLM más las verificaciones."""
        return self.vlm_cost + self.gate.cost_usd - self.gate_cost_start

    # --- Ciclo ---

    async def execute(self, desktop_factory: Callable[[], DesktopSession]) -> AgentResult:
        final: FinishTask | FailTask | None = None
        error_code: ErrorCode | None = None
        self._progress("Conectando al escritorio")
        try:
            self._check_cancel()
            # DesktopSession ya reintenta la conexión: aquí no se reintenta otra vez.
            async with desktop_factory() as desktop:
                final = await self._work(desktop)
            # Fuera del bloque ya se desconectó: de aquí en adelante no se opera el escritorio.
        except (_Stop, DesktopError, LLMError) as error:
            error_code = error.code
        except Exception:
            logger.exception("Error inesperado en la tarea %s", self.record.id)
        finally:
            await self.evidence.aclose()
        if final is not None and error_code is not None:
            # Un error al desconectar no cambia una tarea que ya se había cerrado.
            logger.warning("Error al desconectar la tarea %s: %s", self.record.id, error_code)
            error_code = None

        status = TaskStatus.TERMINADA if isinstance(final, FinishTask) else TaskStatus.FALLIDA
        summary = sanitize(build_summary(final, error_code), self.secrets)
        return AgentResult(
            status=status,
            summary=summary,
            error_code=error_code,
            cost_usd=self.cost,
            steps=self.steps,
        )

    async def _work(self, desktop: DesktopSession) -> FinishTask | FailTask:
        self.size = desktop.size
        self.system = system_prompt(self.size, self.settings.vlm_coord_mode)
        screen = await desktop.screenshot()
        self.evidence.add(screen)
        self._progress("Conectado: analizando la pantalla")
        while True:
            self._check_budget()
            self._check_cancel()
            self.steps += 1
            log: dict = {"paso": self.steps, "captura": await self._screenshot(screen)}
            try:
                outcome = await self._step(desktop, screen, log)
            except (_Stop, DesktopError, LLMError) as error:
                log["error_code"] = error.code.value
                self._trace_step(log)
                raise
            if isinstance(outcome, FinishTask | FailTask):
                return outcome
            screen = outcome

    async def _step(
        self, desktop: DesktopSession, screen: Image.Image, log: dict
    ) -> FinishTask | FailTask | Image.Image:
        """Un paso del ciclo. Devuelve la acción que cierra la tarea o la pantalla siguiente."""
        chat = await self._decide(screen, log)
        self._check_cancel()
        try:
            action = self._parse(chat)
        except ActionError as error:
            self.invalid_replies += 1
            log["accion"] = chat.arguments
            if self.invalid_replies >= MAX_INVALID_REPLIES:
                raise _Stop(ErrorCode.VLM_ERROR, "respuestas inválidas seguidas") from error
            self._end_step(log, chat.tool_name or "sin herramienta", f"respuesta inválida: {error}")
            return screen
        self.invalid_replies = 0
        self._take_note(chat, action)
        label = _describe(action, chat.arguments)
        log.update(accion=action.model_dump(mode="json"), observacion=action.observacion)

        if isinstance(action, FailTask):
            self._end_step(log, label, "la tarea termina como fallida")
            return action
        self._check_loop(action, screen, log)
        if isinstance(action, FinishTask):
            decision = await self._verify_completion(action, screen, log)
            if decision is None or decision.outcome == "approve":
                self._end_step(log, label, "cierre aceptado")
                return action
            self._end_step(
                log,
                label,
                f"la verificación final RECHAZÓ el cierre: {decision.reason}. "
                "Sigue trabajando o usa fail_task",
            )
            return screen

        decision = await self._verify_action(action, screen, log)
        if decision is not None and decision.outcome == "block":
            log["error_code"] = ErrorCode.GATE_BLOCKED.value
            self._end_step(
                log, label, f"BLOQUEADA por la verificación, no se ejecutó: {decision.reason}"
            )
            return screen
        # Última revisión antes de tocar el escritorio: la verificación pudo tardar.
        self._check_time()
        self._check_cancel()
        after, result = await self._execute(desktop, action, screen, log)
        self._end_step(log, label, result)
        return after

    # --- Decidir ---

    async def _decide(self, screen: Image.Image, log: dict) -> ChatResult:
        image = await asyncio.to_thread(image_part, screen)
        messages = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": [{"type": "text", "text": self._step_prompt()}, image]},
        ]
        async with self._budget():
            chat = await self.llm.chat(self.settings.vlm_model, messages, TOOLS)
        self.vlm_cost += chat.cost_usd
        self.record.cost_usd = self.cost
        log.update(
            herramienta=chat.tool_name,
            latencia_vlm_s=round(chat.latency_s, 3),
            costo_usd=chat.cost_usd,
            costo_total_usd=round(self.cost, 6),
        )
        return chat

    def _step_prompt(self) -> str:
        if not self.fecha_app_known:
            fecha = "aún no la informaste. Inclúyela en fecha_app (vacía si no se ve)."
        elif self.fecha_app is None:
            fecha = "no se ve en la app."
        else:
            fecha = self.fecha_app
        remaining = max(0.0, self.deadline - self.clock())
        lines = [
            f"Tarea: {self.task}",
            f"Fecha que muestra la app: {fecha}",
            f"Paso {self.steps} de {self.settings.task_max_steps}; quedan {remaining:.0f} s.",
            "",
        ]
        if self.history:
            lines += ["Historial de los últimos pasos:", *self.history]
        elif self.steps == 1:
            lines.append("Este es el primer paso.")
        if self.no_effect >= NO_EFFECT_WARNING:
            lines += [
                "",
                f"Aviso: las últimas {self.no_effect} acciones no cambiaron la pantalla. No "
                "repitas lo mismo: revisa las coordenadas o prueba otra forma.",
            ]
        lines += ["", "La imagen adjunta es la captura actual de la pantalla."]
        return "\n".join(lines)

    def _parse(self, chat: ChatResult) -> Action:
        if chat.tool_name is None:
            detail = f" ({_shorten(chat.text)})" if chat.text.strip() else ""
            raise ActionError(
                f"respondiste sin una herramienta válida{detail}; elige exactamente una"
            )
        return parse_action(chat.tool_name, chat.arguments, self.size, self.settings.vlm_coord_mode)

    def _take_note(self, chat: ChatResult, action: Action) -> None:
        """Progreso, `fecha_app` y listados marcados como evidencia."""
        if action.observacion:
            self._progress(f"Paso {self.steps}: {action.observacion}")
        if action.fecha_app is not None:
            self.fecha_app, self.fecha_app_known = action.fecha_app, True
        elif "fecha_app" in chat.arguments:
            self.fecha_app_known = True
        if chat.arguments.get("es_listado") is True:
            self.evidence.pin_current()

    # --- Controlar ---

    def _check_loop(self, action: Action, screen: Image.Image, log: dict) -> None:
        """La misma acción sobre la misma pantalla por tercera vez termina la tarea.

        Comparar también la pantalla evita confundir con un ciclo la paginación, donde la misma
        acción se repite y la pantalla cambia cada vez.
        """
        signature = action.model_dump(mode="json", exclude={"observacion", "fecha_app"})
        repeats = sum(
            1
            for previous, seen in self.attempts
            if previous == signature and self._same_screen(seen, screen)
        )
        self.attempts.append((signature, screen))
        if repeats + 1 >= LOOP_REPEATS:
            log["resultado"] = f"ciclo: la misma acción {LOOP_REPEATS} veces en la misma pantalla"
            raise _Stop(ErrorCode.LOOP_DETECTED)

    def _same_screen(self, a: Image.Image, b: Image.Image) -> bool:
        return a is b or changed_pixels(a, b) < self.settings.diff_min_pixels

    async def _verify_action(
        self, action: Action, screen: Image.Image, log: dict
    ) -> GateDecision | None:
        """Pasa por el filtro las acciones irreversibles. Devuelve None si no hizo falta."""
        if not self.settings.verify_enabled or isinstance(action, Wait):
            return None
        irreversible = await self._is_irreversible(action, screen)
        log["irreversible"] = irreversible
        if not irreversible:
            return None

        async def check() -> GateDecision:
            return await self.gate.check_action(
                self.task,
                action,
                screen,
                await self.evidence.current_text(),
                await self.evidence.texts(),
            )

        return await self._ask_gate(check, log)

    async def _verify_completion(
        self, action: FinishTask, screen: Image.Image, log: dict
    ) -> GateDecision | None:
        """Chequeo de éxito falso antes de aceptar `finish_task`."""
        if not self.settings.verify_enabled:
            return None

        async def check() -> GateDecision:
            return await self.gate.check_completion(
                self.task,
                action,
                screen,
                await self.evidence.current_text(),
                await self.evidence.texts(),
            )

        return await self._ask_gate(check, log)

    async def _is_irreversible(self, action: Action, screen: Image.Image) -> bool:
        words: list[str] = []
        if isinstance(action, Click):
            try:
                async with self._budget():
                    words = await asyncio.to_thread(words_near, screen, action.x, action.y)
            except _Stop:
                raise
            except Exception:
                # Sin saber qué hay bajo el clic, ante la duda pasa por la verificación.
                logger.warning("Falló el OCR alrededor del clic", exc_info=True)
                return True
        return is_irreversible(action, words, self.in_form, self.settings.irreversible_keywords)

    async def _ask_gate(
        self, check: Callable[[], Awaitable[GateDecision]], log: dict
    ) -> GateDecision:
        started = self.clock()
        spent_before = self.gate.cost_usd
        try:
            async with self._budget():
                decision = await check()
        except _Stop:
            raise
        except Exception as error:
            # Una verificación que falla nunca aprueba.
            logger.warning("La verificación falló", exc_info=True)
            decision = GateDecision(
                outcome="block", reason=f"la verificación falló ({type(error).__name__})"
            )
        finally:
            spent = self.gate.cost_usd - spent_before
            self.record.cost_usd = self.cost
            log.update(
                costo_usd=log.get("costo_usd", 0.0) + spent,  # el arnés suma costo_usd por paso
                costo_verificacion_usd=spent,
                costo_total_usd=round(self.cost, 6),
                latencia_verificacion_s=round(self.clock() - started, 3),
            )
        log["verificacion"] = decision.model_dump(mode="json")
        return decision

    # --- Actuar y verificar ---

    async def _execute(
        self, desktop: DesktopSession, action: Action, screen: Image.Image, log: dict
    ) -> tuple[Image.Image, str]:
        started = self.clock()
        stable = True
        if isinstance(action, Wait):
            await self._wait(action.segundos)
            after = await desktop.screenshot()
        else:
            try:
                await _act(desktop, action)
            except ValueError as error:
                # DesktopSession valida antes de enviar: al escritorio no llegó nada.
                return screen, f"acción inválida, no se ejecutó: {error}"
            after, stable = await self._settle(desktop, screen)
        log["latencia_vnc_s"] = round(self.clock() - started, 3)

        if isinstance(action, Click):
            self.in_form = False
        elif isinstance(action, TypeText):
            self.in_form = True
        changed = changed_pixels(screen, after)
        log["diff_pct"] = round(100 * changed / (after.width * after.height), 2)
        if changed >= self.settings.diff_min_pixels:
            self.no_effect = 0
            self.evidence.add(after)
            result = f"la pantalla cambió ({log['diff_pct']} % de los píxeles)"
        elif isinstance(action, Wait):
            result = "la pantalla no cambió"
        else:
            self.no_effect += 1
            log["error_code"] = ErrorCode.CLICK_NO_EFFECT.value
            result = "sin efecto visible en la pantalla"
            if isinstance(action, Click) and action.efecto is Effect.EDITAR:
                # Un clic de enfoque sobre un campo ya enfocado no cambia nada, y el VLM lo repetía
                # hasta LOOP_DETECTED. No se sabe si el campo ya tenía el foco o si el clic cayó
                # fuera: se le dice como hipótesis y que lo compruebe al escribir.
                result += (
                    "; si era para enfocar un campo, puede que ya estuviera enfocado o que el "
                    "clic no cayó en el campo: escribe con type_text y comprueba en la captura "
                    "siguiente que el texto quedó en el campo correcto; si no, haz clic en el "
                    "centro del campo"
                )
            elif isinstance(action, TypeText):
                result += (
                    "; el texto no llegó a ningún campo (salvo que el campo ya mostrara ese mismo "
                    "valor): haz clic en el centro del campo y vuelve a escribir"
                )
        if not stable:
            result += "; la pantalla no terminó de estabilizarse"
        return after, result

    async def _settle(
        self, desktop: DesktopSession, before: Image.Image
    ) -> tuple[Image.Image, bool]:
        try:
            return await desktop.settle(before), True
        except DesktopError as error:
            if error.code is not ErrorCode.SCREEN_NOT_STABLE:
                raise
            return await desktop.screenshot(), False

    async def _wait(self, seconds: float) -> None:
        """Pausa que termina antes si llega la cancelación o se acaba el tiempo."""
        timeout = min(seconds, max(0.0, self.deadline - self.clock()))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.cancel.wait(), timeout=timeout)

    # --- Presupuestos y cancelación ---

    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise _Stop(ErrorCode.CANCELLED)

    def _check_time(self) -> None:
        if self.clock() >= self.deadline:
            raise _Stop(ErrorCode.BUDGET_EXHAUSTED, "tiempo agotado")

    def _check_budget(self) -> None:
        self._check_time()
        if self.steps >= self.settings.task_max_steps:
            raise _Stop(ErrorCode.BUDGET_EXHAUSTED, "pasos agotados")
        if self.cost >= self.settings.task_max_cost_usd:
            raise _Stop(ErrorCode.BUDGET_EXHAUSTED, "tope de gasto alcanzado")

    @contextlib.asynccontextmanager
    async def _budget(self) -> AsyncIterator[None]:
        """Corta la espera (VLM, verificación, OCR) cuando se acaba el tiempo de la tarea."""
        try:
            async with asyncio.timeout_at(self.deadline):
                yield
        except TimeoutError:
            raise _Stop(ErrorCode.BUDGET_EXHAUSTED, "tiempo agotado") from None

    # --- Historial, progreso y trazas ---

    def _end_step(self, log: dict, label: str, result: str) -> None:
        line = f"{log['paso']}. {label} → {result}"
        if observation := _shorten(log.get("observacion", "")):
            line += f". Observación: {observation}"
        self.history.append(line)
        log["resultado"] = result
        self._trace_step(log)

    def _progress(self, text: str) -> None:
        self.record.progress = sanitize(_shorten(text), self.secrets)

    def _trace_step(self, fields: dict) -> None:
        try:
            self.trace.step(t_s=round(self.clock() - self.started, 3), **fields)
        except Exception:
            logger.warning("No se pudo escribir la traza", exc_info=True)

    async def _screenshot(self, screen: Image.Image) -> str | None:
        try:
            return await asyncio.to_thread(self.trace.screenshot, screen, f"paso-{self.steps:02d}")
        except Exception:
            logger.warning("No se pudo guardar la captura", exc_info=True)
            return None


@dataclass
class _Screen:
    order: int
    text: asyncio.Task[str]
    pinned: bool = False


class _Evidence:
    """Memoria de evidencia: OCR de las últimas pantallas y de los listados que marca el VLM.

    El OCR de cada pantalla arranca en segundo plano apenas llega, en paralelo con la llamada
    al VLM, y solo se espera cuando la verificación lo necesita.
    """

    def __init__(self, recent: int, enabled: bool) -> None:
        self._enabled = enabled
        self._recent: deque[_Screen] = deque(maxlen=max(recent, 1))
        self._pinned: deque[_Screen] = deque(maxlen=EVIDENCE_PINNED)
        self._tasks: set[asyncio.Task[str]] = set()
        self._count = 0

    def add(self, image: Image.Image) -> None:
        if not self._enabled:
            return
        task = asyncio.create_task(asyncio.to_thread(_ocr, image))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        self._count += 1
        self._recent.append(_Screen(self._count, task))

    def pin_current(self) -> None:
        if self._recent and not self._recent[-1].pinned:
            self._recent[-1].pinned = True
            self._pinned.append(self._recent[-1])

    async def current_text(self) -> str:
        return await self._recent[-1].text if self._recent else ""

    async def texts(self) -> list[str]:
        """Textos en orden cronológico, sin repetidos; si pasan el tope, salen los más viejos."""
        screens = {screen.order: screen for screen in (*self._pinned, *self._recent)}
        texts = [(await screens[order].text).strip() for order in sorted(screens)]
        texts = list(dict.fromkeys(text for text in texts if text))
        while len(texts) > 1 and sum(map(len, texts)) > EVIDENCE_MAX_CHARS:
            texts.pop(0)
        return texts

    async def aclose(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _ocr(image: Image.Image) -> str:
    try:
        return read_text(image)
    except Exception:
        logger.warning("Falló el OCR; la evidencia de esta pantalla queda vacía", exc_info=True)
        return ""


async def _act(desktop: DesktopSession, action: Action) -> None:
    match action:
        case Click():
            await desktop.click(action.x, action.y, double=action.double)
        case TypeText():
            await desktop.type_text(action.texto)
        case PressKey():
            await desktop.press(action.combinacion)
        case Scroll():
            await desktop.scroll(action.x, action.y, action.direccion, action.cantidad)


def _describe(action: Action, arguments: dict) -> str:
    """La acción en una línea del historial, con las coordenadas tal como las envió el VLM."""
    point = f"({arguments.get('x')}, {arguments.get('y')})"
    match action:
        case Click():
            verb = "doble clic" if action.double else "clic"
            return f"{verb} en {point} sobre «{action.objetivo}» [{action.efecto.value}]"
        case TypeText():
            return f"escribir «{_shorten(action.texto)}» en {action.campo}"
        case PressKey():
            return f"tecla {action.combinacion}"
        case Scroll():
            return f"scroll {action.direccion} ×{action.cantidad} en {point}"
        case Wait():
            return f"esperar {action.segundos:g} s"
        case FinishTask():
            return f"finish_task «{_shorten(action.resumen)}»"
        case FailTask():
            return f"fail_task «{_shorten(action.razon)}»"


def _shorten(text: str, limit: int = TEXT_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
