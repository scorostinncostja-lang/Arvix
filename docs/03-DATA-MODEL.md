# 03 · Модель данных

## 1. Принцип: гибридная модель «сущности + event log + проекции»

Три вида таблиц. Путать их нельзя — от этого зависит, что можно менять напрямую, а что нет.

| Вид | Примеры | Как меняется | Пересчитывается из лога? |
|---|---|---|---|
| **Event log** | `events` | Только `INSERT` через `emit()`. Никогда `UPDATE`/`DELETE` | — (это и есть источник) |
| **Сущности** | `tasks`, `goals`, `profile`, `weekly_plans`, `roadmaps`, `srs_cards`, `inbox_items`, `traits`, `memory_facts`, `directives` | Текущее состояние объекта. Меняется доменным кодом, **и каждое изменение сопровождается событием в той же транзакции** | Нет (но лог содержит всю историю изменений) |
| **Проекции** | `state_daily`, `state_weekly`, `state_current` | **Только** через `projections.apply(event)`. Прямой `UPDATE` запрещён | Да: `rebuild()` пересоздаёт их из лога |
| **Технические** | `outbox`, `calendar_busy`, `note_chunks` | Свободно, это инфраструктура, а не бизнес-состояние | Нет |

Почему так, а не «чистый event sourcing»: восстанавливать каждую задачу из ленты событий при каждом чтении — сложно и не нужно одному пользователю. Сущности дают простые запросы, лог даёт историю и аналитику, проекции дают быстрые агрегаты, которые можно пересчитать при смене формулы.

**Правило для кода:** доменная функция, меняющая сущность, обязана вызвать `emit()` в той же сессии до `commit`. Тест-инвариант проверяет, что после каждой доменной операции появилось ожидаемое событие.

```sql
CREATE TABLE events (
    id          BIGSERIAL PRIMARY KEY,
    at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    local_date  DATE NOT NULL,              -- дата в поясе профиля, для группировок
    kind        TEXT NOT NULL,
    entity_id   UUID,                       -- на что ссылается (task, goal, ...)
    payload     JSONB NOT NULL DEFAULT '{}',
    source      TEXT NOT NULL,              -- user | twa | bot | l1 | l2 | scheduler | esp32 | integration
    CONSTRAINT  events_kind_check CHECK (kind <> '')
);
CREATE INDEX ON events (local_date);
CREATE INDEX ON events (kind, at DESC);
CREATE INDEX ON events (entity_id);
CREATE INDEX ON events USING GIN (payload);
```

`local_date` вычисляется в поясе из `profile.timezone` (через единую функцию времени), а не из захардкоженного `Europe/Moscow`.

---

## 2. Каталог событий

`kind` — значение `EventKind` в `core/events/kinds.py`. Payload каждого вида описан Pydantic-моделью (`core/events/payloads.py`) и валидируется в `emit()` — событие с неправильным payload не пишется.

**Обязательное поле всех `task_*` событий: `planned_date`** — локальная дата задачи. Без него проекция не знает, к какому дню отнести исход (баг B8).

### Задачи
| kind | payload |
|---|---|
| `task_created` | snapshot задачи (title, outcome, sphere, importance, planned_start, duration, deep_work, proof, source, goal_id, weekly_outcome_id, planned_date) |
| `task_updated` | changed: {field: [old, new]} |
| `task_rescheduled` | from, to, reason, advance_min, planned_date (новая), prev_planned_date |
| `task_started` | at, planned_date, delay_min |
| `task_completed` | result: `done`\|`partial`, report?, left?, planned_date, actual_min |
| `task_failed` | reason_code, note?, planned_date |
| `task_cancelled` | reason, advance_min, planned_date |
| `task_debted` | planned_date, decision_due |
| `debt_resolved` | how: `done`\|`rescheduled`\|`split`\|`dropped`, reason? |
| `start_missed` | planned_date (T+25 без старта) |
| `start_protocol` | reason_code, response? |
| `reminder_sent` | task_id, type: `t_minus_5`\|`t0`\|`t10`\|`end` |

### Планирование и ритуалы
| kind | payload |
|---|---|
| `checkin_recorded` | sleep_min, bedtime, wake_time, energy, stress?, source |
| `plan_confirmed` | date, task_ids[], auto: bool |
| `weekly_plan_confirmed` | week_start, outcomes[], capacity_min, planned_min |
| `weekly_outcome_closed` | outcome_id, status: `done`\|`dropped`, reason? |
| `weekly_review_completed` | week_start, answer |
| `debrief_started` / `debrief_completed` / `debrief_missed` | date |
| `debrief_answered` | date, question, answer |
| `monthly_review_completed` | month, notes |
| `witness_report_generated` | week_start, forwarded: bool |

