# AGENTS.md — правила для Codex (и любого другого ИИ-агента) в репозитории Arvix

Тот же свод, что [CLAUDE.md](CLAUDE.md) для Claude Code. Если файлы разошлись — прав `CLAUDE.md` и `docs/`,
а расхождение надо исправить в том же PR. Владелец — один человек, школьник, пишет по-русски; отвечай по-русски,
коротко, без воды, с конкретными командами.

## 1. Что такое Arvix

Личный ИИ-ментор **одного** человека. Знает план дня и цели, сам напоминает в Telegram, спрашивает результат,
считает долг и режим нагрузки кодом, вечером проводит разбор, раз в неделю — ретро. Данные человека — в его
Obsidian. Голова — `claude -p` по подписке Claude (без API-ключей). С D62 Arvix — **навигатор по инструментам
человека** (Решу ОГЭ, ФИПИ, Anki, NotebookLM…): даёт шаги «сделай → в каком инструменте → сколько минут»,
а не строит свои аналоги.

Пять лиц на одном ядре и одной базе:

| Лицо | Где в коде |
|---|---|
| Telegram-бот (long polling, systemd `arvix-telegram`, живёт на VPS) | `arvix/telegram/` |
| Приложение: Mini App в Telegram, PWA на телефоне/ноутбуке | `arvix/web/` (API в процессе бота), `arvix/web/static/` |
| Плагин Claude Code: стиль, 9 скиллов, MCP-инструменты, хуки, строка состояния | `.claude-plugin/`, `skills/`, `hooks/`, `output-styles/`, `arvix/mcp_server.py`, `arvix/hooks.py`, `arvix/statusline.py` |
| Чат Claude Desktop (те же MCP-инструменты) | `arvix/mcp_server.py` |
| CLI `arvix` (без ИИ: статус, отчёты, doctor, setup, rebuild) | `arvix/cli.py`, `scripts/arvix_cli.py` |

Три слоя: **L0** — рефлексы, чистый Python без модели; **L1** — голос, ровно один вызов модели на сообщение,
модель возвращает `{reply, actions}`, actions исполняет код; **L2** — совет (разбор, ретро), только в фоне.

## 2. Прочитай перед работой

Обязательно (один раз за сессию): `docs/README.md` → `docs/00-VISION.md` → `docs/01-ARCHITECTURE.md`.
Плюс профильный документ задачи:

| Задача про… | Документ |
|---|---|
| задачи, долг, Burnout Guard, закрытие дня, формулы | `docs/02-MECHANICS.md` |
| журнал событий, каталог событий, свёртка | `docs/03-DATA-MODEL.md` |
| промпт, actions, валидаторы, память, роли моделей | `docs/04-AI-LAYER.md` |
| Telegram, приложение, Claude Code, CLI | `docs/05-INTERFACES.md` |
| учёба, роадмапы, конспекты | `docs/06-LEARNING.md` |
| установка, конфиг, сервер, бэкапы, голос | `docs/07-OPERATIONS.md` |
| что делать дальше | `docs/08-ROADMAP.md` |
| «почему так», решения D1–D62, открытые вопросы | `docs/09-DECISIONS.md` |

Корневой `README.md` местами устарел (упоминает XP/HP — их убрали в D41). Правда — в `docs/`.

## 3. Карта репозитория

