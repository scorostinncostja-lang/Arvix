# 03 · Модель данных

## 1. Принцип: журнал событий + свёртка

Всё, что происходит, пишется в **append-only** таблицу `events`. Состояние (задачи, долг, режим, профиль) —
производное: `State.rebuild(events)` сворачивает журнал с нуля, `State.apply(event)` — инкрементально.
Инвариант «rebuild = накопленный apply» проверяется тестом на случайной истории из 220 операций.

Почему так:
- правила будут меняться — с журналом история пересчитывается, а не теряется (так ушли XP и HP, D41: события остались, свёртка их не читает);
- любой отчёт за любой период строится из одной таблицы;
- аналитик получает сырую ленту с id событий, а не чью-то интерпретацию;
- невозможно «потерять» историю кривым UPDATE — его запрещает триггер.

```sql
-- arvix-claude/arvix/store.py
CREATE TABLE events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,            -- ISO 8601 с часовым поясом
    local_date  TEXT NOT NULL,            -- дата в часовом поясе человека, для группировок
    kind        TEXT NOT NULL CHECK (kind <> ''),
    entity_id   TEXT,                     -- id задачи, цели, факта…
    payload     TEXT NOT NULL DEFAULT '{}',  -- JSON
    source      TEXT NOT NULL             -- telegram | claude | cli | user | bot | scheduler | l0 | l1 | l2
);
CREATE INDEX ix_events_date ON events (local_date);
CREATE INDEX ix_events_kind ON events (kind, id);
CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

-- Транспортное состояние, не доменное: offset Telegram, чего бот ждёт, черновик распорядка, кэш хука.
CREATE TABLE runtime (key TEXT PRIMARY KEY, value TEXT NOT NULL);
```

Файл: `~/.local/share/arvix/arvix.db`, режим WAL, `busy_timeout` 15 с. Запись — только через `Core.emit` внутри
`Core.tx()` (`BEGIN IMMEDIATE`): при ошибке память откатывается вслед за базой полным пересчётом.

Источники `telegram`, `claude`, `cli`, `user` означают «человек что-то сделал сам» — это вход протокола игнора
(`USER_SOURCES`). `scheduler`, `l0`, `bot`, `l1`, `l2` — действия системы.

## 2. Каталог событий

Обработчики — методы `State._on_<kind>`. Событие без обработчика допустимо: оно остаётся в журнале для аналитика.

### Профиль и знакомство
| kind | payload | источник |
|---|---|---|
| `profile_set` | `key, value` — `name`, `address` (m/f), `city`, `timezone`, `bedtime_target`, `wake_target`, `bedtime_actual`, `wake_actual`, `sleep_target_min`, `main_goal`, `main_goal_why`, `support_person`, `week_budget_min`, `season_start`, `program_start`, `currency`, произвольные | интервью (l0), человек, модель |
| `interview_answer` | `qid, block, question, answer` | человек |
| `interview_skipped` / `interview_reset` | `qid` (+ `reason`) | человек |
| `goal_set` | `id, title, why, kind (dream·main·yearly·quarterly·milestone), deadline, metric, sphere, parent_id, status (active·done·dropped)` — повторное событие с тем же `id` обновляет; у цели верхнего уровня `why` обязательно, у этапа (`parent_id`) — нет | человек, модель |
| `trait_set` | `id, kind (fear·weakness·bad_habit·good_habit·trigger), title, description, severity 1–5, counter_strategy` | модель, человек |
| `fact_remembered` / `fact_retracted` | `id, topic, fact, confidence 1–5, valid_until` / `id, reason` | модель, человек |
| `template_set` | `weekdays[], day_type, blocks[{start, duration, title, sphere, importance, difficulty, deep_work, tags, fixed?}]` | человек, модель |
| `mentor_toggled` | `enabled, by` | **только человек** (CLI, `/mentor`) |

