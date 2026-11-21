"""Главный цикл Telegram-бота: long polling + тик планировщика.

Поток опроса ждёт Telegram (getUpdates до 20 с) и кладёт апдейты в общую очередь (web/hub.py);
туда же пишут приложение и терминал. Главный поток исполняет очередь и раз в 5 с — планировщик.
Ошибки сети (ноутбук проснулся без Wi-Fi) переживаются с экспоненциальной паузой.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from collections.abc import Callable

from arvix.brain import Brain
from arvix.config import load_config
from arvix.core import Core
from arvix.stt import STT
from arvix.telegram import templates
from arvix.telegram.api import TelegramAPI, TelegramError
from arvix.telegram.bot import Bot
from arvix.telegram.scheduler import Scheduler
from arvix.web.hub import Hub
from arvix.web.server import start_web

log = logging.getLogger("arvix.daemon")
POLL_SECONDS = 20
TICK_SECONDS = 5  # планировщик: напоминания, таймер, панель
MAX_PAUSE = 20  # после обрыва сети бот возвращается не позже чем через 20 с


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(name)s %(levelname)s %(message)s")
    cfg = load_config()
    tg = cfg.section("telegram")
    if not tg.get("token") or not tg.get("owner_id"):
        sys.exit("Telegram не настроен: запусти `arvix setup`.")
    core = Core(cfg)
    api = TelegramAPI(tg["token"])
    brain = Brain(cfg)
    if not brain.available():
        log.warning("claude CLI не найден (%s): бот будет отвечать только шаблонами L0", brain.bin)
    stt = STT(cfg)
    if stt.engine != "off" and not stt.enabled:
        log.warning("голосовые не работают: %s", stt.problem())
    bot = Bot(core, api, brain, int(tg["owner_id"]), stt=stt)
    scheduler = Scheduler(bot)
    app_url = str(cfg.section("web").get("public_url") or "").rstrip("/")
    api.app_url = app_url + "/" if app_url else ""
    def setup_menu() -> None:
        # В фоне: на нестабильной сети два вызова Telegram ждали таймауты по 40 с, и бот с приложением
        # стартовали через полторы минуты. Меню — косметика, ждать его незачем.
        try:
            api.set_commands(templates.COMMANDS)  # меню «/» пустое: говорят словами (D23)
            api.set_menu_button(api.app_url)      # кнопка слева от поля ввода открывает приложение
        except TelegramError as exc:
            log.warning("меню не установлено: %s", exc)

    threading.Thread(target=setup_menu, name="tg-menu", daemon=True).start()
    hub = Hub()
    bot.more_incoming = hub.chat_waiting  # ответ на сообщение, за которым уже есть новые, — цитатой (D52)
    web = start_web(cfg, hub)  # приложение и API — в том же процессе (arvix/web)

    stopping = threading.Event()

    def stop(*_: object) -> None:
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def handle(update: dict) -> Callable[[Bot], None]:
        def run(b: Bot) -> None:
            b.core.store.kv_set("tg_offset", update["update_id"] + 1)  # до обработки: упавший апдейт не зациклит бота
            b.handle(update)
        return run

    def poll() -> None:
        """Отдельный поток: только ждёт Telegram и кладёт апдейты в общую очередь."""
        offset = start_offset
        pause = 1
        while not stopping.is_set():
            try:
                updates = api.get_updates(offset, timeout=POLL_SECONDS)
                pause = 1
            except TelegramError as exc:
                log.warning("Telegram недоступен: %s — пауза %s с", exc, pause)
                stopping.wait(pause)
                pause = min(pause * 2, MAX_PAUSE)
                continue
            for update in updates:
                offset = update["update_id"] + 1
                hub.post(handle(update), label=f"update {update.get('update_id')}", chat=bool(update.get("message")))

    start_offset = int(core.store.kv_get("tg_offset", 0))
    threading.Thread(target=poll, name="tg-poll", daemon=True).start()
    log.info("Arvix в Telegram запущен, владелец %s", tg["owner_id"])
    last_tick = 0.0
    while not stopping.is_set():
        hub.run_pending(bot, timeout=1.0)
        if time.monotonic() - last_tick >= TICK_SECONDS:
            last_tick = time.monotonic()
            try:
                scheduler.tick()
            except Exception:
                log.exception("ошибка планировщика")
    if web is not None:
        web.shutdown()
    log.info("Остановлен")


if __name__ == "__main__":
    main()
