# 07 · Эксплуатация

> Пошаговая инструкция для человека — [`arvix-claude/GUIDE.md`](../arvix-claude/GUIDE.md) (разделы 2–4, 9–13).
> Здесь — устройство: что куда ставится, как настроено и что делать при отказах.

## 1. Установка

```bash
bash arvix-claude/deploy/install.sh          # повторный запуск = обновление
arvix setup                                   # диалог: хранилище, часовой пояс, дом, Telegram
arvix doctor                                  # проверка
```

`install.sh` (нужен Python 3.11+, зависимостей нет):
1. копирует плагин в `~/.local/share/arvix/app` — путь без пробелов и кириллицы, его видят systemd, Claude Code и
   Claude Desktop, и он не исчезает вместе с git-worktree; тесты не копируются;
2. ставит CLI `~/.local/bin/arvix` (предупреждает, если папки нет в `PATH`);
3. проверяет плагин `claude plugin validate`, регистрирует маркетплейс `arvix` и плагин `arvix@arvix` (scope user);
4. кладёт systemd-юниты пользователя: `arvix-telegram.service`, `arvix-backup.service/.timer`,
   `arvix-vault-sync.service/.timer` — **не включает** их; если бот уже работает — перезапускает на новой версии;
   при `[sync] vault = "syncthing"` держит `arvix-vault-sync.timer` выключенным (§4);
5. с `--desktop` — регистрирует MCP-сервер в чате Claude Desktop; если конфиг уже есть — дополняет дом Арвикса.

Данные (`~/.local/share/arvix/arvix.db`) и конфиг (`~/.config/arvix/config.toml`) установка не трогает.
Удаление плагина (`claude plugin uninstall arvix@arvix`) журнал тоже не удаляет — данные лежат отдельно специально.

`arvix setup` без флагов — диалог; с флагами и `--yes` — без вопросов:
```bash
arvix setup --vault "$HOME/Документы/Obsidian Vault" --tz Europe/Moscow --home ~/Arvix --no-telegram --yes
arvix setup --telegram --yes        # только привязать бота: токен — скрытым вводом, в терминале
```
`setup` сам находит в хранилище папку роадмапов, Inbox, шаблон ежедневного отчёта (если путь в настройках Obsidian
ведёт в пустоту — ищет в папке шаблонов) и пишет найденное в `[vault_paths]`, не трогая то, что человек записал сам.
Привязка бота: `getMe` → «отправь боту /start» → «Это ты? y» → `owner_id` в конфиг. Токен в чаты и логи не попадает.

`arvix doctor` проверяет: конфиг, базу (или сервер в удалённом режиме), хранилище, шаблон отчёта, дом, `claude` для
головы, плагин в Claude Code, токен и владельца, ответ Telegram API, состояние службы (и что на ноутбуке бот
выключен, если он на сервере), Syncthing и его папку (при `[sync] vault = "syncthing"`) и файлы `*.sync-conflict-*`
в хранилище (§4).

## 2. Конфиг

Значения по умолчанию — `arvix-claude/arvix/defaults.toml`, свои — `~/.config/arvix/config.toml` (права 600).
`arvix setup` перезаписывает файл и теряет комментарии, значения сохраняет.

