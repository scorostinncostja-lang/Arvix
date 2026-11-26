# ARCHITECTURE.md — карта кода Arvix для агентов (Claude Code и Codex)

Общий файл для обоих агентов. Правила работы — в [AGENTS.md](AGENTS.md) (общие; Claude Code подключает их из
[CLAUDE.md](CLAUDE.md)), план большой задачи — по [PLANS.md](PLANS.md).
Здесь — **где в коде что лежит, как по нему идут данные и что трогать, когда меняешь X**.

Что и почему система делает — в [docs/01-ARCHITECTURE.md](docs/01-ARCHITECTURE.md) и остальных `docs/`. Этот файл
их не пересказывает, а ведёт от спецификации к функциям. Разошёлся с кодом — правь в том же PR, что и код.

## 1. Картина за 30 секунд

```
 Telegram ─┐                                   ┌─ claude -p  (голова: один вызов на сообщение, JSON по схеме)
 Mini App ─┼─ arvix-telegram (VPS, systemd) ───┤
 PWA      ─┘   daemon → Hub → Bot → Core       └─ Obsidian-хранилище (профиль, цели, конспекты, заметки дня)
                                  │
 Claude Code / Desktop ── MCP ────┤
 CLI arvix ───────────────────────┤   все процессы — один пакет arvix/, свой экземпляр Core
                                  ▼
                       SQLite arvix.db: таблица events (append-only) + runtime (транспорт)
```

- **Один пакет** `arvix-claude/arvix/`, Python 3.11+, только стандартная библиотека.
- **Одна база** — журнал событий. Состояние нигде не хранится: `State` собирается свёрткой журнала в памяти.
- **Несколько процессов** (бот, MCP, CLI, хук) открывают ту же базу; запись сериализует `BEGIN IMMEDIATE`.
- **Удалённый режим**: на ноутбуке с `[remote] host` MCP/CLI/хук не открывают базу, а через `remote.exec_remote`
  запускают тот же скрипт на сервере по SSH. Код один, база одна.

## 2. Процессы и точки входа

| Процесс | Вход | Что внутри |
|---|---|---|
| Служба бота `arvix-telegram` | `scripts/arvix_telegram.py` → `telegram/daemon.py:main` | поток опроса Telegram + HTTP-сервер приложения кладут работу в `web/hub.py:Hub`; **главный поток** один исполняет очередь и раз в 5 с `Scheduler.tick()` |
| MCP-сервер (Claude Code, Desktop) | `scripts/arvix_mcp.py` → `mcp_server.py:serve` | JSON-RPC по stdin/stdout, 12 инструментов `TOOLS` → функции `t_<имя>` |
| Хук и строка состояния Claude Code | `scripts/arvix_hook.py` → `hooks.py:run`; `statusline.py` | подкладывают состояние в сессию (`prompt.hook_context`) |
| CLI `arvix` | `scripts/arvix_cli.py` → `cli.py` | всё без ИИ: статус, сон, траты, setup, doctor, rebuild |
| Сборка файлов | `scripts/build_assets.py` | из `constitution/` генерирует `output-styles/arvix.md` и `deploy/claude-ai/*` |

Внутри службы бота **все изменения идут через главный поток** (`Hub.call` / `Hub.post`). Потоки HTTP и опроса
сами `Core` не меняют. Новая ручка приложения — тоже `hub.call(lambda bot: …)`, а не прямой вызов.

## 3. Данные: журнал → свёртка

```python
with core.tx():                                   # BEGIN IMMEDIATE + refresh: догнать чужие события
    core.emit("task_completed", {...}, source="telegram", entity_id=task.id)
    #  └─ store.append()  → строка в events (UPDATE/DELETE запрещены триггерами)
    #  └─ state.apply(ev) → State._on_task_completed(ev, payload, day)
```

- `store.py` — только `events` и `runtime`. `runtime` — транспорт (offset Telegram, ожидание ответа, кэш хука),
  **не** доменное состояние: задач и режима там нет.
- `state.py` — `State.apply` вызывает обработчик `_on_<kind>`. Нет обработчика — событие лежит в журнале,
  но на состояние не влияет (так задуманы чисто журнальные события).
- `core.py:Core` — единственный слой записи. Каждая операция (`add_task`, `complete_task`, `log_sleep`, `set_goal`…)
  проверяет ввод, открывает `tx()`, пишет события. Ошибка → `ArvixError` с текстом для человека; память
  откатывается вслед за базой (`State.rebuild`).
- `Core.refresh()` — подтянуть события других процессов и `daily.catch_up` (закрыть прошедшие дни, материализовать
  сегодняшние задачи, пересчитать режим). Вызывается в начале любого входа.
- Время — только `core.now()` / `clock.now()`. Тесты подменяют его `clock.set_now`; `datetime.now()` в логике ломает тесты.

