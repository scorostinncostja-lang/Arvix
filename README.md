# Arvix

Личный ИИ-ментор для одного владельца (single-user): раскладывает цели на результаты недели
и задачи с критерием готовности, напоминает, помогает начать, принимает честный отчёт, проводит
вечерний разбор и недельное планирование, учит по роадмапам с интервальными повторениями,
следит за режимом нагрузки (Burnout Guard) и разговаривает через Telegram.
Подробное видение — в [docs/00-VISION.md](docs/00-VISION.md), индекс спецификации — в [docs/README.md](docs/README.md).

## Концепция L0 / L1 / L2

| Слой | Роль | Правило |
|------|------|---------|
| **L0 — Рефлексы** | Чистый детерминированный Python: тикер и напоминания, протокол старта, метрики, долг, Burnout Guard, расписание повторений | Если задачу решает формула или шаблон — ИИ не вызывается |
| **L1 — Голос** | Ответ пользователю за секунды, максимум 2 круга вызова tools | Метрики не считает и состояние текстом не меняет — только вызывает tools из L0 |
| **L2 — Фон** | Тяжёлая аналитика и исследование (роли `thinker`, `researcher`) | Только в фоне, никогда не в цепочке ответа; результат пишет в `directives` |

Состояние хранится как **Event Log + проекции**: любое изменение идёт через `emit()` в
`core/events/log.py`, прямые `UPDATE` проекций (`state_current`, `state_daily`, `state_weekly`) запрещены.
Инвариант «`rebuild()` = накопленный `apply()`» проверяется в `tests/test_projections.py`.

## Стек

Версии — из `pyproject.toml` и `docker-compose.yml`:

- Python 3.12+, FastAPI + uvicorn, aiogram 3.x
- PostgreSQL 16 (образ `pgvector/pgvector:pg16`), SQLAlchemy 2.0 async + asyncpg, Alembic
- Redis 7, APScheduler
- LLM: единый клиент `openai.AsyncOpenAI` для всех провайдеров; модели и параметры — в `core/ai/roles.yaml`
- Caddy (реверс-прокси, TLS)
- Тесты и линтер: pytest + pytest-asyncio, ruff

## Структура

```
core/            # пакет приложения
  ai/            # провайдеры, router, constitution, context, tools
  api/           # FastAPI: авторизация Telegram initData и т.д.
  bot/           # aiogram: handlers, keyboards, templates, states
  db/            # модели SQLAlchemy, сессия, миграции
  domain/        # бизнес-логика (tasks, ...)
  events/        # log.py (emit), kinds.py, projections.py
  scheduler/     # APScheduler-задачи, materialize
  utils/
tests/           # pytest
docs/            # спецификация
firmware/        # ESP32
```

## Документация

Спецификация лежит в `docs/` (ревизия 2.0), начинать с [docs/README.md](docs/README.md):

- [00-VISION.md](docs/00-VISION.md) — видение, принципы, фильтр псевдопродуктивности
- [01-ARCHITECTURE.md](docs/01-ARCHITECTURE.md) — архитектура, три слоя, надёжность, безопасность
- [02-MECHANICS.md](docs/02-MECHANICS.md) — цели, неделя, задачи, протокол старта, долг, режимы, метрики
- [03-DATA-MODEL.md](docs/03-DATA-MODEL.md) — модель данных, Event Log, проекции, машина состояний
- [04-AI-LAYER.md](docs/04-AI-LAYER.md) — ИИ-слой, конституция, режимы помощи, инструменты
- [05-BOT-TWA.md](docs/05-BOT-TWA.md) — бот и Telegram Web App
- [06-IOT-BIOMETRICS.md](docs/06-IOT-BIOMETRICS.md) — чек-ин состояния, биометрия, ESP32
- [07-SECOND-BRAIN.md](docs/07-SECOND-BRAIN.md) — обучение, повторения, языки, Obsidian
- [08-ROADMAP.md](docs/08-ROADMAP.md) — фазы реализации
- [09-PHASE-0-1-PLAN.md](docs/09-PHASE-0-1-PLAN.md) — пошаговый план фаз 0 и 1 со статусом
- [10-ESP32-BUILD.md](docs/10-ESP32-BUILD.md) — сборка умного таймера
- [11-INTEGRATIONS.md](docs/11-INTEGRATIONS.md) — веб-поиск, MCP, календарь
- [12-DECISIONS.md](docs/12-DECISIONS.md) — журнал решений, найденные баги, открытые вопросы
- [13-AGENT-PLATFORM.md](docs/13-AGENT-PLATFORM.md) — скиллы, память, самодоработка, сервер, Google Диск, YouTube, блокноты источников, точность

Правила для ИИ-ассистента — в `CLAUDE.md` и `.clinerules/`.

## Запуск

```bash
cp .env.example .env     # заполнить BOT_TOKEN, OWNER_ID, POSTGRES_PASSWORD, ключи провайдеров
make up                  # docker compose up -d --build
make migrate             # alembic upgrade head
make test                # pytest внутри контейнера core
make lint                # ruff check core внутри контейнера core
```

Остальные цели `Makefile`: `make down`, `make logs`, `make revision m="описание"`.

> **Важно:** `docker-compose.yml` монтирует `./core` и `./tests` в контейнер, поэтому правки кода
> видны без пересборки (uvicorn без `--reload` — после правок перезапусти `core`: `docker compose restart core`).
> Пересборка (`make up`) нужна после изменения зависимостей в `pyproject.toml` или `Dockerfile`.

`/health` отвечает 200 — на нём построен healthcheck контейнера `core`.

## Лицензия

См. [LICENSE](LICENSE).