### Цели и профиль
| kind | payload |
|---|---|
| `profile_updated` | changed: {field: [old, new]} |
| `onboarding_stage_changed` | from, to |
| `goal_created` / `goal_updated` | snapshot / changed |
| `goal_status_changed` | from, to, reason |
| `lead_measure_logged` | goal_id, measure, value, source |
| `trait_recorded` | snapshot (кроме чувствительных полей — только id) |

### Состояние и безопасность
| kind | payload |
|---|---|
| `mode_changed` | from, to, trigger |
| `mentor_toggled` | enabled, by: `safety`\|`user` |
| `safety_flag` | level, marker_kind (без текста сообщения) |
| `silence_day` | day_n |
| `silent_day_started` / `silent_day_result` | date / completion, notes |
| `focus_session` | duration_min, device, task_id, interruptions |
| `biometrics_recorded` | steps, hr_rest, spo2, source (фаза 5) |

### Обучение
| kind | payload |
|---|---|
| `learning_question` | topic, mode: `hint`\|`direct`, roadmap_node_id? |
| `roadmap_created` / `roadmap_node_status` | snapshot / node_id, from, to |
| `checkpoint_attempted` | node_id, kind, passed, gaps[] |
| `srs_card_created` | card_id, deck, source_ref |
| `srs_reviewed` | card_id, rating (1–4), elapsed_days, next_due |
| `language_session` | language, kind: `conversation`\|`writing`\|`input`\|`srs`, minutes, errors_n |

### Диалог, инструменты, фон
| kind | payload |
|---|---|
| `message_in` | text, via: `text`\|`voice` |
| `message_out` | text, role, model, provider, tokens_in, tokens_out, latency_ms, fallback_used |
| `tool_called` | name, args (после фильтра приватности), ok, latency_ms, confirmed_by_user? |
| `inbox_captured` / `inbox_processed` | item_id / action |
| `directive_created` / `directive_expired` | snapshot / id |
| `insight` | text, evidence[] |
| `memory_fact_added` / `memory_fact_superseded` | snapshot / old_id, new_id |

### Опционально
| kind | payload |
|---|---|
| `expense_logged` | amount, currency, category, impulse (модуль финансов) |

Исправление ошибочного события = **компенсирующее событие** (например, `task_updated` с исправлением), а не правка строки.

---

## 3. Проекции

Обновляются в той же транзакции, что и событие (`emit()` → `apply()`). Полный пересчёт: `python -m core.events.rebuild`.

```sql
CREATE TABLE state_daily (
    local_date        DATE PRIMARY KEY,
    planned           INT NOT NULL DEFAULT 0,   -- задачи с planned_date = день (без source=log)
    done              INT NOT NULL DEFAULT 0,
    partial           INT NOT NULL DEFAULT 0,
    failed            INT NOT NULL DEFAULT 0,
    cancelled_advance INT NOT NULL DEFAULT 0,
    started_on_time   INT NOT NULL DEFAULT 0,   -- старт ≤ T+10
    off_plan_done     INT NOT NULL DEFAULT 0,   -- source=log
    commitment_pct    NUMERIC(5,2),             -- формула 02-MECHANICS §9
    deep_minutes      INT NOT NULL DEFAULT 0,
    goal_minutes      INT NOT NULL DEFAULT 0,   -- задачи, связанные с целями
    sleep_min         INT,
    energy            SMALLINT,
    mode              TEXT,
    debrief_done      BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE state_weekly (
    week_start        DATE PRIMARY KEY,
    planned_min       INT NOT NULL DEFAULT 0,
    done_min          INT NOT NULL DEFAULT 0,
    deep_min          INT NOT NULL DEFAULT 0,
    outcomes_total    INT NOT NULL DEFAULT 0,
    outcomes_done     INT NOT NULL DEFAULT 0,
    lead_measures     JSONB NOT NULL DEFAULT '{}',  -- {goal_id: {measure: {target, actual}}}
    commitment_pct    NUMERIC(5,2)
);

CREATE TABLE state_current (
    id                SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    mode              TEXT NOT NULL DEFAULT 'normal',   -- normal | yellow | red
    mode_since        DATE,
    debrief_streak    INT NOT NULL DEFAULT 0,
    active_debt       INT NOT NULL DEFAULT 0,
    last_contact_at   TIMESTAMPTZ,
    silence_days      INT NOT NULL DEFAULT 0
);
```