## 4. Путь сообщения (по функциям)

```
telegram/daemon.py   поток опроса getUpdates → hub.post(...)
web/api.py           POST из приложения       → hub.post(...)
        ▼  главный поток
telegram/bot.py      Bot.handle → владелец? (owner_id) → core.refresh() → Bot.dispatch
                     Bot.on_text: safety-маркеры (safety.py, L0)
                              → Bot.on_await: ждём отчёт / причину / сон / разбор / интервью? — ответ кодом (L0)
                              → иначе Bot.converse (L1):
                                   prompt.voice_prompt(core, …)   системный промпт + context.build_context
                                   Brain.ask(schema=VOICE_SCHEMA) claude -p → {reply, actions, learning, …}
                                   валидаторы: 🟥 gentle_violation → перегенерация; learning без источника → перегенерация
                                   brain.apply_actions → Core.<операция> → события
                                   Bot.run_ui_actions                 → действия интерфейса (план, таймер, экраны)
                                   Bot.reply(reply + «✅ записано / ⚠️ отказано»)
```

- Голова недоступна (`Brain.ask` → `None`) — шаблон `templates.FALLBACK`; L0 работает дальше.
- `apply_actions` исполняет только типы из закрытого `brain.ACTION_TYPES`. Всё, что от `plan_schedule` и дальше, —
  `UI_ACTIONS`, их исполняет бот, а не `Core`.
- Модель никогда не пишет в базу сама. Её «руки» — `ACTION_TYPES` в боте и `TOOLS` в MCP; оба идут через `Core`.

Проактив (без ИИ, кроме разбора и ретро): `telegram/scheduler.py:Scheduler.tick` → `brief`, `reminders`, `midday`,
`initiative`, `bedtime`, `debrief`, `retro`… Каждое сообщение отправляется один раз: ключ `message_out.key` и `_once`
с окном опоздания. L2 (`debrief`, `retro`) — роль `analyst` в фоне, ответ человеку не ждёт его.

## 5. Карта модулей

Слой: **L0** — без модели, **L1** — голос, **L2** — совет, **IO** — транспорт и интерфейсы.

| Модуль | Слой | Отвечает за |
|---|---|---|
| `store.py` | — | SQLite-журнал, триггеры append-only, `runtime` |
| `state.py` | — | `State`, `Task`, `Day`; свёртка `_on_<kind>` |
| `core.py` | L0 | все операции записи, `tx/emit`, режим, бюджет, статус |
| `rules.py` | L0 | формулы: режим Burnout Guard, заморозка, доказательство выполнения |
| `daily.py` | L0 | `catch_up`, `close_day`, `materialize`, пересмотр нагрузки |
| `load.py` | L0 | автонагрузка: множители, недельная нагрузка |
| `checks.py`, `safety.py` | L0 | проверки ввода («не верит на слово»), safety-маркеры |
| `initiative.py` | L0 | D59: когда Arvix пишет первым |
| `guide.py`, `tools.py` | L0/L1 | D62: шаги «сделай → инструмент → минуты», список инструментов человека |
| `interview.py` | L0 | вопросы знакомства и их порядок |
| `memory.py`, `graph.py` | L0 | факты памяти, поиск по основам слов, граф заметок |
| `vault.py`, `daily_note.py`, `export.py`, `files.py` | IO | Obsidian: безопасная запись заметок, заметка дня, экспорт, файлы |
| `context.py` | L1 | контекст-пакет для головы (числа из `Core`, модель их только читает) |
| `prompt.py` | L1 | системный промпт из `constitution/` + `fewshot.json`; мягкий режим; генерация стиля |
| `brain.py` | L1/L2 | `Brain.ask` (claude -p), схемы ответов, `ACTION_TYPES`, `apply_actions` |
| `telegram/bot.py` | IO | весь диалог: входящие, кнопки, таймер, ожидания, `converse` |
| `telegram/scheduler.py` | L0 | проактив по часам |
| `telegram/templates.py`, `fmt.py`, `api.py`, `daemon.py` | IO | тексты L0, разметка, Bot API, главный цикл |
| `web/server.py`, `api.py`, `auth.py`, `hub.py` | IO | HTTP приложения, проверка initData/токена, одна очередь |
| `web/static/` | IO | Mini App/PWA: `app.js`, `app.css`, `sw.js` (кэш оболочки) |
| `mcp_server.py`, `hooks.py`, `statusline.py` | IO | Claude Code и Desktop |
| `cli.py`, `tui.py` | IO | терминал |
| `remote.py` | IO | удалённый режим по SSH |
| `stt.py`, `tts.py`, `weather.py` | IO | голос, погода |
| `config.py`, `defaults.toml`, `clock.py` | — | конфиг (имена моделей — только здесь и у пользователя), время |

