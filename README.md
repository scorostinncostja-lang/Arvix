# Arvix

Личный ИИ-ментор для одного владельца (single-user): планирует день, напоминает о задачах,
считает XP/HP, следит за режимом нагрузки (Burnout Guard) и разговаривает через Telegram.
Подробное видение — в [docs/00-VISION.md](docs/00-VISION.md).

## Концепция L0 / L1 / L2

| Слой | Роль | Правило |
|------|------|---------|
| **L0 — Рефлексы** | Чистый детерминированный Python: таймеры, напоминания, расчёт XP/HP, Burnout Guard, квоты | Если задачу решает формула или шаблон — ИИ не вызывается |
| **L1 — Голос** | Быстрый ответ пользователю (< 1.5 с), максимум 1–2 итерации вызова tools | XP/HP не считает — только вызывает tools из L0 |
| **L2 — Совет** | Тяжёлая аналитика (Analyst, Planner, Chief) | Только в фоне, никогда не в цепочке ответа; результат пишет в `directives` |

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

Спецификация лежит в `docs/`:

- [00-VISION.md](docs/00-VISION.md) — видение и принципы
- [01-ARCHITECTURE.md](docs/01-ARCHITECTURE.md) — архитектура, три слоя
- [02-MECHANICS.md](docs/02-MECHANICS.md) — механики (задачи, XP/HP, режимы)
- [03-DATA-MODEL.md](docs/03-DATA-MODEL.md) — модель данных, Event Log и проекции
- [04-AI-LAYER.md](docs/04-AI-LAYER.md) — ИИ-слой
- [05-BOT-TWA.md](docs/05-BOT-TWA.md) — бот и Telegram Web App
- [06-IOT-BIOMETRICS.md](docs/06-IOT-BIOMETRICS.md) — IoT и биометрия
- [07-SECOND-BRAIN.md](docs/07-SECOND-BRAIN.md) — второй мозг и обучение
- [08-ROADMAP.md](docs/08-ROADMAP.md) — фазы реализации
- [09-PHASE-0-1-PLAN.md](docs/09-PHASE-0-1-PLAN.md) — пошаговый план фаз 0 и 1
- [10-ESP32-BUILD.md](docs/10-ESP32-BUILD.md) — сборка умного таймера

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

> **Важно:** образ `core` копирует код при сборке (`COPY core`, `COPY tests`), а `docker-compose.yml`
> не монтирует исходники. После правок кода или тестов выполните `make up`, иначе `make test`
> и `make lint` отработают на старой копии.

`/health` отвечает 200 — на нём построен healthcheck контейнера `core`.

## Лицензия

См. [LICENSE](LICENSE).
