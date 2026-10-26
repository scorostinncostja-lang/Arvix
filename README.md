# Arvix

**Arvix** — личный ИИ-ментор и productivity-система для одного пользователя (single-user). Помогает планировать день, отслеживать задачи, управлять энергией и защищать от выгорания.

## Концепция: трёхуровневая архитектура (L0/L1/L2)

- **L0 (Рефлексы)** — детерминированные операции без ИИ: расчёт XP/HP, Burnout Guard, таймеры, квоты, напоминания. Если задача решается формулой или шаблоном — ИИ не вызывается.
- **L1 (Голос)** — быстрый диалоговый интерфейс в Telegram (<1.5 сек), использует LLM для понимания запросов и формулирования ответов. Не считает XP/HP самостоятельно — вызывает инструменты (tools) из L0.
- **L2 (Совет)** — тяжёлая аналитика (Analyst, Planner, Chief), работает в фоне/воркере, никогда не блокирует ответ пользователю. Результаты записываются в таблицу `directives`.

## Стек технологий

- **Backend**: Python 3.12+, FastAPI, aiogram 3.x
- **БД**: PostgreSQL 16 (с pgvector), SQLAlchemy 2.0 (async)
- **Кеш**: Redis 7
- **Frontend**: React + Vite (Telegram Web App)
- **Embedded**: ESP32 (PlatformIO) — в будущем

## Архитектурные принципы

1. **Event Sourcing** — любое изменение состояния проходит через `core/events/log.py -> emit()`. Прямые UPDATE проекций запрещены.
2. **Универсальный AI-клиент** — все LLM-провайдеры (Groq, Gemini, DeepSeek, OpenRouter, APINET) подключаются через единый `AsyncOpenAI`-совместимый интерфейс.
3. **Burnout Guard** — в режиме RED (🟥) и при `mentor_enabled = false` жёсткие тон-блоки исключаются из контекста. Это тестируется.
4. **Single-User** — строго один владелец (`OWNER_ID`), никакой мультитенантности.

## Структура проекта

```
arvix/
├── core/                    # Основной пакет (бот + API + WS)
│   ├── main.py              # Точка входа
│   ├── config.py            # Конфигурация через Pydantic Settings
│   ├── db/                  # SQLAlchemy модели и миграции
│   ├── events/              # Event log и проекции
│   ├── domain/              # Бизнес-логика (tasks, ledger, guard, quotas)
│   ├── ai/                  # LLM-клиенты, роутер, конституция, tools
│   ├── bot/                 # Telegram bot (aiogram 3.x)
│   ├── api/                 # REST API + WebSocket
│   └── scheduler/           # APScheduler задачи
├── worker/                  # Фоновые задачи L2 (будущее)
├── twa/                     # React фронтенд (Telegram Web App)
├── firmware/                # ESP32 прошивка (будущее)
├── tests/                   # Тесты
└── docs/                    # Документация и спецификация
```

## Документация

Полная спецификация системы находится в директории `docs/`:

- `00-VISION.md` — видение и философия проекта
- `01-ARCHITECTURE.md` — архитектура L0/L1/L2, Event Sourcing
- `02-MECHANICS.md` — игровая механика (XP, HP, стрики, режимы, квоты)
- `03-DATA-MODEL.md` — модель данных и проекции
- `04-AI-STACK.md` — LLM-провайдеры, роли моделей, конституция
- `05-VOICE-L1.md` — диалоговый интерфейс в Telegram
- `06-REFLEXES-L0.md` — детерминированная логика без ИИ
- `07-COUNCIL-L2.md` — фоновая аналитика (Analyst, Planner, Chief)
- `08-TWA-FRONTEND.md` — веб-интерфейс
- `09-PHASE-0-1-PLAN.md` — детальный план реализации по шагам

## Быстрый старт

### Требования

- Docker & Docker Compose
- Python 3.12+
- Node.js 18+ (для фронтенда)

### Установка

1. Склонируйте репозиторий:
```bash
git clone <repo-url>
cd arvix
```

2. Скопируйте `.env.example` в `.env` и заполните переменные:
```bash
cp .env.example .env
# Отредактируйте .env: укажите BOT_TOKEN, OWNER_ID, API ключи
```

3. Поднимите инфраструктуру:
```bash
make up
```

4. Выполните миграции:
```bash
make migrate
```

### Команды разработки

```bash
make up        # Запустить все сервисы (docker compose up -d --build)
make down      # Остановить все сервисы
make logs      # Смотреть логи core-сервиса
make migrate   # Применить миграции Alembic
make test      # Запустить тесты (pytest)
make lint      # Проверить код линтером (ruff check)
```

### Проверка работы

После запуска система должна быть доступна:
- **Telegram Bot**: найдите своего бота в Telegram и отправьте `/start`
- **Health Check**: `https://your-domain.com/health` → 200 OK
- **API Docs**: `https://your-domain.com/docs` (FastAPI Swagger UI)

## Разработка

### Правила работы

1. **Event Sourcing**: все изменения состояния через `emit()` в `core/events/log.py`
2. **Строгая типизация**: type hints везде, используем `mypy` / `ruff`
3. **Тестирование**: каждый новый функционал покрывается тестами
4. **По шагам**: работаем строго по одному шагу из `docs/09-PHASE-0-1-PLAN.md`

### Правила для Cline/Claude Code

См. файлы в `.clinerules/`:
- `01-architecture-invariants.md` — незыблемые архитектурные правила
- `02-coding-standards.md` — стандарты кода и стека
- `03-git-and-testing.md` — workflow разработки
- `workflows/implement-step.md` — как реализовывать шаги из плана
- `workflows/pre-commit-check.md` — что проверять перед коммитом

## Текущий статус

**Фаза 0**: Базовая инфраструктура и модель данных
- ✅ Шаг 0.1: Docker Compose, PostgreSQL, Redis, Alembic
- ✅ Шаг 0.2: Модели данных, Event Log, проекции, тест инварианта
- 🚧 Шаг 0.3: Бот (скелет и онбординг) — в разработке

## Лицензия

Проект находится в разработке и предназначен для личного использования.

## Контакты

Создатель: [имя]  
GitHub: [ссылка]