### День и задачи
| kind | payload | источник |
|---|---|---|
| `day_materialized` | `date, day_type` | scheduler |
| `task_created` | снимок задачи: `id, title, sphere, importance, difficulty, date, start, duration_min, deep_work, proof, source, tags, project?` (id проекта, D43) | человек, модель, scheduler |
| `task_started` | `id, at` | человек |
| `task_completed` | `id, done_pct, report, proof_kind, deep_min[, focus_min, doubts]` — `focus_min` есть, когда таймер покрыл ≥ половины блока; `xp` — только в событиях до 0.6 | человек, модель |
| `task_failed` | `id, reason, debt, hp` | человек, модель, scheduler (`no_report`) |
| `task_reason` | `id, reason` — причина, присланная позже | человек |
| `task_deferred` | `id, from, to, date, minutes` | человек, модель |
| `task_cancelled` | `id, reason` | человек, модель |
| `debt_written_off` | `id, justification` | человек, модель |
| `sleep_recorded` | `duration_min, bedtime, wake, date, source` — `wake` с 0.6: длительность из отбоя и подъёма считает код | человек, модель |
| `bedtime_noted` | `at, night` — «ложусь» (D48): `night` — дата утра, к которому относится ночь; сон из этого не пишется, только догадка | человек |
| `task_completed.photos` | пути фото отчёта в хранилище (D49), только внутри хранилища; `report` без слов — «фото-отчёт» | человек |
| `focus_session` | `duration_min, task_id, topic?` — с задачей копится в `Task.focus_min`, без задачи (тема «физика») идёт в глубокую работу дня; сессии дня — `Day.focus` | человек |
| `focus_noted` | `focus_event_id, date, note` — «что успел» к прошедшей сессии; сама сессия не меняется | человек |
| `file_received` | `name, kind, size, path, read, caption` — файл от человека в хранилище (`arvix/files.py`) | человек |
| `expense_logged` | `amount, currency, category, impulse, note` | человек, модель |
| `social_contact` | `who` | человек, модель |
| `reason_declared` | `reason` — причина плохого дня: важное, не сделанное в этот день, не уходит в долг | человек, модель |
| `silent_day` | `date` | человек, scheduler |
| `debrief_completed` | `date, answers, conclusion` | человек, модель |
| `learning_question` | `question, mode (hint·direct)` | модель |
| `note_captured` | `text, path` — Inbox | человек, модель |
| `note_written` | `path, sha, owned, mode, created, backup` — чтобы отличать свои заметки от чужих; `mode = edit \| create` — правка человека из приложения (`owned = false`) | l0, человек |

Шаги к задаче (D62): `task_guide` — `id, steps[{do, tool, min}], done, save, note, note_path` → `Task.guide`; пишет голова
(источник `l1`, из приложения — `web`), проверяет `guide.clean`.

Учебная тема (D64): `study_focus_step` хранит ключ и видимое название темы, связанный ID задачи (если есть),
результат, обратную связь, источник, схему, следующий шаг, заметку и дату повторения. Свёртка использует
последний шаг темы в `State.study_focus`. События D63 остаются читаемыми.

Старые события проектов и учебных сессий (D43–D61: `channel_set`, `learn_item_set`, `lesson_checked`, `lesson_started`, `milestone_set`, `project_logged`, `project_money`, `project_set`, `repo_activity`, `resource_set`, `review_answer`, `review_quiz`, `review_set`, `study_answer`, `study_fix`, `study_mine`, `study_panel`, `study_shadow`, `study_stage`) остаются в журнале;
с D62 свёртка их не читает, как XP и HP после D41.

### Режимы и итоги (пишет только код)
| kind | payload | источник |
|---|---|---|
| `xp_awarded` · `hp_changed` · `shield_used` · `protocol_zero` | **устарели (D41).** С 0.6 не пишутся; старые остаются в журнале, свёртка их не читает | — |
| `mode_changed` | `from, to, trigger` | l0, scheduler |
| `sos` | `on, until, note` — ручной 🟥 на 24 ч | человек, модель |
| `recovery_started` | `until` — человек нажал «Вернуться к плану»: до смены дня режим не выше 🟨, SOS снят (D38) | только человек (кнопка, MCP `mode resume` с подтверждением) |
| `safety_flag` | `level (high·critical), note` — выключает ментора; `info`/`low` в журнал не пишутся, а становятся фактом | l0, l1, модель |
| `quota_result` | `sphere, target, actual, met, week` | scheduler |
| `budget_set` | `week_min, deep_min, factors{}, streaks{}, verdict (up·down·hold), reason, change, from_*` | scheduler |
| `day_closed` | `date, completion, total, done, deep_min, sleep_min, ignored, frozen, mode`; до 0.6 ещё `sp, penalty_mult, hp_end` | scheduler |