```
AGENTS.md, CLAUDE.md     правила для агентов
README.md, LICENSE       витрина (Apache-2.0)
docs/                    спецификация «что и почему» (00–10)
arvix-claude/            ПРОДУКТ — вся работа здесь
  arvix/                 ядро, Python 3.11+, только стандартная библиотека
    core.py              операции с проверками; Core.tx() + Core.emit() — единственный путь записи
    store.py             SQLite-журнал events (append-only, триггеры запрещают UPDATE/DELETE)
    state.py             State — свёртка журнала в памяти
    rules.py daily.py load.py   L0: долг, режим, закрытие дня, автонагрузка
    checks.py safety.py  проверки ввода («не верит на слово»), safety-маркеры
    prompt.py context.py brain.py   промпт L1, контекст-пакет, вызов головы и apply_actions
    memory.py vault.py daily_note.py export.py graph.py   память, Obsidian, заметка дня, граф
    guide.py tools.py    D62: шаги «Как сделать» и список инструментов человека
    initiative.py        D59: Arvix пишет первым
    interview.py         знакомство (52 вопроса)
    remote.py            удалённый режим: CLI/MCP ноутбука выполняются на сервере по SSH
    stt.py tts.py weather.py files.py   голос, погода, файлы
    defaults.toml        значения по умолчанию, ИМЕНА МОДЕЛЕЙ — только тут ([roles.*])
    constitution/*.md, fewshot.json   конституция голоса; из неё генерируются стиль и файлы claude.ai
    telegram/            bot.py (главный, большой), scheduler.py (проактив), templates.py, daemon.py, api.py, fmt.py
    web/                 server.py, api.py, hub.py (одна очередь изменений), auth.py, static/ (app.js, app.css, sw.js)
  skills/ head-skills/ hooks/ output-styles/ .claude-plugin/ .mcp.json   плагин Claude Code
  scripts/               arvix_cli.py, arvix_mcp.py, arvix_hook.py, arvix_telegram.py, build_assets.py, make_icons.py
  deploy/                install.sh, sync-server.sh, server-setup.sh, restore-server.sh, web-setup.sh,
                         server-claude-token.sh, systemd-юниты, бэкап, синхронизация хранилища, claude-ai/
  tests/                 unittest, ~460 тестов, без сети и без ИИ
  GUIDE.md               руководство пользователя «как»
firmware/                ESP32-таймер — заморожен, не трогать
archive/v1-docker/       старый прототип — не трогать, не запускать, не брать оттуда код
.claude/worktrees/       рабочие копии сессий Claude Code — чужие, не трогать
```

## 4. Незыблемые правила (нарушение = PR не принимается)

1. **Всё, что можно сделать кодом, делается кодом.** Модель — только где нужно понимание языка или суждение.
   Долг, режим, напоминания, нагрузка — детерминированный Python. Игры нет: ни XP, ни HP, ни уровней, ни серий (D41).
2. **L2 никогда не стоит в цепочке ответа.** Ответ в чате — один вызов L1.
3. **Любое изменение состояния — событие через `Core.emit()` внутри `Core.tx()`.** Прямой SQL в `events` запрещён;
   исправление — компенсирующее событие. Новый тип события — в каталог `docs/03-DATA-MODEL.md` и в свёртку `state.py`.
4. **Имена моделей — только в `arvix/defaults.toml` и конфиге пользователя.** В коде их нет — это проверяет тест.
5. **В 🟥 КРАСНОМ и при выключенном менторе** жёсткие тон-блоки, жёсткие примеры и `decision_rule` физически
   не попадают в промпт. Проверяет `tests/test_prompt_safety.py`.
6. **Один человек.** Бот отвечает только `owner_id`. Никакой мультитенантности, ролей, регистрации, биллинга.
7. **Без зависимостей.** Только стандартная библиотека Python. Нет Docker, Postgres, Redis, очередей, WebSocket,
   векторной БД, нескольких LLM-провайдеров (см. «Чего не будет» в `docs/08-ROADMAP.md`).
8. **Фильтр пяти вопросов** из `docs/00-VISION.md §6`: фича, не прошедшая его, не делается — скажи владельцу прямо.

## 5. Как работать

- Задача = один пункт `docs/08-ROADMAP.md` или явная просьба владельца. Один пункт = одна ветка = один PR.
  Не забегай к следующему пункту и не «улучшай заодно».
- Ветка: `codex/<короткая-тема>` от свежего `origin/main`.
- Каждое изменение поведения — **с тестом, который падает на прежнем коде**, и с правкой спецификации в том же PR.
  Документ, расходящийся с кодом, хуже его отсутствия.
- Решение, меняющее принцип, — строкой `D<N>` в `docs/09-DECISIONS.md` §2. Номер бери следующий после
  последнего **в `origin/main`** (`git fetch && git show origin/main:docs/09-DECISIONS.md | grep -o 'D[0-9]\+' | sort -V | tail -1`):
  параллельные ветки Claude Code тоже занимают номера, коллизии уже были.
