"""Одна очередь на все изменения (05-INTERFACES §7.2).

Telegram, приложение и терминал меняют состояние только через главный поток службы:
один Core, один Bot, без гонок. Поток опроса Telegram и потоки HTTP-сервера лишь кладут
работу в очередь. Быстрые операции (закрыть задачу, запустить таймер) ждут результата;
сообщение в чат — нет: ответ приходит в приложение через поток событий.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger("arvix.hub")


class Job:
    def __init__(self, fn: Callable[[Any], Any], label: str = "", chat: bool = False) -> None:
        self.fn = fn
        self.label = label
        self.chat = chat  # новое сообщение человека: пока оно ждёт, ответ на прежнее идёт цитатой (D52)
        self.done = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None


class Hub:
    def __init__(self) -> None:
        self.jobs: queue.Queue[Job] = queue.Queue()
        self.busy = ""  # что сейчас делает главный поток: «думаю» для приложения

    def post(self, fn: Callable[[Any], Any], label: str = "", *, chat: bool = False) -> Job:
        job = Job(fn, label, chat)
        self.jobs.put(job)
        return job

    def chat_waiting(self) -> bool:
        """В очереди есть ещё сообщение человека — он написал, пока Arvix думал над прошлым."""
        with self.jobs.mutex:
            return any(job.chat for job in self.jobs.queue)

    def call(self, fn: Callable[[Any], Any], timeout: float = 30, label: str = "") -> Any:
        """Выполнить в главном потоке и вернуть результат (или поднять его ошибку)."""
        job = self.post(fn, label)
        if not job.done.wait(timeout):
            raise TimeoutError("Arvix занят — попробуй через несколько секунд")
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
            self.busy = job.label
            try:
                job.result = job.fn(bot)
            except BaseException as exc:  # noqa: BLE001 — ошибку получит тот, кто ждёт
                job.error = exc
                if job.label:
                    log.exception("задача %s", job.label)
            finally:
                self.busy = ""
                job.done.set()
            count += 1
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                return count