### Совет и переписка
| kind | payload | источник |
|---|---|---|
| `directive_created` | `id, kind (focus·warning·schedule_change·insight·quota_push), text, voice_hint, priority 1–5, evidence[id…] ≥ 1, valid_until, created_by` | l2, модель |
| `insight` | `text, evidence[]` | l2, модель |
| `message_in` | `text, channel, [project], [reply_to], [tg_id]` | telegram, web |
| `message_out` | `text, key, channel, [buttons], [project], [reply_to], [tg_id]` — `key` дедуплицирует проактив (`brief:<дата>`, `rem5:<id>:<start>`, `debrief:<дата>`…) | bot |
| `message_reacted` | `message (id message_out), emoji, channel` — реакция человека; пустой `emoji` — снята. Одна на сообщение (D52) | telegram, web |
| `messages_read` | `upto, channel` — лента в приложении долистана до сообщения `upto`; только вперёд. Источник `seen` — не действие человека для протокола игнора | seen |

Переписка (`message_in`, `message_out`) хранится целиком, до 16 000 символов (D25); `channel` — `telegram`, `web` или
`terminal`; у `message_out` бывают `buttons` — приложение показывает те же кнопки. Ответ на сообщение (D52):
`reply_to` — id события-сообщения, на которое это ответ цитатой; `tg_id` — номер сообщения в Telegram, по нему
находится цитата человека и туда же Arvix отвечает цитатой (`Core.message`, `Core.message_by_tg`). «В сети» —
не событие: пульс приложения раз в 30 с пишется в runtime-ключ `presence {seen, since}` (`Core.presence_ping`):
история «был в сети» никому не нужна, а 2880 событий в сутки засорили бы журнал. Производные данные вне журнала:
FTS5-индекс `memory_fts` (поиск по памяти) и в runtime-таблице — ключ приложения `web_token`, кэш погоды, отметки
`dialog_day`, `last_in_at`, `curiosity_tried`. Ни задач, ни режима в них нет.

## 3. Состояние — `State`

```
profile{}            goals{id→}        traits{id→}       facts{id→}        directives{id→}
insights[]           templates{weekday→{day_type, blocks}}                 tasks{id→Task}
days{date→Day}       interview{qid→answer}  interview_skipped{}
xp_total  hp  mode  mode_trigger  mentor_enabled  sos_until  zero_until
shields[dates]  expenses[]  learning[]  safety[]  penalized{once_key}  notes{path→sha}  budget{}
reactions{message_id→{emoji, at, channel}}  read_upto  read_at
last_user_at  last_event_id  first_date
```

`Day`: `sleep_min, bedtime, deep_min, xp, hp_end, debrief, user_actions, msgs_out, out_keys, silent, reason,
materialized, day_type, social, expenses, damages[], closed{}`.

Производные величины (методы `State`): `tasks_on(date)`, `debts()`, `completion(date)` — доля выполнения с учётом
частичного, `level()`, `series(until, n, attr)`, `streak(today)` — дни подряд с ≥ 70 % (дни без задач не рвут),
`ignore_streak(until)`, `shields_used(date)`, `active_directives(today)`, `week_stats(date)` — продуктивные минуты,
глубокая работа, квоты, траты, `autonomy(today, days=28)`.

Снаружи `State` не меняется: любое изменение — новое событие через `Core.emit`. Другие процессы подхватывают чужие
события через `Core.refresh()` (читает `events` с `id > last_event_id`).

## 4. Инварианты, которые проверяются тестами