- Нашёл противоречие в спецификации — запиши в `docs/09-DECISIONS.md` §6 «Открытые вопросы» и спроси владельца,
  если от ответа зависит, что строить.
- Правил `arvix/constitution/*` — пересобери `python3 scripts/build_assets.py` (тест следит за актуальностью).
- Правил `arvix/web/static/*` — подними версию кэша `CACHE = "arvix-vNN"` в `sw.js`, иначе телефон покажет старую
  оболочку. Все `:hover` в `app.css` — только в одном блоке `(min-width:900px) and (hover:hover)` (есть тест).
- Коммит, пуш, PR — только когда владелец попросил. В конце коммита строка `Co-Authored-By` — по его правилам.
- Секреты в git не попадают: `~/.config/arvix/config.toml`, `claude.env`, `.env`, токены, ключи голоса.
  Репозиторий **публичный**.

## 6. Команды (из `arvix-claude/`)

```bash
python3 -m unittest discover -s tests -t .                          # все тесты, без сети и ИИ (~35 с)
python3 -W error::ResourceWarning -m unittest discover -s tests -t . # строже — так проверяй перед PR
python3 -m unittest tests.test_rules -v                              # один модуль
python3 scripts/build_assets.py --check                              # сгенерированные файлы не устарели
claude plugin validate .                                             # манифест плагина (если есть claude CLI)
```

Проверка поведения без Telegram и без настоящих данных — CLI на временной базе:
```bash
ARVIX_LOCAL=1 ARVIX_DATA_DIR=/tmp/a ARVIX_CONFIG_DIR=/tmp/c python3 scripts/arvix_cli.py status
```

Никогда не запускай тесты или CLI против настоящей базы `~/.local/share/arvix/arvix.db`.

## 7. Где что живёт на машинах владельца (для понимания, не для правки)

| Что | Где |
|---|---|
| Журнал событий (источник правды) | сервер: `~/.local/share/arvix/arvix.db` (SQLite, WAL) |
| Конфиг и токен бота | `~/.config/arvix/config.toml`, права 600 |
| Вход в Claude для головы на сервере | `~/.config/arvix/claude.env`, права 600 |
| Установленная копия плагина | `~/.local/share/arvix/app` (её ставит `deploy/install.sh`) |
| Хранилище Obsidian | ноутбук ↔ сервер `~/vault`, `rsync` раз в 2 мин |
| Бэкапы журнала | ноутбук: `~/.local/share/arvix/backups/` (каждый час, 30 дней) |

Схема: бот, приложение и журнал — на VPS под пользователем `arvix` (Ubuntu 24.04, systemd --user).
Ноутбук (CachyOS) — в удалённом режиме: `[remote] host` в конфиге, MCP/CLI/хук ходят на сервер по SSH.
Приложение снаружи — Caddy, `https://<ip-через-дефисы>.sslip.io:8443`.

## 8. Деплой — только владелец или по его явной команде

Деплой перезапускает живого бота. Только после мержа PR и с явного «да» владельца в этом же разговоре:
```bash
bash arvix-claude/deploy/install.sh                 # ноутбук
bash arvix-claude/deploy/sync-server.sh arvix@HOST  # сервер: код → install.sh → рестарт бота
```
У облачного Codex нет доступа к серверу и не должно быть. Не подключайся к серверу, не читай его конфиг,
не трогай `deploy/restore-server.sh` без задачи.

## 9. Чего не делать

- Не возвращать то, что убрано решениями: XP/HP/уровни (D41), вкладки «Проекты» и «Обучение» (D62), звонок (D52),
  пузырьки сообщений (D46), свои тесты/плееры/карточки вместо инструментов человека (D62).
- Не строить платформу агентов, мультимодельный совет, Android-проект, TWA, вебхуки.
- Не обходить ограничения YouTube (PO-токен) для субтитров — решено не делать.
- Не дописывать фичи без недели реального использования предыдущих: правило `docs/08-ROADMAP.md` «польза раньше фич».
