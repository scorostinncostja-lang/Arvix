#!/usr/bin/env python3
"""Приложение на временной базе — посмотреть интерфейс без Telegram, без ИИ и без живых данных.

    python3 scripts/demo_web.py [порт]      → http://127.0.0.1:8799/?tab=projects#t=<ключ>

Цели, распорядок и проект — примерные (похожие на настоящие, с дублями), голова — подставная: на «собрать
систему» отвечает готовым планом, в чате — коротким ответом. Всё живёт в /tmp и исчезает после остановки.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="arvix-demo-"))
os.environ["ARVIX_DATA_DIR"] = str(TMP / "data")
os.environ["ARVIX_CONFIG_DIR"] = str(TMP / "cfg")
os.environ["ARVIX_LOCAL"] = "1"

from arvix import projects  # noqa: E402
from arvix.config import load_config  # noqa: E402
from arvix.core import Core  # noqa: E402
from arvix.store import Store  # noqa: E402
from arvix.telegram.bot import Bot  # noqa: E402
from arvix.web.auth import app_token  # noqa: E402
from arvix.web.hub import Hub  # noqa: E402
from arvix.web.server import Server, WebApp, make_handler  # noqa: E402

OWNER = 1


class QuietAPI:
    """Telegram, который никуда не шлёт: ответы и так видны в приложении через журнал."""

    app_url = ""

    def __getattr__(self, name: str) -> Any:
        def call(*args: Any, **kwargs: Any) -> Any:
            return 1
        return call


class DemoBrain:
    last_error = ""
    bin = "demo"

    def available(self) -> bool:
        return True

    def supports(self, flag: str) -> bool:
        return False

    def ask(self, **kw: Any) -> dict[str, Any]:
        time.sleep(1.5)
        schema = kw.get("schema") or {}
        props = schema.get("properties", {})
        if "diagnosis" in props:
            return {"diagnosis": "За 4 недели на цель — 0 минут: ни одного блока в распорядке, срок есть, а дороги к нему нет.",
                    "summary": "Сначала ежедневная короткая привычка, чтобы цель двигалась без силы воли; пробник — чтобы знать "
                               "реальный уровень; тема — самое слабое место.",
                    "items": [
                        {"type": "habit", "title": "ОГЭ информатика: 2 задачи", "why": "ежедневная практика", "weekdays": [0, 1, 2, 3, 4],
                         "start": "17:00", "duration": 30, "sphere": "learning", "deep_work": True},
                        {"type": "task", "title": "Пробник ОГЭ по информатике на ФИПИ", "why": "узнать реальный уровень", "duration": 90},
                        {"type": "learn", "title": "Python: циклы и списки (задание 16)", "why": "слабое место",
                         "sources": ["ФИПИ — открытый банк заданий"]},
                        {"type": "fix_goal", "title": "Метрика", "why": "проверяемость", "metric": "пробник ≥ 18 баллов из 21"}]}
        return {"reply": "Принял. Записал в проект и поставил следующий шаг.", "actions": []}


def seed(core: Core) -> None:
    goals = [("Жизнь со своей компанией, путешествия по миру, атлетичное тело", "dream", None),
             ("Собственная компания и путешествия по миру", "dream", None),
             ("Сдать ОГЭ по русскому, математике, информатике и физике с максимальным баллом", "main", "2027-06-15"),
             ("Сдать ОГЭ на высшие баллы: информатика, физика и обязательные предметы", "yearly", None),
             ("Поступить в Stanford/MIT на EECS с полным покрытием", "yearly", "2029-01-01"),
             ("Поступить в Stanford или MIT", "yearly", None),
             ("Уровень B2 по английскому", "yearly", "2027-08-01"),
             ("Рельефное, накачанное и выносливое тело", "yearly", None),
             ("Попасть в школу Газпром (г. Бишкек)", "yearly", None),
             ("Запустить личный блог", "quarterly", None)]
    ids = {}
    for title, kind, deadline in goals:
        ids[title] = core.set_goal(title, why="это важно для меня", kind=kind, deadline=deadline, source="demo")
    week = [{"start": "08:00", "duration": 360, "title": "Школа", "fixed": True},
            {"start": "15:00", "duration": 60, "title": "Английский", "sphere": "learning"},
            {"start": "18:30", "duration": 60, "title": "Спортзал", "sphere": "sport"}]
    core.set_template([0, 1, 2, 3, 4], "study", week, source="demo")
    core.set_template([5, 6], "recovery", [{"start": "11:00", "duration": 90, "title": "Проект", "sphere": "project"}], source="demo")
    core.profile_set("bedtime_target", "23:00", source="demo")
    core.profile_set("wake_target", "07:00", source="demo")
    pid = projects.set_project(core, "Калькулятор совместимости ПК", why="портфолио и Python", expectation="сайт, 10 пользователей",
                               goal_id=ids["Поступить в Stanford/MIT на EECS с полным покрытием"], weekly_min=180, source="demo")
    projects.set_milestone(core, pid, "Прототип в терминале", dod="считает 3 сборки", source="demo")
    projects.set_milestone(core, pid, "Веб-версия", dod="ссылка работает", source="demo")
    projects.write_note(core, pid, "План", "# План\n\n- [ ] прототип\n- [ ] веб\n\nИдея: брать цены из DNS.", source="demo")
    projects.set_learn(core, "Flask: маршруты и шаблоны", project_ref=pid, why="веб-версия", source="demo")


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    vault = TMP / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    cfg = load_config()
    cfg.raw["vault"] = str(vault)
    cfg.raw["timezone"] = "Europe/Moscow"
    cfg.raw["telegram"] = {"token": "0:demo", "owner_id": OWNER}
    core = Core(cfg, Store(TMP / "arvix.db", shared=True))
    seed(core)
    bot = Bot(core, QuietAPI(), DemoBrain(), OWNER)
    hub = Hub()
    app = WebApp(cfg, hub, core=core)
    server = Server(("127.0.0.1", port), make_handler(app))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"http://127.0.0.1:{port}/?tab=projects#t={app_token(core)}", flush=True)
    while True:
        with app.lock:
            hub.run_pending(bot, 0.05)
        time.sleep(0.01)


if __name__ == "__main__":
    main()