| Секция · ключ | По умолчанию | Что задаёт |
|---|---|---|
| `timezone` | `Europe/Moscow` | часовой пояс; профиль (`profile.timezone` из интервью) важнее |
| `vault` · `home` | — · `~/Arvix` | хранилище Obsidian · дом Арвикса для Claude Code |
| `[telegram] token · owner_id` | — | бот и единственный человек, которого он слушает |
| `[telegram] bubble_pause_sec · bubble_pause_per_char · bubble_pause_max_sec · bubbles_max` | `0.6` · `0.012` · `2.5` · `4` | ответ головы абзацами-сообщениями с паузой «набирает…»; `bubble_pause_sec = 0` — одним сообщением |
| `[vault_paths]` | `05_System/…`, `03_Resources/…` | места профиля, целей, роадмапов, конспектов, недель, Inbox, системной папки, ежедневных заметок и их шаблона |
| `[schedule] brief` | `auto` | брифинг: подъём из профиля + 15 мин, или `"07:30"` |
| `[schedule] midday · debrief` | `15:00` · `22:30` | чек-ин при выполнении < 40 % · разбор |
| `[schedule] retro_weekday · retro` | `6` · `20:00` | ретро: день недели (0 = пн) и время |
| `[schedule] rollover` | `04:00` | до этого времени вчерашний день открыт для отчётов; сове — `05:00` |
| `[schedule] bedtime_warning_min` | `30` | за сколько минут предупреждать об отбое |
| `[schedule] silent_weekday` | `-1` | тихий день каждую неделю (`6` = воскресенье), `-1` — нет |
| `[brain] claude_bin · timeout_sec · vault_tools · web_tools` | `claude` · `180` · `true` · `true` | путь к `claude`; таймаут головы; читает ли голова хранилище и папку памяти; ищет ли в интернете (D24) |
| `[schedule] curiosity` | `18:30` | Арвикс пишет первым раз в день (D27); `""` — выключено |
| `[web] enabled · port · public_url · token` | `true` · `8787` · — · — | приложение (D26): API в службе бота на 127.0.0.1; внешний адрес пишет `deploy/web-setup.sh`; ключ — в базе, если не задан здесь |
| `[weather] city` | — | запасной город для погоды, если в профиле его нет |
| `[roles.voice] model` · `[roles.analyst] model` | `sonnet` · `sonnet` | модели голоса и совета — **только здесь** (правило №4) |
| `[roles.stt] model` | `whisper-large-v3-turbo` | модель распознавания голоса; для OpenAI — их модель |
| `[stt] engine · api_key · language · max_seconds · timeout_sec · command` | `off` · — · `ru` · `300` · `90` · — | голосовые (§8) |
| `[learning] auto_lesson · check_questions · tools · concept_dir · concept_template` | `true` · `3` · `[]` · — · — | учебный блок ([06-LEARNING.md §8](06-LEARNING.md#8-учебный-блок-в-telegram-)): включён ли, сколько вопросов проверки, дополнительные инструменты, папка и шаблон каркаса заметки |
| `[stt] show_transcript` | `false` | показывать `🎙 «…»` перед ответом на голосовое; по умолчанию бот просто отвечает (D20) |
| `[mechanics] sleep_target_min` | `450` | норма сна, если распорядок не задан ([02-MECHANICS.md §7.1](02-MECHANICS.md#71-норма-сна--coresleep_target)) |
| `[mechanics] deep_target_min` | `120` | норма глубокой работы, если в плане дня её нет |
| `[mechanics] week_budget_min · week_deep_budget_min` | `1560` · `480` | бюджет недели без шаблонов |
| `[mechanics] shields_per_month` | `2` | щиты |
| `[mechanics.quotas]` | спорт 3 · социум 2 · новое 1 · отдых без экрана 3 | недельные минимумы |
| `[remote] host · app` | — | удалённый режим (§3) |
| `[sync] vault · folder` | `rsync` · `arvix-vault` | чем синхронизируется хранилище с сервером и id папки Syncthing; `syncthing` пишет `deploy/syncthing-setup.sh` (§4) |

После правки конфига: `systemctl --user restart arvix-telegram` (или на сервере).

## 2.1. Приложение наружу (Mini App, телефон)

```bash
bash deploy/web-setup.sh root@HOST          # Caddy, https://<ip>.sslip.io:8443, [web] public_url, перезапуск бота
```
Порт 443 скрипт не трогает (на сервере его держит VPN), сертификат получает через 80. Чужие сайты Caddy не трогаются:
свой блок — `/etc/caddy/arvix.caddy`. Проверка: `curl -sI https://<адрес>:8443/` и кнопка «Арвикс» у поля ввода в
Telegram. Ключ для телефона без Telegram — `arvix app-token` (на сервере). Терминал — просто `arvix` на ноутбуке.

## 3. Сервер и удалённый режим

Бот пишет круглосуточно, только если процесс жив. Ноутбук спит — бот молчит. Решение — VPS (1 ядро, 1–4 ГБ, любой
Linux с systemd; регион, где Claude доступен без VPN).

```bash
# 1. На сервере под root (один раз): python3, rsync, sqlite3, syncthing, пользователь arvix с linger, ключ ноутбука, Claude CLI
ssh root@HOST 'PUBKEY="'"$(cat ~/.ssh/id_ed25519.pub)"'" bash -s' < arvix-claude/deploy/server-setup.sh
# 2. С ноутбука: код + конфиг сервера из ноутбучного (vault → ~/vault, home → ~/Arvix) + install + doctor
bash arvix-claude/deploy/sync-server.sh arvix@HOST --init
# 3. Токен подписки для головы (нужен браузер для входа), кладётся в ~/.config/arvix/claude.env, на экран не выводится
ssh -t arvix@HOST bash ~/.local/share/arvix/app/deploy/server-claude-token.sh
ssh arvix@HOST systemctl --user enable --now arvix-telegram
# 4. Ноутбук — в удалённый режим
arvix remote set arvix@HOST
systemctl --user disable --now arvix-telegram            # два бота с одним токеном мешают друг другу
systemctl --user enable --now arvix-backup.timer
# 5. Хранилище ⇄ сервер через Syncthing (§4)
bash arvix-claude/deploy/syncthing-setup.sh arvix@HOST
```

**Удалённый режим** (`[remote] host`): MCP-сервер, хук, строка состояния и CLI ноутбука не открывают локальную базу,
а выполняют тот же скрипт на сервере по SSH (`arvix/remote.py`, `BatchMode`, таймаут соединения 8 с,
`ARVIX_LOCAL=1` на сервере, чтобы не зациклиться). Локально всегда работают `setup`, `init-home`, `doctor`,
`desktop-mcp`. `arvix remote show` — где журнал, `arvix remote off` — обратно локально,
`ARVIX_LOCAL=1 arvix …` — разово локально.

**Обновление:**
```bash
bash arvix-claude/deploy/sync-server.sh arvix@HOST   # сервер: код → install.sh → перезапуск бота
bash arvix-claude/deploy/install.sh                  # ноутбук: плагин и CLI
```

## 4. Синхронизация хранилища

Хранилище правят с двух сторон: человек — в Obsidian на ноутбуке, бот и приложение — на сервере (Inbox, итоги дня,
заметки из приложения). Поэтому его синхронизирует Syncthing, а не rsync по таймеру (D29).

```bash
bash arvix-claude/deploy/syncthing-setup.sh arvix@HOST    # с ноутбука; повторный запуск безопасен
arvix doctor
```

`deploy/syncthing-setup.sh`:
1. включает `syncthing.service` пользователя на ноутбуке и на сервере, если Syncthing там ещё не отвечает;
2. GUI — только `127.0.0.1:8384` (если слушал наружу — переносит на петлю); с Syncthing говорит только REST API на
   петле с ключом из `config.xml` (`arvix/syncthing.py`, стандартная библиотека; на сервер этот файл уходит через
   `ssh … python3 -`, свежая версия Арвикса там не нужна);
3. на сервере выключает глобальный анонс, NAT и ретрансляторы: ноутбук сам приходит на `tcp://<сервер>:22000`.
   Значит, на сервере должен быть открыт **22000/tcp**; порт 443 и VPN не трогаются;
4. обменивает id устройств и делает общую папку `sendreceive` = `vault` из конфига Арвикса на каждой стороне
   (ноутбук — своё хранилище, сервер — `~/vault`). Если на ноутбуке уже есть папка Syncthing на это хранилище,
   берёт её id и добавляет к ней сервер — вторую папку на тот же путь не заводит. Маркер `.stfolder` создаёт сам;
5. игнор: `/.obsidian/workspace*` (раскладка окон у каждой машины своя), `/.trash`, `Cache`; свои строки игнора
   сохраняются. Корзина версий `trashcan` на 30 дней: удалённое или заменённое с другой стороны лежит в `.stversions`
   (Syncthing переносит удаления, rsync — нет);
6. пишет `[sync] vault = "syncthing"` и `folder` в конфиг Арвикса на обеих сторонах и выключает
   `arvix-vault-sync.timer` (`disable --now`, юнит остаётся). На время настройки таймер остановлен; если скрипт
   сорвался — включается обратно.

После этого `install.sh` держит таймер выключенным (даже если его включили руками), `vault-sync.sh` ничего не делает,
`sync-server.sh` перестаёт предлагать переход.

**Конфликты.** Заметку изменили с двух сторон до обмена — Syncthing оставляет обе: одну под своим именем, вторую
рядом файлом `Имя.sync-conflict-ДАТА-ВРЕМЯ-УСТРОЙСТВО.md`. Арвикс их не сливает и не удаляет: `arvix doctor` показывает
их число и первые имена строкой `!!`, человек переносит нужное и удаляет копию. Поиск по хранилищу `.stversions`
не видит.

**`arvix doctor`** при `[sync] vault = "syncthing"` — FAIL, если Syncthing не отвечает на петле, GUI открыт наружу,
папки нет, она смотрит не на `vault`, на паузе или в ошибке; `!!`, если устройство папки не на связи (ноутбук бывает
выключен; старое устройство в папке — убрать в GUI). Файлы `*.sync-conflict-*` ищет при любом режиме. В удалённом
режиме с rsync — строка `--` с подсказкой перейти. GUI сервера — только через туннель:
`ssh -L 8385:127.0.0.1:8384 arvix@HOST` → `http://127.0.0.1:8385`.

**Откат на rsync:** `[sync] vault = "rsync"` в конфиге ноутбука и сервера, на ноутбуке
`systemctl --user enable --now arvix-vault-sync.timer`, на сервере `systemctl --user disable --now syncthing`.
Ограничения rsync-схемы (`deploy/vault-sync.sh`, `rsync -au` в обе стороны раз в 10 минут, новее побеждает):
удаления и переименования не переносятся; если в те же 10 минут файл изменили с двух сторон, одна правка теряется.

## 5. Бэкапы

| Где | Как | Сколько |
|---|---|---|
| ноутбук (удалённый режим) | `arvix-backup.timer` раз в сутки: на сервере `sqlite3 .backup` (целостный снимок при работающем боте), копия на ноутбук, `integrity_check`, только потом сохранение | 14 последних, `~/.local/share/arvix/backups/` |
| сервер | cron пользователя `arvix` — **ставится вручную**: `30 4 * * * sqlite3 ~/.local/share/arvix/arvix.db ".backup ~/backups/arvix-$(date +\%u).db"` | 7, по дню недели |
| хранилище | `/export` — журнал JSONL, профиль, выводы в Obsidian; дальше — как синхронизируется само хранилище | — |
| локальный режим | автоматического бэкапа нет: `sqlite3 ~/.local/share/arvix/arvix.db ".backup ~/arvix-$(date +%F).db"` вручную или свой таймер | — |

Восстановление: остановить бота, положить копию на место `arvix.db`, `arvix rebuild` (проверит инварианты), запустить.

## 6. Логи и отказы

Скорость головы видна в журнале службы: строка `голова: 7.1 с, ходов 2, роль voice` на каждый вызов. Много ходов —
модель искала инструментами; сообщения про заметки код ищет сам (`<vault_hits>`), чтобы ходов было меньше.

| Симптом | Что делать |
|---|---|
| Бот не отвечает | `systemctl --user status arvix-telegram`, `journalctl --user -u arvix-telegram -n 50` (на сервере — через `ssh arvix@HOST`) |
| «Голова сейчас недоступна» | кончился лимит подписки или нет сети; `arvix brain-test` покажет. Ошибка региона — бот сам подскажет про VPN |
| В Claude Code спрашивает разрешение на каждый инструмент | папке `~/Arvix` не дали доверие: `claude` там интерактивно → «да» |
| Нет стиля Arvix | сессия не в `~/Arvix`; или `/output-style arvix:Arvix` |
| Нет задач и напоминаний | нет шаблонов дней: `/schedule` или `/arvix:onboarding` |
| Режим «застрял» в 🟥 | выключен ментор (`/status`) — `/mentor on`; SOS — `/sos off`; иначе смотри причину в `/status` |
| Сомнения в цифрах | `arvix rebuild` — пересчёт журнала против текущего состояния |
| Строка состояния пустая или с ошибкой | `echo '{}' \| arvix statusline`; в удалённом режиме «сервер недоступен» — проверь `ssh HOST` |
| `ssh`: REMOTE HOST IDENTIFICATION HAS CHANGED | сервер переустановлен или подменён: убедись, что он твой, `ssh-keygen -R HOST`, подключись вручную |
| Токен бота где-то засветился (чат, скриншот, git) | @BotFather → `/revoke`, затем `arvix setup --telegram --yes` и `sync-server.sh … --init` |

## 7. Приватность

- Погода: Open-Meteo получает название города и его координаты — больше ничего. Поиск в сети (D24): запросы головы
  уходят в веб-поиск Claude; выключить — `[brain] web_tools = false`.
- Приложение наружу открыто только через HTTPS и только с подписью Telegram владельца или ключом приложения.

- Syncthing: заметки идут напрямую ноутбук ⇄ сервер по TLS. Сервер себя не анонсирует; Syncthing ноутбука по
  умолчанию пользуется глобальным обнаружением и ретрансляторами проекта Syncthing — они видят id устройства и IP,
  но не содержимое. Выключить — GUI ноутбука → Настройки → Подключения.

Наружу уходит: в Anthropic — сообщения, контекст-пакет и прочитанные головой заметки; в Telegram — переписка с ботом.
Больше никуда. Журнал, конфиг, токены — только на своих машинах, права 600. Голова на сервере видит всё хранилище,
защищённых папок пока нет — R5 в [08-ROADMAP.md](08-ROADMAP.md). Не держи в хранилище то, что не готов отправить
в модель: пароли, документы, чужие личные данные. Голосовые с `groq` или `openai` уходят этому сервису; с `command` —
никуда.

## 8. Голосовые сообщения

Настраивать на машине, где работает бот (в удалённом режиме — на сервере: `setup` всегда локален).

**Groq — проще всего.** Ключ: console.groq.com → API Keys → Create, бесплатно. Затем:
```bash
ssh -t arvix@HOST '~/.local/bin/arvix setup --stt groq --yes && systemctl --user restart arvix-telegram'
```
Ключ вводится скрытно и ложится в `config.toml` (права 600).

**Локально, без ключа и без отправки голоса:** нужны git, cmake, g++, ffmpeg.
```bash
ssh -t arvix@HOST 'bash ~/.local/share/arvix/app/deploy/stt-local.sh base'
ssh -t arvix@HOST '~/.local/bin/arvix setup --stt command --yes && systemctl --user restart arvix-telegram'
```
`base` быстрее, `small` точнее по-русски и медленнее в 2–3 раза.

Проверка — `arvix doctor` (строка «голосовые»). Сбой распознавания бот объясняет в чате: неверный ключ, лимит,
недоступный сервис — и просит написать текстом.