`commitment_pct` пересчитывается в обработчике проекции после каждого `task_*` события своего дня — это чистая функция от счётчиков строки.

---

## 4. Машина состояний задачи

```
                ┌──────────── task_rescheduled (остаётся planned, новое время)
                ▼          │
  task_created → planned ──┼── task_started ──→ active ──┬── task_completed(done)    → done
                   │       │                             ├── task_completed(partial) → partial (+ хвост)
                   │       │                             └── task_failed             → failed
                   │       ├── task_completed (без старта: короткие confirm-задачи)   → done | partial
                   │       ├── task_failed                                             → failed
                   │       └── task_cancelled                                          → cancelled
                   │
  failed (importance ≥ 4) ── task_debted → debt ──┬── debt_resolved(done)        → done
                                                  ├── debt_resolved(rescheduled) → planned (debt_since сохраняется)
                                                  ├── debt_resolved(split)       → cancelled + новые задачи
                                                  └── debt_resolved(dropped)     → cancelled
```

- Конечные статусы: `done`, `partial`, `failed` (если не долг), `cancelled`. Из них переходов нет — исправление делается компенсирующим событием и новой задачей
- **Удаления задач нет.** `/day rebuild` отменяет (`cancelled`, reason=`rebuild`) нетронутые задачи шаблона, а не удаляет их (баг B10)
- Повторное действие над задачей в конечном статусе — не ошибка: доменная функция возвращает «уже в статусе X», событие не пишется (идемпотентность колбэков, баг B15)

---

## 5. Сущности

