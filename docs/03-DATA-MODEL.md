# 03 · Модель данных

## 1. Принцип: Event Log + проекции

Всё, что происходит, пишется в **append-only** таблицу `events`. Состояние (XP, HP, стрики, статистика) — **производное**, считается из событий.

Почему так:
- Формулы XP/HP будут меняться (они точно будут меняться) — с логом ты пересчитываешь историю, а не теряешь её
- Любой отчёт за любой период строится из одной таблицы
- Analyst получает сырую ленту, а не чью-то интерпретацию
- Невозможно «потерять» историю кривым UPDATE

```sql
CREATE TABLE events (
    id          BIGSERIAL PRIMARY KEY,
    at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    local_date  DATE NOT NULL,              -- дата в Europe/Moscow, для группировок
    kind        TEXT NOT NULL,
    entity_id   UUID,                       -- на что ссылается (task, goal, expense...)
    payload     JSONB NOT NULL DEFAULT '{}',
    source      TEXT NOT NULL,              -- user | bot | twa | esp32 | scheduler | l2
    CONSTRAINT  events_kind_check CHECK (kind <> '')
);
CREATE INDEX ON events (local_date);
CREATE INDEX ON events (kind, at DESC);
CREATE INDEX ON events USING GIN (payload);
```

### Каталог событий

| kind | payload | source |
|---|---|---|
| `task_created` | task snapshot | user/twa/l2 |
| `task_started` | task_id, at | user/esp32 |
| `task_completed` | task_id, quality, proof_kind, xp | user |
| `task_failed` | task_id, reason | user/scheduler |
| `task_deferred` | task_id, to | user |
| `task_debted` | task_id | scheduler |
| `proof_submitted` | task_id, kind, file_id, exif_ok, phash, verdict | user |
| `proof_suspicious` | task_id, flags[] | l0 |
| `sleep_recorded` | duration_min, bedtime, quality, source | user/bridge |
| `biometrics_recorded` | steps, hr_avg, hr_rest, spo2, stress, source | bridge |
| `focus_session` | duration_min, device, task_id, interruptions | esp32/twa |
| `xp_awarded` / `hp_changed` | amount, reason, balance_after | l0 |
| `shield_used` | reason, damage_prevented | l0 |
| `mode_changed` | from, to, trigger | l0 |
| `quota_met` / `quota_missed` | sphere, target, actual | l0 |
| `expense_logged` | amount, category, impulse | user |
| `directive_created` | directive snapshot | l2 |
| `insight` | text, evidence[] | l2 |
| `debrief_completed` | answers, rating | user |
| `silent_day_result` | completion, notes | l0 |
| `message_in` / `message_out` | text, tokens, model, latency_ms | bot |
| `learning_question` | question, answered_with_hint \| answered_directly | l1 |
| `safety_flag` | level, note | l0 |

### Проекции

Материализованные таблицы, обновляются транзакционно вместе с записью события. Полный пересчёт из лога доступен командой `arvix rebuild-projections`.

- `state_daily(local_date, completion_pct, deep_minutes, sleep_min, xp, hp_end, sp, mode)`
- `state_current(xp_total, level, hp, streak_days, season_id, sp_avg, mode, autonomy_score)`
- `state_weekly(week_start, budget_used_min, deep_min, quotas JSONB, expenses JSONB)`

---

## 2. Основные таблицы

