"""Одна очередь на все изменения (05-INTERFACES §7.2).

Telegram, приложение и терминал меняют состояние только через главный поток службы:
один Core, один Bot, без гонок. Поток опроса Telegram и потоки HTTP-сервера лишь кладут
работу в очередь. Быстрые операции (закрыть задачу, запустить таймер) ждут результата;
сообщение в чат — нет: ответ приходит в приложение через поток событий.

Голова думает 10–180 с — и раньше всё это время главный поток стоял: кнопки приложения
отваливались по таймауту, Telegram и напоминания ждали (D51). Теперь разговор идёт полосой
(`think`): подготовка запроса и запись ответа — в главном потоке, сам вызов головы — в
отдельном потоке, который базу не трогает. Полоса одна: второе сообщение готовится, только
когда записан ответ на первое, — порядок разговора и история в запросе не ломаются.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections import deque
from collections.abc import Callable
from typing import Any

log = logging.getLogger("arvix.hub")

# start() в главном потоке возвращает (думать, записать) или None — ответ уже дан без головы
Plan = tuple[Callable[[], Any], Callable[[Any], None]] | None


class Job:
    def __init__(self, fn: Callable[[Any], Any], label: str = "", *, show: bool = True) -> None:
        self.fn = fn
        self.label = label
        self.show = show  # видно ли в приложении как «думаю» (апдейт Telegram — нет)
        self.done = threading.Event()
        self.cancelled = False
        self.result: Any = None
        self.error: BaseException | None = None


class Hub:
    def __init__(self, *, spawn: Callable[[Callable[[], None]], None] | None = None) -> None:
        self.jobs: queue.Queue[Job] = queue.Queue()
        self.current: Job | None = None
        self.thinking = ""  # голова думает над ответом (полоса разговора)
        self.lane: deque[tuple[Callable[[], Plan], str]] = deque()
        self.in_flight = False
        self.spawn = spawn or (lambda fn: threading.Thread(target=fn, name="head", daemon=True).start())

    @property
    def busy(self) -> str:
        """Что показать в приложении: «думаю», «слушаю», «смотрю файл» — или пусто."""
        job = self.current
        if job is not None and job.show and job.label:
            return job.label
        return self.thinking

    def post(self, fn: Callable[[Any], Any], label: str = "", *, show: bool = True) -> Job:
        job = Job(fn, label, show=show)
        self.jobs.put(job)
        return job

    def call(self, fn: Callable[[Any], Any], timeout: float = 30, label: str = "") -> Any:
        """Выполнить в главном потоке и вернуть результат (или поднять его ошибку).
        Не дождались — задача снимается: иначе она выполнилась бы позже, и повтор нажатия
        закрыл бы задачу или запустил таймер дважды."""
        job = self.post(fn, label)
        if not job.done.wait(timeout):
            job.cancelled = True
            if self.current is job:  # уже выполняется — снять нельзя, дождёмся (быстрые операции, без головы)
                job.done.wait()
            if not job.done.is_set():
                raise TimeoutError("Арвикс занят — попробуй через несколько секунд")
        if job.error is not None:
            raise job.error
        return job.result

    def run_pending(self, bot: Any, timeout: float) -> int:
        """Главный поток: выполнить всё, что пришло за timeout секунд. Возвращает число задач."""
        count = 0
        try:
            job = self.jobs.get(timeout=timeout)
        except queue.Empty:
            return 0
        while True:
            if not job.cancelled:
                self.current = job
                try:
                    job.result = job.fn(bot)
                except BaseException as exc:  # noqa: BLE001 — ошибку получит тот, кто ждёт
                    job.error = exc
                    if job.label:  # ошибку быстрой операции получит тот, кто ждёт, — в журнал процесса незачем
                        log.exception("задача %s", job.label)
                finally:
                    self.current = None
                    job.done.set()
                count += 1
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                return count

    # --- полоса разговора ---------------------------------------------------------------------

    def think(self, start: Callable[[], Plan], label: str = "думаю") -> None:
        """Из главного потока: встать в очередь разговора. start() вызовется в главном потоке,
        когда полоса свободна, и вернёт (думать, записать): думать — в отдельном потоке,
        записать(результат) — снова в главном."""
        self.lane.append((start, label))
        self._pump()

    def _pump(self) -> None:
        while not self.in_flight and self.lane:
            start, label = self.lane.popleft()
            try:
                plan = start()
            except Exception:  # noqa: BLE001
                log.exception("подготовка ответа")
                continue
            if plan is None:
                continue
            slow, then = plan
            self.in_flight, self.thinking = True, label
            self.spawn(self._worker(slow, then))

    def _worker(self, slow: Callable[[], Any], then: Callable[[Any], None]) -> Callable[[], None]:
        def work() -> None:
            try:
                result, error = slow(), None
            except Exception as exc:  # noqa: BLE001 — голова упала: ответит шаблон
                result, error = None, exc
                log.exception("голова")

            def finish(_bot: Any) -> None:
                try:
                    then(None if error else result)
                finally:
                    self.in_flight, self.thinking = False, ""
                    self._pump()

            self.post(finish, "", show=False)
        return work