Вокруг пакета: `skills/` (9 скиллов плагина), `head-skills/` (навыки головы в Telegram, D33), `hooks/hooks.json`,
`output-styles/` (генерируется), `.claude-plugin/`, `.mcp.json`, `deploy/` (установка, сервер, бэкапы, systemd),
`tests/` (unittest, без сети и ИИ; база — `tests/helpers.py:ArvixCase`), `GUIDE.md` (руководство пользователя).
Корень репозитория: `docs/` (спецификация), `README.md` (витрина, местами устарел — правда в `docs/`).

Учебные темы доступны через `web/api.py:study` и `learning_focus.py`.
Событие `study_focus_step` хранит последний результат темы и срок следующей проверки.

## 6. Инварианты и кто их держит

| Инвариант | Где держится | Тест |
|---|---|---|
| Журнал только дописывается | триггеры в `store.SCHEMA` | `tests/test_core.py` |
| Запись только через `Core.emit()` в `Core.tx()` | ревью; в `bot.py`/`web/`/`mcp_server.py` нет SQL | — (следи сам) |
| Нет имён моделей в коде | `defaults.toml [roles.*]` | `test_prompt_safety.test_no_model_names_in_code` |
| В 🟥 и без ментора нет жёстких блоков в промпте | `prompt.is_gentle`, `tone_block`, `fewshot(gentle=…)` | `tests/test_prompt_safety.py` |
| Нет игры (XP, HP, уровни, серии) | D41 | `tests/test_no_game.py` |
| Отвечаем только владельцу | `Bot.handle`, `web/auth.py` | `test_strangers_are_ignored`, `tests/test_web_is_user.py` |
| Сгенерированные файлы свежие | `scripts/build_assets.py` | `build_assets.py --check` и тест |
| `:hover` только под `(min-width: 900px) and (hover: hover)` | `app.css` | `test_laptop.test_hover_styles_only_for_a_real_pointer` |

## 7. Рецепты: меняешь X — трогай Y

**Новый тип события.** `Core.<операция>` → `emit("<kind>", …)`; обработчик `State._on_<kind>` (если влияет на
состояние); строка в каталоге `docs/03-DATA-MODEL.md`. Тест: событие пишется и свёртка даёт нужное состояние
после `State.rebuild` (то есть и после перезапуска).

**Новая формула или порог** (долг, режим, нагрузка). Только `rules.py` / `daily.py` / `load.py`, не промпт.
Описание — `docs/02-MECHANICS.md`. Модель число лишь читает через `context.py`.

**Новое действие модели в Telegram.** `brain.ACTION_TYPES` (данные — до `plan_schedule`, интерфейс — после),
`ACTION_RU`, ветка в `apply_actions` (или в `Bot.run_ui_actions` для интерфейса), описание в `constitution/`,
пересборка `build_assets.py`, `docs/04-AI-LAYER.md`. Тест: выдуманный id → честный отказ в ответе.

**Новый MCP-инструмент.** `mcp_server.TOOLS` + функция `t_<имя>` через операции `Core`; число инструментов
упомянуто в `docs/01` и `docs/05` — обнови. Тест — в `tests/test_mcp.py`.

**Новый проактив.** Метод `Scheduler`, вызов в `tick()` с учётом `quiet`/`red`, ключ дедупликации. Тексты — в
`templates.py`. Проверь: после сна ноутбука сообщение не уходит дважды и не уходит слишком поздно.

**Тон, правила голоса.** `arvix/constitution/*.md`, `fewshot.json` → `python3 scripts/build_assets.py`.
Жёсткое — только в блоках, которые `prompt.py` выкидывает в мягком режиме.

**Приложение.** Ручка в `web/api.py` через `hub.call`; интерфейс в `web/static/app.js`/`app.css`;
**подними `CACHE = "arvix-vNN"` в `sw.js`**, иначе телефон покажет старую оболочку. Проверяй в браузере как человек,
а не только тестом.

**Заметки Obsidian.** Только через `Core.write_note` / `write_block` / `save_note` (→ `vault.py`): чужой текст не
перезаписывается без `force`, удалений нет.

## 8. Не трогать

`archive/v1-docker/` (старый прототип), `firmware/` (заморожен), `.claude/worktrees/` (чужие рабочие копии),
настоящая база `~/.local/share/arvix/arvix.db` и конфиг `~/.config/arvix/` — тесты и CLI только на временных
`ARVIX_DATA_DIR` / `ARVIX_CONFIG_DIR`.

## 9. Два агента в одном репозитории

Кто где работает, префиксы веток, номера `D<N>` и горячие файлы — [AGENTS.md](AGENTS.md) §1 и §5.
Большую задачу ведут по плану в `plans/` ([PLANS.md](PLANS.md)) — так её может продолжить второй агент.
Поменял карту (новый модуль, процесс, точка входа, инвариант) — обнови этот файл в том же PR.