| # | Инвариант | Тест |
|---|---|---|
| 1 | Пересчёт из журнала даёт те же статусы задач, закрытия дней и режим, что накопленное состояние | `test_rebuild_equals_incremental_on_random_history` |
| 2 | Игровых событий (`xp_awarded`, `hp_changed`, `shield_used`, `protocol_zero`) код больше не пишет, и они ни на что не влияют | там же, `tests/test_no_game.py` |
| 3 | `done` не возвращается в `planned`; повторное закрытие или провал закрытой задачи отклоняется | `test_done_cannot_go_back` |
| 4 | События не редактируются и не удаляются — триггеры SQLite | `test_append_only` |
| 5 | Директива без `evidence` или со ссылкой на несуществующее событие отклоняется | `test_directive_requires_evidence`, `test_directive_needs_evidence` |
| 6 | При `mentor_enabled = false` и в 🟥 жёсткие тон-блоки, жёсткие примеры и `decision_rule` не попадают в промпт; контекст без метрик | `tests/test_prompt_safety.py` |
| 7 | Включить ментора может только человек: ни инструмента, ни `profile_set` | `test_mentor_cannot_be_reenabled_via_profile`, `test_no_tool_can_reenable_mentor` |
| 8 | Один день закрывается ровно одним `day_closed`, сколько бы процессов ни звали `catch_up` | `test_catch_up_is_idempotent` |
| 9 | Имена моделей отсутствуют в коде | `test_no_model_names_in_code` |
| 10 | Сгенерированные файлы (стиль, claude.ai) соответствуют конституции | `test_generated_assets_are_fresh` |

`arvix rebuild` прогоняет инвариант 1 и «день закрыт один раз» на живой базе и выходит с кодом 1 при расхождении.

## 5. Obsidian — второе хранилище

Arvix работает **в структуре хранилища человека**, а не в отдельной папке. Места — `[vault_paths]` конфига
(`arvix setup` находит их сам: папку роадмапов, Inbox, шаблон ежедневного отчёта):

| Что | По умолчанию | Ключ |
|---|---|---|
| профиль (блок `arvix:profile`) | `05_System/Профиль Arvix.md` | `profile` |
| цели | `05_System/Цели/` | `goals` |
| роадмапы | `03_Resources/Роадмапы/` или папка предмета | `roadmaps` |
| каркасы конспектов | `03_Resources/Обучение/` или `02_Areas/<Предмет>/Конспекты/` | `notes` |
| ретро недель | `05_System/Недели/` | `weekly` |
| Inbox | `05_System/Inbox.md` | `inbox` |
| журнал событий, выводы, бэкапы перезаписей | `05_System/Арвикс/` | `system` |
| ежедневные заметки и их шаблон | из `.obsidian/daily-notes.json` | `daily`, `daily_template` |

Правила записи — код (`vault.py`), не обещание:
- новую заметку можно создать в любой папке, кроме служебных (`.obsidian`, `.trash`, `.git`…); путь вне хранилища отклоняется;
- в чужую заметку — только дописать в конец (`append`) или обновить **свой** помеченный блок `%% arvix:имя %% … %% /arvix:имя %%` (комментарий Obsidian, человеку не виден; старые `<!-- arvix:… -->` заменяются); текст человека вне блока не трогается;
- перезаписать целиком — только свою заметку, которую человек с тех пор не менял (сверка sha из `note_written`), либо по явному согласию (`force`); перед перезаписью — копия в `05_System/Арвикс/_backup/`;
- удалять Arvix не умеет вообще.

Ежедневная заметка (`daily_note.py`): создаётся утром из шаблона человека (дата, номер дня и недели программы,
задачи чекбоксами); вечером заполняются **только пустые** поля frontmatter, и только те, что есть в шаблоне
(`sleep`, `wake`, `focus_min`/`focus_minutes`, `workout`), итоги и разбор — в блок `arvix:день`.

## 6. Экспорт ✅ `export.py`

`/export`, `arvix export [--days N]`, MCP `export`:
- блок `arvix:profile` в файле профиля — поля профиля, дерево целей, черты, память, все ответы интервью по блокам;
- блок `arvix:insights` в `05_System/Арвикс/Выводы.md` — инсайты и директивы с датами;
- итоги каждого из последних N дней в их ежедневных заметках (только существующих);
- `05_System/Арвикс/Журнал событий.md` — полный журнал JSONL, по строке на событие.

Всё, что человек допишет вне блоков, переживает любой повторный экспорт. Удаление плагина журнал не трогает:
данные лежат отдельно специально.
