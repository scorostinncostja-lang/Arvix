"""Главный цикл Telegram-бота: long polling + тик планировщика.

getUpdates ждёт до 20 секунд — это и есть «часы» планировщика. Ошибки сети
(ноутбук проснулся без Wi-Fi) переживаются с экспоненциальной паузой.
"""

from __future__ import annotations

import logging
import signal
import sys
import time

from arvix.brain import Brain
from arvix.config import load_config
from arvix.core import Core
from arvix.telegram.api import TelegramAPI, TelegramError
from arvix.telegram.bot import Bot
from arvix.telegram.scheduler import Scheduler

log = logging.getLogger("arvix.daemon")
POLL_SECONDS = 20
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
    bot = Bot(core, api, brain, int(tg["owner_id"]))
    scheduler = Scheduler(bot)

    stopping = False
    waiting = True  # ждём сеть или long poll — прерывать можно сразу

    def stop(*_: object) -> None:
        nonlocal stopping
        stopping = True
        if waiting:
            raise SystemExit(0)  # иначе getUpdates/sleep держат процесс и systemd убивает его по таймауту

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    offset = int(core.store.kv_get("tg_offset", 0))
    pause = 1
    log.info("Арвикс в Telegram запущен, владелец %s", tg["owner_id"])
    while not stopping:
        waiting = True
        try:
            updates = api.get_updates(offset, timeout=POLL_SECONDS)
            pause = 1
        except TelegramError as exc:
            log.warning("Telegram недоступен: %s — пауза %s с", exc, pause)
            time.sleep(pause)
            pause = min(pause * 2, MAX_PAUSE)
            updates = []
        waiting = False
        for update in updates:
            offset = update["update_id"] + 1
            core.store.kv_set("tg_offset", offset)  # до обработки: упавший апдейт не зациклит бота
            try:
                bot.handle(update)
            except Exception:
                log.exception("ошибка обработки апдейта %s", update.get("update_id"))
        try:
            scheduler.tick()
        except Exception:
            log.exception("ошибка планировщика")
    log.info("Остановлен")


if __name__ == "__main__":
    main()