```sql
-- Профиль (одна строка)
CREATE TABLE profile (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    name TEXT, birth_date DATE, city TEXT,
    timezone TEXT NOT NULL DEFAULT 'Europe/Moscow',   -- источник истины для времени
    institution TEXT,
    sleep_target_min INT DEFAULT 465,
    bedtime_target TIME DEFAULT '23:30',
    wake_target TIME DEFAULT '07:15',
    mentor_enabled BOOLEAN NOT NULL DEFAULT true,     -- выключается safety-контуром
    onboarding_stage TEXT NOT NULL DEFAULT 'core',    -- core | interview | done
    emergency_number TEXT DEFAULT '112',
    trusted_contact TEXT,                             -- «брат, +7 ...» — только для safety
    witness_name TEXT,                                -- внешний свидетель, опционально
    languages JSONB DEFAULT '[]',                     -- [{lang, level, target_level, deadline}]
    extra JSONB DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE goals (
    id UUID PRIMARY KEY, parent_id UUID REFERENCES goals(id),
    title TEXT NOT NULL,
    kind TEXT NOT NULL,                     -- dream | year | quarter
    sphere TEXT, why TEXT NOT NULL,
    metric TEXT, target_value NUMERIC, current_value NUMERIC,
    deadline DATE,
    woop JSONB,                             -- {wish, outcome, obstacle, plan}
    lead_measures JSONB DEFAULT '[]',       -- [{name, unit, weekly_target, source}]
    status TEXT NOT NULL DEFAULT 'active',  -- active | paused | done | dropped
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE weekly_plans (
    week_start DATE PRIMARY KEY,
    outcomes JSONB NOT NULL DEFAULT '[]',   -- [{id, goal_id, text, dod, estimate_min, status}]
    capacity_min INT, planned_min INT,
    review_answer TEXT,
    confirmed_at TIMESTAMPTZ
);

-- Слабости, триггеры, привычки — собираются интервью; используются для планов «если-то»
CREATE TABLE traits (
    id UUID PRIMARY KEY,
    kind TEXT NOT NULL,                     -- trigger | weakness | bad_habit | good_habit | fear
    title TEXT NOT NULL, description TEXT,
    if_then TEXT,                           -- «если X — то Y»
    sensitive BOOLEAN NOT NULL DEFAULT false, -- fear и подобное: в контекст LLM только по релевантности
    status TEXT DEFAULT 'active',
    last_triggered_at TIMESTAMPTZ
);

CREATE TABLE day_templates (
    id UUID PRIMARY KEY,
    kind TEXT NOT NULL,                     -- study | work | free | recovery | silent
    weekdays SMALLINT[] DEFAULT '{}',       -- привязка к дням недели (0 = пн)
    blocks JSONB NOT NULL                   -- [{start, duration, type: slot|busy, slot_kind, sphere, label}]
);

CREATE TABLE tasks (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    outcome TEXT,                           -- DoD; обязателен для importance ≥ 3 и deep_work (проверка в домене)
    first_step TEXT,
    sphere TEXT NOT NULL,
    importance SMALLINT NOT NULL CHECK (importance BETWEEN 1 AND 5),
    estimate_min INT,
    planned_start TIMESTAMPTZ,
    planned_date DATE,                      -- локальная дата; задача без времени тоже может иметь дату
    planned_duration_min INT,
    deep_work BOOLEAN NOT NULL DEFAULT false,
    proof TEXT NOT NULL DEFAULT 'confirm',  -- none | confirm | report
    status TEXT NOT NULL DEFAULT 'planned', -- planned | active | done | partial | failed | debt | cancelled
    actual_start TIMESTAMPTZ, actual_end TIMESTAMPTZ,
    goal_id UUID REFERENCES goals(id),
    weekly_outcome_id UUID,
    roadmap_node_id TEXT,
    parent_task_id UUID REFERENCES tasks(id),
    source TEXT NOT NULL DEFAULT 'user',    -- plan | user | l1 | roadmap | debt | partial_tail | inbox | log
    defer_count SMALLINT NOT NULL DEFAULT 0,
    reschedule_count SMALLINT NOT NULL DEFAULT 0,
    debt_since DATE, debt_decision_due TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON tasks (planned_date);
CREATE INDEX ON tasks (planned_start);
CREATE INDEX ON tasks (status) WHERE status IN ('planned','active','debt');

CREATE TABLE inbox_items (
    id UUID PRIMARY KEY, text TEXT NOT NULL,
    via TEXT NOT NULL,                      -- text | voice | twa | l1
    status TEXT NOT NULL DEFAULT 'new',     -- new | task | note | question | dropped
    created_at TIMESTAMPTZ DEFAULT now(), processed_at TIMESTAMPTZ
);

CREATE TABLE directives (
    id UUID PRIMARY KEY, kind TEXT NOT NULL,
    text TEXT NOT NULL, voice_hint TEXT, question TEXT,
    priority SMALLINT NOT NULL DEFAULT 3,
    evidence BIGINT[] NOT NULL CHECK (cardinality(evidence) >= 1),  -- event ids
    valid_until DATE, created_by TEXT,      -- имя задания L2
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Долговременная память о пользователе (факты, не диалоги)
CREATE TABLE memory_facts (
    id UUID PRIMARY KEY, topic TEXT NOT NULL,
    fact TEXT NOT NULL,
    importance SMALLINT NOT NULL DEFAULT 3, -- 5 = всегда в контексте (главная цель и т. п.)
    confidence SMALLINT NOT NULL DEFAULT 3,
    source_event_id BIGINT, embedding vector(768),
    superseded_by UUID REFERENCES memory_facts(id),
    valid_until DATE, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE roadmaps (
    id UUID PRIMARY KEY, title TEXT NOT NULL, goal_id UUID REFERENCES goals(id),
    kind TEXT NOT NULL DEFAULT 'skill',     -- skill | language
    status TEXT DEFAULT 'active',
    nodes JSONB NOT NULL,                   -- структура — 07-SECOND-BRAIN §2.2
    created_at TIMESTAMPTZ DEFAULT now(), reviewed_at TIMESTAMPTZ
);

CREATE TABLE srs_cards (
    id UUID PRIMARY KEY,
    deck TEXT NOT NULL,                     -- «js», «en-vocab», ...
    front TEXT NOT NULL, back TEXT NOT NULL,
    source_ref TEXT,                        -- узел роадмапа / файл заметки / языковая сессия
    fsrs_state JSONB NOT NULL,              -- due, stability, difficulty, reps, lapses, state (py-fsrs)
    due TIMESTAMPTZ NOT NULL,
    suspended BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON srs_cards (due) WHERE NOT suspended;

CREATE TABLE biometrics (                   -- фаза 5; до неё сон/энергия живут в checkin_recorded
    local_date DATE PRIMARY KEY,
    sleep_min INT, bedtime TIME, wake_time TIME,
    energy SMALLINT, stress SMALLINT,
    hr_rest INT, steps INT, spo2 SMALLINT,
    source TEXT NOT NULL,                   -- manual | healthconnect | export
    raw JSONB
);

CREATE TABLE devices (
    id UUID PRIMARY KEY, kind TEXT,         -- esp32 | android_bridge
    name TEXT, token UUID NOT NULL UNIQUE,
    last_seen_at TIMESTAMPTZ, firmware TEXT
);
```