```sql
-- Профиль (одна строка)
CREATE TABLE profile (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    name TEXT, birth_date DATE, city TEXT, country TEXT,
    institution TEXT, height_cm INT, weight_kg NUMERIC(5,2),
    timezone TEXT DEFAULT 'Europe/Moscow',
    sleep_target_min INT DEFAULT 465,
    bedtime_target TIME DEFAULT '23:30',
    wake_target TIME DEFAULT '07:15',
    mentor_enabled BOOLEAN DEFAULT true,   -- выключается safety-контуром
    onboarding_stage TEXT DEFAULT 'core',
    extra JSONB DEFAULT '{}',              -- всё, что Арвикс дособрал в диалоге
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Цели и мечты (иерархия)
CREATE TABLE goals (
    id UUID PRIMARY KEY, parent_id UUID REFERENCES goals(id),
    title TEXT NOT NULL, kind TEXT,         -- dream | main | yearly | quarterly | milestone
    sphere TEXT, why TEXT,                  -- зачем — обязательное поле
    metric TEXT, target_value NUMERIC, current_value NUMERIC,
    deadline DATE, status TEXT DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Слабости, страхи, привычки — собираются интервью, не формой
CREATE TABLE traits (
    id UUID PRIMARY KEY,
    kind TEXT NOT NULL,                     -- fear | weakness | bad_habit | good_habit | trigger
    title TEXT NOT NULL, description TEXT,
    severity SMALLINT,                      -- 1..5
    counter_strategy TEXT,                  -- что делаем, когда срабатывает
    status TEXT DEFAULT 'active',
    last_triggered_at TIMESTAMPTZ
);

-- Шаблоны расписания
CREATE TABLE day_templates (
    id UUID PRIMARY KEY, kind TEXT,         -- study | work | deep | recovery | silent
    weekday SMALLINT,                       -- 0..6, null = не привязан
    blocks JSONB NOT NULL                   -- [{start, duration, sphere, title, deep_work}]
);

CREATE TABLE tasks (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL, sphere TEXT NOT NULL,
    importance SMALLINT NOT NULL, difficulty SMALLINT NOT NULL,
    planned_start TIMESTAMPTZ, planned_duration_min INT,
    deep_work BOOLEAN DEFAULT false,
    proof TEXT NOT NULL DEFAULT 'confirm',
    status TEXT NOT NULL DEFAULT 'planned',
    actual_start TIMESTAMPTZ, actual_end TIMESTAMPTZ,
    quality SMALLINT, goal_id UUID REFERENCES goals(id),
    source TEXT DEFAULT 'user', recurrence JSONB,
    debt_since DATE,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON tasks (planned_start);
CREATE INDEX ON tasks (status) WHERE status IN ('planned','active','debt');

CREATE TABLE directives (
    id UUID PRIMARY KEY, kind TEXT NOT NULL,
    text TEXT NOT NULL, voice_hint TEXT,
    priority SMALLINT DEFAULT 3,
    evidence JSONB,                          -- ссылки на события, на которых основана
    valid_until DATE, created_by TEXT,       -- какая роль совета породила
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE biometrics (
    local_date DATE PRIMARY KEY,
    sleep_min INT, deep_sleep_min INT, bedtime TIME, wake_time TIME,
    sleep_quality SMALLINT, hr_rest INT, hr_avg INT,
    spo2 SMALLINT, stress_avg SMALLINT, steps INT, active_min INT,
    source TEXT NOT NULL,                    -- manual | healthconnect | export
    raw JSONB
);

CREATE TABLE expenses (
    id UUID PRIMARY KEY, amount NUMERIC(12,2) NOT NULL,
    currency TEXT DEFAULT 'RUB', category TEXT NOT NULL,
    note TEXT, impulse BOOLEAN DEFAULT false,
    at TIMESTAMPTZ DEFAULT now(), goal_id UUID REFERENCES goals(id)
);

CREATE TABLE seasons (
    id SERIAL PRIMARY KEY, started_on DATE, ends_on DATE,
    start_rank TEXT, final_rank TEXT, sp_avg NUMERIC(5,2)
);

CREATE TABLE devices (
    id UUID PRIMARY KEY, kind TEXT,          -- esp32 | android_bridge
    name TEXT, token UUID NOT NULL UNIQUE,
    last_seen_at TIMESTAMPTZ, firmware TEXT
);

-- Заметки Obsidian: чанки + вектор
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

-- Долговременная память Арвикса о пользователе (факты, не диалоги)
CREATE TABLE memory_facts (
    id UUID PRIMARY KEY, topic TEXT NOT NULL,
    fact TEXT NOT NULL, confidence SMALLINT DEFAULT 3,
    source_event_id BIGINT, embedding vector(768),
    valid_until DATE, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE roadmaps (
    id UUID PRIMARY KEY, title TEXT, goal_id UUID REFERENCES goals(id),
    status TEXT DEFAULT 'active',
    nodes JSONB NOT NULL,   -- [{id, title, sources[], est_hours, deps[], status, checkpoint}]
    created_at TIMESTAMPTZ DEFAULT now(), reviewed_at TIMESTAMPTZ
);
```

---

## 3. Инварианты, которые проверяются тестами

1. Пересчёт проекций из `events` даёт те же числа, что накопленное состояние — **всегда**
2. `hp` ∈ [0, 100], `xp_total` монотонно не убывает
3. Задача не может перейти `done → planned` (только новое событие с новой задачей)
4. Сумма `xp_awarded` = `state_current.xp_total`
5. Ни одно событие не удаляется и не редактируется. Исправление = компенсирующее событие
6. Каждая директива имеет `evidence` — минимум один `event_id`. Директива без доказательств отклоняется
7. При `mentor_enabled = false` ни один тон-блок «жёсткий» не попадает в промпт (проверяется юнит-тестом на сборщике контекста)

---

## 4. Экспорт

`/export` и еженедельный cron генерируют в Obsidian-репозиторий:

```
Arvix/
  Daily/2026-09-11.md          # разбор дня, метрики, события
  Weekly/2026-W37.md           # ретро
  Goals/<goal>.md              # цель, прогресс, связанные задачи
  Roadmaps/<title>.md          # роадмап в виде чеклиста
  Insights.md                  # накопленные выводы Analyst
  _raw/events.jsonl            # полный лог
  _raw/dump.sql.gz             # дамп БД
```

Формат — обычный Markdown с YAML frontmatter, читается Obsidian напрямую. Это и бэкап, и второй мозг, и гарантия, что ты не заперт в чужой базе.