### Технические таблицы

```sql
-- Очередь исходящих сообщений (01-ARCHITECTURE §6)
CREATE TABLE outbox (
    id BIGSERIAL PRIMARY KEY,
    due_at TIMESTAMPTZ NOT NULL,
    kind TEXT NOT NULL,                     -- reminder | brief | debrief | nudge | text
    payload JSONB NOT NULL,                 -- текст, клавиатура, task_id
    dedupe_key TEXT NOT NULL UNIQUE,        -- «t5:<task_id>», «brief:2026-11-02»
    sent_at TIMESTAMPTZ, attempts SMALLINT NOT NULL DEFAULT 0, last_error TEXT
);
CREATE INDEX ON outbox (due_at) WHERE sent_at IS NULL;

-- Кэш занятости из ICS-календарей (11-INTEGRATIONS §4), пересоздаётся из фида
CREATE TABLE calendar_busy (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,                   -- имя фида
    starts_at TIMESTAMPTZ NOT NULL, ends_at TIMESTAMPTZ NOT NULL,
    title TEXT
);
CREATE INDEX ON calendar_busy (starts_at);

-- Заметки Obsidian: чанки + вектор (фаза 2)
CREATE TABLE note_chunks (
    id BIGSERIAL PRIMARY KEY,
    file_path TEXT NOT NULL, heading_path TEXT,
    content TEXT NOT NULL, tokens INT,
    content_hash TEXT NOT NULL,
    embedding vector(768),
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('russian', content)) STORED,
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON note_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON note_chunks USING GIN (tsv);
CREATE UNIQUE INDEX ON note_chunks (file_path, content_hash);
```

### Убрано из схемы v1.0
`seasons`; поля `xp_total`, `level`, `hp`, `season_id`, `sp_avg`, `autonomy_score` из `state_current`; `xp`, `hp_end`, `sp` из `state_daily`; `tasks.quality`, `tasks.difficulty`; `expenses` (переезжает в опциональный модуль). Причины — 12-DECISIONS D1, D2, D7, D15. Миграция — в шаге 0.R2.

---

## 6. Инварианты, которые проверяются тестами

1. `rebuild()` проекций из `events` даёт те же значения, что накопленный `apply()` — **всегда** (генерация 500 случайных валидных событий)
2. Каждая доменная операция над сущностью пишет ровно ожидаемые события в той же транзакции
3. Переходы статусов задачи — только по машине из §4. Недопустимый переход → исключение в домене, ноль событий
4. Ни одна задача не удаляется. Ни одно событие не удаляется и не редактируется
5. Каждое `task_*` событие содержит `planned_date`
6. Каждая директива имеет `evidence` ≥ 1 существующий `event_id`
7. При `mode = red` или `mentor_enabled = false` тон-блок НОРМЫ отсутствует в собранном промпте (юнит-тест на сборщике)
8. Повторный колбэк над задачей в конечном статусе не создаёт событий
9. `commitment_pct` не учитывает задачи `source=log` и отменённые заранее
10. Payload каждого события проходит валидацию своей Pydantic-модели

---

## 7. Экспорт

`/export` и еженедельный cron генерируют в Obsidian-репозиторий (папка `Arvix/`):

```
Arvix/
  Daily/2026-11-02.md          # план, исходы, ответы разбора
  Weekly/2026-W45.md           # результаты недели, метрики, ответ ревью
  Goals/<goal>.md              # цель, WOOP, показатели, связанные задачи
  Roadmaps/<title>.md          # роадмап чеклистом с источниками
  Insights.md                  # накопленные выводы фона с доказательствами
  _raw/events.jsonl            # полный лог
  _raw/dump.sql.gz.age         # зашифрованный дамп БД
```

Формат — Markdown с YAML frontmatter, читается Obsidian напрямую. Это и бэкап, и второй мозг, и гарантия, что ты не заперт в чужой базе. Чувствительные поля (`traits.sensitive`, safety) в Markdown не экспортируются — только в зашифрованный дамп.
