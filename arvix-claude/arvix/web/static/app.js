/* Арвикс — приложение: Mini App в Telegram, PWA на телефоне. Без сборки и зависимостей.
 * Данные — только через /api (arvix/web/server.py). Живые обновления — поток /api/stream. */
"use strict";

const TG = window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData ? window.Telegram.WebApp : null;
const $ = (sel, root = document) => root.querySelector(sel);
const view = $("#view");
const TOKEN_KEY = "arvix_token";
const state = { tab: "today", data: null, messages: [], history: null, notesDir: "", note: null, thinking: "", seen: 0, version: "" };

// --- вход --------------------------------------------------------------------------------------
/* Привязка телефона: #p=<одноразовый код> из ссылки Арвикса (живёт 15 минут, срабатывает
 * один раз) → ключ приложения. Старые ссылки #t=<ключ> тоже принимаются. */
async function pairFromHash() {
  const t = location.hash.match(/[#&]t=([\w-]+)/), p = location.hash.match(/[#&]p=([\w-]+)/);
  if (!t && !p) return;
  history.replaceState(null, "", location.pathname);
  let key = t ? t[1] : "";
  if (p) {
    try {
      const res = await fetch("/api/pair/claim?code=" + encodeURIComponent(p[1]));
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { toast(data.error || "Ссылка не сработала"); return; }
      key = data.token;
    } catch (_) { toast("Нет связи с сервером"); return; }
  }
  try { localStorage.setItem(TOKEN_KEY, key); } catch (_) { /* приватный режим */ }
}

/* Chrome сам предлагает установку (WebAPK — настоящее приложение с иконкой): ловим это
 * событие и показываем свою кнопку, чтобы не искать пункт в меню ⋮. */
let installPrompt = null;
const standalone = () => window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installPrompt = e; if (state.tab === "today") renderToday(); });
window.addEventListener("appinstalled", () => { installPrompt = null; toast("Арвикс установлен — ищи иконку на экране"); });
async function installApp() {
  if (!installPrompt) { toast("Меню браузера ⋮ → «Установить приложение»"); return; }
  installPrompt.prompt();
  await installPrompt.userChoice.catch(() => null);
  installPrompt = null; if (state.tab === "today") renderToday();
}

function token() {
  try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (_) { return ""; }
}

function authHeaders() {
  if (TG) return { "X-Telegram-Init-Data": TG.initData };
  const t = token();
  return t ? { Authorization: "Bearer " + t } : {};
}

async function api(path, opts = {}) {
  const headers = { ...authHeaders(), ...(opts.json ? { "Content-Type": "application/json" } : {}), ...(opts.headers || {}) };
  const res = await fetch("/api/" + path, {
    method: opts.method || (opts.json || opts.body ? "POST" : "GET"),
    headers, body: opts.json ? JSON.stringify(opts.json) : opts.body,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) throw Object.assign(new Error(data.error || "Нужен вход"), { auth: true });
  if (!res.ok) throw Object.assign(new Error(data.error || "Ошибка " + res.status), { status: res.status, data });
  return data;
}

// --- утилиты -----------------------------------------------------------------------------------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const hm = (min) => { min = Math.round(min || 0); const h = Math.floor(min / 60), m = min % 60; return h ? `${h}ч${m ? " " + m + "м" : ""}` : `${m}м`; };
const haptic = (kind = "light") => { try { TG && TG.HapticFeedback.impactOccurred(kind); } catch (_) { /* нет */ } };
const notify = (kind) => { try { TG && TG.HapticFeedback.notificationOccurred(kind); } catch (_) { /* нет */ } };
let toastTimer;
function toast(text) {
  const el = $("#toast");
  el.textContent = text; el.classList.remove("hidden");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.add("hidden"), 2600);
}
// --- иконки: контурный набор в стиле Lucide (ISC), встроены — без зависимостей ------------------
const ICON_PATHS = {
  mic: '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><path d="M12 19v3"/>',
  clip: '<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
  phone: '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>',
  phoneOff: '<path d="M10.68 13.31a16 16 0 0 0 3.41 2.6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7 2 2 0 0 1 1.72 2v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.42 19.42 0 0 1-3.33-2.67m-2.67-3.34a19.79 19.79 0 0 1-3.07-8.63A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91"/><path d="M22 2 2 22"/>',
  send: '<path d="M14.54 21.69a.5.5 0 0 0 .94-.03l6.5-19a.5.5 0 0 0-.64-.64l-19 6.5a.5.5 0 0 0-.03.94l7.93 3.18a2 2 0 0 1 1.11 1.11z"/><path d="m21.85 2.15-10.94 10.94"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
  today: '<rect width="18" height="18" x="3" y="4" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/><path d="m9 16 2 2 4-4"/>',
  chat: '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>',
  notes: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
  progress: '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
  play: '<path d="M6 4.5v15a1 1 0 0 0 1.5.87l12-7.5a1 1 0 0 0 0-1.74l-12-7.5A1 1 0 0 0 6 4.5Z" fill="currentColor" stroke="none"/>',
  pause: '<rect x="6" y="4" width="4" height="16" rx="1" fill="currentColor" stroke="none"/><rect x="14" y="4" width="4" height="16" rx="1" fill="currentColor" stroke="none"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  more: '<circle cx="12" cy="12" r="1.2" fill="currentColor"/><circle cx="19" cy="12" r="1.2" fill="currentColor"/><circle cx="5" cy="12" r="1.2" fill="currentColor"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  pencil: '<path d="M21.17 6.81a1 1 0 0 0-3.98-3.98L3.84 16.17a2 2 0 0 0-.5.83l-1.32 4.35a.5.5 0 0 0 .62.62l4.35-1.32a2 2 0 0 0 .83-.5z"/><path d="m15 5 4 4"/>',
  back: '<path d="m15 18-6-6 6-6"/>',
  chevron: '<path d="m9 18 6-6-6-6"/>',
  folder: '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
  file: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>',
  graph: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.59 13.51 6.83 3.98"/><path d="m15.41 6.51-6.82 3.98"/>',
  list: '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/>',
  calendar: '<rect width="18" height="18" x="3" y="4" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
};
const icon = (name, cls = "") => `<svg class="ic${cls ? " " + cls : ""}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON_PATHS[name] || ""}</svg>`;

const MODE_CLASS = { green: "green", normal: "green", yellow: "yellow", red: "red", pressure: "yellow" };

// --- каркас ------------------------------------------------------------------------------------
document.querySelectorAll("[data-ic]").forEach((el) => { el.innerHTML = icon(el.dataset.ic); });
$("#top-call").innerHTML = icon("phone");
$("#top-call").onclick = () => { haptic(); openTalk(); };

function setTab(tab) {
  state.tab = tab;
  $("#top-call").classList.toggle("hidden", tab !== "chat");
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  if (tab === "chat") { $("#chat-dot").classList.add("hidden"); }
  state.note = tab === "notes" ? state.note : null;
  render();
  load(tab);
  window.scrollTo(0, tab === "chat" ? document.body.scrollHeight : 0);
}

$("#tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-tab]");
  if (b) { haptic(); setTab(b.dataset.tab); }
});

async function load(tab = state.tab) {
  try {
    if (tab === "today" || !state.data) state.data = await api("state");
    if (tab === "chat") {
      const r = await api("messages");
      const last = r.messages.length ? r.messages[r.messages.length - 1].id : 0;
      state.messages = r.messages; state.thinking = r.thinking || "";
      state.seen = Math.max(state.seen, last);
    }
    if (tab === "progress") state.history = await api("history?days=30");
    if (tab === "notes" && !state.note && !state.notesList) state.notesList = await api("notes?dir=" + encodeURIComponent(state.notesDir));
    renderTop(); render();
  } catch (err) {
    if (err.auth) renderLogin(); else toast(err.message);
  }
}

function renderTop() {
  const d = state.data;
  if (!d) return;
  const date = new Date(d.now);
  $("#top-day").textContent = d.weekday + ", " + date.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
  const s = d.stats;
  $("#top-sub").textContent = d.gentle ? "Мягкий день" : s ? `${s.done} из ${s.total}` : "";
  const mode = $("#top-mode");
  mode.textContent = d.mode_label;
  mode.className = "chip mode " + (MODE_CLASS[d.mode] || "");
}

function render() {
  if (state.tab === "today") renderToday();
  else if (state.tab === "chat") renderChat();
  else if (state.tab === "notes") renderNotes();
  else renderProgress();
  $(".fab") && $(".fab").remove();
  $(".composer") && state.tab !== "chat" && $(".composer").remove();
  if (state.tab === "today" && state.data && !state.data.gentle) {
    const fab = document.createElement("button");
    fab.className = "fab"; fab.innerHTML = icon("plus"); fab.setAttribute("aria-label", "Новая задача");
    fab.onclick = () => openAddSheet();
    document.body.appendChild(fab);
  }
}

function renderLogin() {
  view.innerHTML = `<div class="login">
    <h1>Арвикс</h1>
    <p class="muted">Откройте приложение из Telegram — кнопка «Арвикс» слева от поля ввода в чате с ботом.</p>
    <p class="muted small">Чтобы установить на телефон: в Telegram откройте приложение → «Прогресс» → «Установить на телефон».</p>
  </div>`;
}

// --- Сегодня -----------------------------------------------------------------------------------
function renderToday() {
  const d = state.data;
  if (!d) { view.innerHTML = `<div class="empty">Загружаю…</div>`; return; }
  let html = "";
  if (d.gentle) {
    html += `<div class="card note-card">${esc(d.note)}</div>`;
  } else if (d.stats) {
    const s = d.stats;
    // Только факты дня (D41): задачи, глубокая работа, сон. Ни очков, ни здоровья, ни уровня.
    const sleep = s.sleep_min == null ? `<b>—</b><span>сон не записан</span>`
      : `<b>${hm(s.sleep_min)}</b><span>сон, норма ${hm(s.sleep_target)}</span>`;
    html += `<div class="stats">
      <div class="stat"><b>${s.done}/${s.total}</b><span>задач</span><div class="bar"><i style="width:${s.total ? (100 * s.done / s.total) : 0}%"></i></div></div>
      <div class="stat"><b>${hm(s.deep_min)}</b><span>глубокая из ${hm(s.deep_target)}</span><div class="bar deep"><i style="width:${Math.min(100, 100 * s.deep_min / Math.max(1, s.deep_target))}%"></i></div></div>
      <div class="stat">${sleep}<div class="bar"><i style="width:${s.sleep_min == null ? 0 : Math.min(100, 100 * s.sleep_min / Math.max(1, s.sleep_target))}%"></i></div></div>
    </div>`;
  }
  if (installPrompt && !TG && !standalone()) {
    html += `<div class="card install-card"><div><b>Арвикс как приложение</b><div class="muted small">Иконка на экране, своё окно, без адресной строки</div></div>
      <button class="pill primary" id="install-now">Установить</button></div>`;
  }
  html += focusCard(d);
  if (d.lesson && d.lesson.topic) {
    html += `<div class="card"><h3>Урок</h3><div><b>${esc(d.lesson.topic)}</b></div>
      <div class="muted small">${d.lesson.started ? "идёт — в конце 3 вопроса проверки, ответь в чате" : "план готов — начни из чата или кнопкой ▶ у задачи"}</div></div>`;
  }
  const items = [...(d.tasks || []).map((t) => ({ ...t, kind: "task" })), ...(d.busy || []).map((b) => ({ ...b, kind: "busy" }))]
    .sort((a, b) => (a.start || "99").localeCompare(b.start || "99"));
  html += `<div class="section-title"><span>План дня</span><span>${d.day_type ? esc(d.day_type) : ""}</span></div>`;
  html += items.length ? items.map((t) => (t.kind === "busy" ? busyRow(t) : taskRow(t))).join("") :
    `<div class="empty">На сегодня задач нет.<br><span class="small">Нажми «+» или напиши Арвиксу: «добавь физику в 18:00 на час».</span></div>`;
  if (d.debts && d.debts.length) {
    html += `<div class="section-title"><span>Долг</span><span>${d.debts.length}</span></div>` + d.debts.map((t) => taskRow(t, true)).join("");
  }
  if (d.tomorrow && d.tomorrow.length) {
    html += `<details class="card"><summary><b>Завтра</b> <span class="muted">· ${d.tomorrow.length}</span></summary>
      <div style="margin-top:8px">${d.tomorrow.map((t) => `<div class="row"><span>${esc(t.start || "--:--")} ${esc(t.title)}</span><span class="muted small">${hm(t.duration_min)}</span></div>`).join("")}</div></details>`;
  }
  view.innerHTML = html;
  bindToday();
  $("#install-now") && ($("#install-now").onclick = installApp);
  tickFocus();
}

function focusCard(d) {
  const f = d.focus;
  const sessions = d.sessions || [];
  const list = sessions.length ? `<div class="sessions">${sessions.map((x) => `<div class="session">
      <span class="muted small">${esc(new Date(x.at).toTimeString().slice(0, 5))}</span><b>${hm(x.minutes)}</b>
      <span class="grow">${esc(x.title)}${x.note ? `<span class="muted small"> — ${esc(x.note)}</span>` : ""}</span>
      ${x.note ? "" : `<button class="link small" data-act="focus-note" data-event="${x.event_id}" data-min="${x.minutes}" data-title="${esc(x.title)}">+ что сделал</button>`}
    </div>`).join("")}<div class="muted small">Всего: ${hm(sessions.reduce((a, x) => a + x.minutes, 0))}</div></div>` : "";
  if (f) {
    const paused = !!f.paused_at;
    return `<div class="card"><div class="focus${paused ? " paused" : ""}" id="focus-card" data-until="${esc(f.until)}" data-minutes="${f.minutes}" data-paused="${esc(f.paused_at || "")}">
      <div class="ring" id="focus-ring"><div id="focus-left">--:--</div></div>
      <div class="focus-body"><div class="muted small">${paused ? `Пауза · до ${f.max_pause_min} мин, потом сессия закроется` : `Фокус · ${f.minutes} мин`}</div>
        <div class="focus-title">${esc(f.title || "глубокая работа")}</div>
        <div class="pills">${paused ? `<button class="pill primary" data-act="focus-op" data-op="resume">${icon("play")} Дальше</button>` : `<button class="pill" data-act="focus-op" data-op="pause">${icon("pause")} Пауза</button>`}
          <button class="pill" data-act="focus-op" data-op="stop">${icon("stop")} Закончить</button>
          <button class="pill danger" data-act="focus-op" data-op="cancel" aria-label="Отменить, не записывать">${icon("x")}</button></div></div></div>${list}</div>`;
  }
  if (d.gentle) return "";
  const open = (d.tasks || []).filter((t) => t.open);
  const form = state.focusForm || (state.focusForm = { target: (open.find((t) => t.status === "active") || open[0] || {}).id || "topic", minutes: 25, topic: "" });
  if (form.target !== "topic" && !open.some((t) => t.id === form.target)) form.target = open[0] ? open[0].id : "topic";
  const choices = d.focus_choices || [15, 25, 45, 60, 90];
  const custom = !choices.includes(+form.minutes);
  return `<div class="card focus-setup"><h3>Фокус</h3>
    <div class="field"><label>На что</label><div class="seg wrap" data-focus="target">
      ${open.map((t) => `<button type="button" data-v="${t.id}" class="${form.target === t.id ? "on" : ""}">${esc(t.title)}</button>`).join("")}
      <button type="button" data-v="topic" class="${form.target === "topic" ? "on" : ""}">${icon("pencil")} Своя тема</button></div>
      ${form.target === "topic" ? `<input id="focus-topic" class="input" placeholder="Например: физика, задачи 1–5" value="${esc(form.topic)}" maxlength="120">` : ""}</div>
    <div class="field"><label>Сколько</label><div class="seg" data-focus="minutes">
      ${choices.map((m) => `<button type="button" data-v="${m}" class="${+form.minutes === m ? "on" : ""}">${m}</button>`).join("")}
      <button type="button" data-v="custom" class="${custom ? "on" : ""}">${custom ? form.minutes : "своё"}</button></div></div>
    <button class="btn primary" data-act="focus-go">${icon("play")} Начать ${form.minutes} мин</button>
    <div class="muted small" style="margin-top:6px">Телефон экраном вниз. Пауза и отмена — на таймере.</div>${list}</div>`;
}

function openFocusNoteSheet(session) {
  openSheet(`<h2>Что успел?</h2><p class="muted small">${esc(session.title)} · ${hm(session.minutes)}</p>
    <div class="field"><textarea id="fn-text" rows="3" placeholder="Например: §12 — 5 задач, одна с ошибкой в единицах"></textarea></div>
    <button class="btn primary" id="fn-save">Записать</button><button class="btn" id="fn-skip">Пропустить</button>`, () => {
    setTimeout(() => $("#fn-text").focus(), 50);
    $("#fn-skip").onclick = () => { closeSheet(); load("today"); };
    $("#fn-save").onclick = async () => {
      const note = $("#fn-text").value.trim();
      if (!note) { toast("Пара слов — или «Пропустить»"); return; }
      try { await api("focus/note", { json: { event: session.event_id, note } }); notify("success"); closeSheet(); toast("Вписал в сессию"); load("today"); }
      catch (err) { toast(err.message); }
    };
  });
}

function busyRow(b) {
  return `<div class="task busy"><div class="time"><b>${esc(b.start)}</b>${esc(b.end)}</div>
    <div class="body"><div class="title muted">${esc(b.title)}</div><div class="meta"><span class="chip">занято</span></div></div></div>`;
}

function taskRow(t, debt = false) {
  const chips = [`<span class="chip">${esc(t.sphere_ru)}</span>`, `<span class="chip">${hm(t.duration_min)}</span>`];
  if (t.deep_work) chips.push(`<span class="chip accent">глубокая</span>`);
  if (t.importance >= 4) chips.push(`<span class="chip yellow">★${t.importance}</span>`);
  if (t.status === "done") chips.push(`<span class="chip green">✓ ${t.done_pct < 100 ? t.done_pct + "%" : "сделано"}</span>`);
  if (t.status === "failed") chips.push(`<span class="chip red">не сделано</span>`);
  if (t.focus_min) chips.push(`<span class="chip">🎯 ${hm(t.focus_min)}</span>`);
  let acts = "";
  if (t.status === "planned") acts = `<button class="icon-btn go" data-act="start" data-id="${t.id}" aria-label="Начать">${icon("play")}</button>`;
  if (t.open || debt) acts += `<button class="icon-btn ok" data-act="done" data-id="${t.id}" aria-label="Сделано">${icon("check")}</button>
    <button class="icon-btn" data-act="more" data-id="${t.id}" aria-label="Ещё">${icon("more")}</button>`;
  return `<div class="task ${esc(t.status)}${debt ? " debt" : ""}"><div class="time"><b>${esc(t.start || "—")}</b>${esc(t.end || "")}</div>
    <div class="body"><div class="title">${esc(t.title)}</div><div class="meta">${chips.join("")}</div></div>
    <div class="acts">${acts}</div></div>`;
}

function findTask(id) {
  const d = state.data || {};
  return [...(d.tasks || []), ...(d.debts || []), ...(d.tomorrow || [])].find((t) => t.id === id);
}

function bindFocusSetup() {
  const f = state.focusForm;
  if (!f) return;
  view.querySelectorAll("[data-focus]").forEach((g) => g.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    haptic("soft");
    const topicEl = $("#focus-topic"); if (topicEl) f.topic = topicEl.value;
    if (g.dataset.focus === "minutes") {
      if (b.dataset.v === "custom") {
        const v = parseInt(prompt("Сколько минут? 5–180", String(f.minutes)) || "", 10);
        if (!v) return;
        f.minutes = Math.max(5, Math.min(180, v));
      } else f.minutes = +b.dataset.v;
    } else f.target = b.dataset.v;
    renderToday();
    if (f.target === "topic" && g.dataset.focus === "target") setTimeout(() => $("#focus-topic") && $("#focus-topic").focus(), 30);
  }));
  const topicEl = $("#focus-topic");
  if (topicEl) topicEl.addEventListener("input", () => { f.topic = topicEl.value; });
}

function bindToday() {
  bindFocusSetup();
  view.querySelectorAll("[data-act]").forEach((el) => el.addEventListener("click", async () => {
    const act = el.dataset.act, id = el.dataset.id;
    haptic();
    try {
      if (act === "start") {
        const t = findTask(id);
        if (t && t.sphere === "learning") { await api("lesson/" + id, { json: {} }); toast("Готовлю план урока — он придёт в чат"); setTab("chat"); return; }
        await api(`tasks/${id}/start`, { json: {} }); toast("Пошло. Удачи.");
      } else if (act === "done") {
        const t = findTask(id);
        if (t && t.proof && t.proof !== "confirm") { openReportSheet(t); return; }
        const r = await api(`tasks/${id}/done`, { json: {} });
        notify("success"); toast("✓ Записал" + (r.debt_closed ? " · долг закрыт" : "") + (r.warnings && r.warnings.length ? "\n" + r.warnings.join("\n") : ""));
      } else if (act === "more") { openTaskSheet(findTask(id)); return; }
      else if (act === "focus-go") {
        const f = state.focusForm, topic = f.target === "topic" ? ($("#focus-topic") ? $("#focus-topic").value.trim() : f.topic) : "";
        await api("focus", { json: { minutes: +f.minutes, task: f.target === "topic" ? null : f.target, topic: topic || null } });
        f.topic = ""; toast("Фокус пошёл. Таймер есть и в Telegram.");
      } else if (act === "focus-op") {
        const op = el.dataset.op;
        if (op === "cancel" && !confirm("Отменить фокус? Ничего не запишется.")) return;
        const r = await api("focus/" + op, { json: {} });
        if (op === "stop" && r.session) { await load("today"); openFocusNoteSheet(r.session); return; }
        if (op === "stop") toast("Меньше 5 минут — не сессия, ничего не записано");
        if (op === "cancel") toast("Отменено, ничего не записано");
      } else if (act === "focus-note") { openFocusNoteSheet({ event_id: +el.dataset.event, minutes: +el.dataset.min, title: el.dataset.title }); return; }
      await load("today");
    } catch (err) { notify("error"); toast(err.message); }
  }));
}

let focusTimer;
function tickFocus() {
  clearInterval(focusTimer);
  const card = $("#focus-card");
  if (!card) return;
  const until = new Date(card.dataset.until).getTime(), total = (+card.dataset.minutes || 1) * 60000;
  const pausedAt = card.dataset.paused ? new Date(card.dataset.paused).getTime() : 0;
  const step = () => {
    const left = Math.max(0, until - (pausedAt || Date.now()));
    const m = Math.floor(left / 60000), s = Math.floor((left % 60000) / 1000);
    const el = $("#focus-left"); if (!el) return clearInterval(focusTimer);
    el.textContent = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    $("#focus-ring").style.setProperty("--p", String(Math.min(1, 1 - left / total)));
    if (!left && !pausedAt) { clearInterval(focusTimer); notify("success"); setTimeout(() => load("today"), 1500); }
  };
  step();
  if (!pausedAt) focusTimer = setInterval(step, 1000);
}

// --- шторки ------------------------------------------------------------------------------------
function openSheet(html, bind) {
  const sheet = $("#sheet"), back = $("#sheet-back");
  sheet.innerHTML = `<div class="grab"></div>` + html;
  sheet.classList.remove("hidden"); back.classList.remove("hidden");
  back.onclick = closeSheet;
  if (TG) { TG.BackButton.show(); TG.BackButton.onClick(closeSheet); }
  bind && bind(sheet);
}
function closeSheet() {
  $("#sheet").classList.add("hidden"); $("#sheet-back").classList.add("hidden");
  if (TG) { TG.BackButton.offClick(closeSheet); if (!state.note) TG.BackButton.hide(); }
}

function seg(name, values, current, fmt = (v) => v) {
  return `<div class="seg" data-seg="${name}">${values.map((v) => `<button type="button" data-v="${v}" class="${String(v) === String(current) ? "on" : ""}">${fmt(v)}</button>`).join("")}</div>`;
}
function bindSeg(root, form) {
  root.querySelectorAll("[data-seg]").forEach((g) => g.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    g.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    form[g.dataset.seg] = b.dataset.v; haptic("soft");
  }));
}

function openAddSheet() {
  const now = new Date(); now.setMinutes(Math.ceil(now.getMinutes() / 15) * 15 + 15);
  const form = { duration_min: 60, sphere: "learning", importance: 3, day: "today", deep_work: "0" };
  openSheet(`<h2>Новая задача</h2>
    <div class="field"><input id="f-title" placeholder="Что сделать? Например: Физика — задачи 1–5" autocomplete="off"></div>
    <div class="field"><label>Когда</label><div style="display:flex;gap:8px">
      <input id="f-start" type="time" value="${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes() % 60).padStart(2, "0")}" style="flex:1">
      ${seg("day", ["today", "tomorrow"], "today", (v) => (v === "today" ? "сегодня" : "завтра"))}</div></div>
    <div class="field"><label>Сколько</label>${seg("duration_min", [15, 30, 45, 60, 90, 120], 60, hm)}</div>
    <div class="field"><label>Сфера</label>${seg("sphere", ["learning", "project", "work", "sport", "health", "social", "chore"], "learning",
      (v) => ({ learning: "учёба", project: "проект", work: "работа", sport: "спорт", health: "здоровье", social: "люди", chore: "быт" }[v]))}</div>
    <div class="field"><label>Важность</label>${seg("importance", [1, 2, 3, 4, 5], 3)}</div>
    <div class="field"><label>Глубокая работа</label>${seg("deep_work", ["0", "1"], "0", (v) => (v === "1" ? "да" : "нет"))}</div>
    <button class="btn primary" id="f-save">Добавить</button>
    <p class="muted small">Без времени — оставь поле пустым, Арвикс не станет напоминать. Можно и словами в чате: «добавь физику на завтра в 18:00».</p>`,
  (root) => {
    bindSeg(root, form);
    setTimeout(() => $("#f-title").focus(), 50);
    $("#f-save").onclick = async () => {
      const title = $("#f-title").value.trim();
      if (!title) { toast("Напиши, что сделать"); return; }
      const today = new Date(); if (form.day === "tomorrow") today.setDate(today.getDate() + 1);
      const iso = today.toLocaleDateString("sv-SE");
      try {
        const r = await api("tasks", { json: { title, start: $("#f-start").value || null, duration_min: +form.duration_min, sphere: form.sphere,
          importance: +form.importance, deep_work: form.deep_work === "1", date: iso } });
        notify("success"); closeSheet();
        toast("+ " + r.task.title + (r.warnings && r.warnings.length ? "\n⚠️ " + r.warnings.join("\n⚠️ ") : ""));
        load("today");
      } catch (err) { toast(err.message); }
    };
  });
}

function openTaskSheet(t) {
  if (!t) return;
  openSheet(`<h2>${esc(t.title)}</h2>
    <p class="muted small">${esc(t.start || "без времени")} · ${hm(t.duration_min)} · ${esc(t.sphere_ru)}</p>
    <div class="sheet-actions">
      ${t.sphere === "learning" && t.open ? `<button class="btn" data-op="lesson">📚 Урок: план, таймер, проверка</button>` : ""}
      <button class="btn" data-op="part">◐ Сделано частично…</button>
      <button class="btn" data-op="report">📝 Сделано, с отчётом…</button>
      <button class="btn" data-op="defer" data-min="15">⏳ Перенести на 15 мин</button>
      <button class="btn" data-op="defer" data-min="30">⏳ Перенести на 30 мин</button>
      <button class="btn" data-op="defer" data-min="60">⏳ Перенести на час</button>
      <button class="btn danger" data-op="fail">✕ Не сделано…</button>
      <button class="btn danger" data-op="cancel">Отменить задачу…</button>
    </div>`, (root) => {
    root.querySelectorAll("[data-op]").forEach((b) => b.addEventListener("click", async () => {
      const op = b.dataset.op;
      haptic();
      try {
        if (op === "lesson") { await api("lesson/" + t.id, { json: {} }); closeSheet(); toast("Готовлю план урока — он придёт в чат"); setTab("chat"); return; }
        if (op === "part") { openPartSheet(t); return; }
        if (op === "report") { openReportSheet(t); return; }
        if (op === "defer") { const r = await api(`tasks/${t.id}/defer`, { json: { minutes: +b.dataset.min } }); toast("→ " + r.start); }
        if (op === "fail" || op === "cancel") {
          const reason = prompt(op === "fail" ? "Что помешало? Честно, одной фразой" : "Почему отменяешь?");
          if (reason === null) return;
          const r = await api(`tasks/${t.id}/${op}`, { json: { reason } });
          toast(op === "fail" ? `Не сделано${r.debt ? " · в долг" : ""}` : "Отменено");
        }
        closeSheet(); load("today");
      } catch (err) { toast(err.message); }
    }));
  });
}

function openPartSheet(t) {
  const form = { pct: 50 };
  openSheet(`<h2>Сколько сделано?</h2><p class="muted small">${esc(t.title)}</p>
    <div class="field">${seg("pct", [25, 50, 75], 50, (v) => v + "%")}</div>
    <div class="field"><textarea id="p-report" rows="3" placeholder="Что именно сделано"></textarea></div>
    <button class="btn primary" id="p-save">Записать</button>`, (root) => {
    bindSeg(root, form);
    $("#p-save").onclick = async () => {
      try {
        const r = await api(`tasks/${t.id}/done`, { json: { pct: +form.pct, report: $("#p-report").value.trim() || null } });
        notify("success"); closeSheet(); toast(`✓ ${form.pct}% — записал`); load("today");
      } catch (err) { toast(err.message); }
    };
  });
}

function openReportSheet(t, after = null) {
  openSheet(`<h2>Отчёт</h2><p class="muted small">${esc(t.title)}</p>
    <div class="field"><textarea id="r-report" rows="4" placeholder="Что сделано: цифры, темы, результат"></textarea></div>
    <button class="btn primary" id="r-save">Сделано</button>`, () => {
    setTimeout(() => $("#r-report").focus(), 50);
    $("#r-save").onclick = async () => {
      const report = $("#r-report").value.trim();
      if (!report) { toast("Пара слов о сделанном"); return; }
      try {
        const r = await api(`tasks/${t.id}/done`, { json: { report } });
        notify("success"); closeSheet(); toast("✓ Записал");
        if (after) after(); else load("today");
      } catch (err) { toast(err.message); }
    };
  });
}

// --- Чат ---------------------------------------------------------------------------------------
function renderChat() {
  let html = `<div class="chat" id="chat">`;
  let lastDay = "";
  for (const m of state.messages) {
    const at = new Date(m.at);
    const day = at.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
    if (day !== lastDay) { html += `<div class="day-sep">${day}</div>`; lastDay = day; }
    const btns = (m.buttons || []).flat().filter((b) => b && b[1] && !String(b[1]).startsWith("app:"));
    html += `<div class="msg ${m.who === "me" ? "me" : ""}">${linkify(esc(m.text))}${btns.length ? `<div class="btns">${btns.map((b) =>
      String(b[1]).startsWith("url:") ? `<a class="pill" href="${esc(String(b[1]).slice(4))}" target="_blank" rel="noopener">${esc(b[0])}</a>` :
      `<button data-btn="${esc(b[1])}">${esc(b[0])}</button>`).join("")}</div>` : ""}<time>${at.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}${m.channel === "telegram" ? "" : " · " + esc(m.channel)}</time></div>`;
  }
  if (state.thinking) html += `<div class="typing" title="${esc(state.thinking)}"><i></i><i></i><i></i></div>`;
  if (!state.messages.length && !state.thinking) html += `<div class="empty">Напиши или скажи что угодно — как в Telegram.</div>`;
  html += `</div>`;
  view.innerHTML = html;
  if (!$(".composer")) {
    const c = document.createElement("div");
    c.className = "composer";
    c.innerHTML = `<button class="round ghost" id="attach" aria-label="Прислать файл">${icon("clip")}</button>
      <input type="file" id="file" multiple hidden>
      <textarea id="msg" rows="1" placeholder="Сообщение Арвиксу"></textarea>
      <button class="round send" id="send" aria-label="Голосовое сообщение" data-mode="mic">${icon("mic")}</button>`;
    document.body.appendChild(c);
    const ta = $("#msg");
    ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = Math.min(140, ta.scrollHeight) + "px"; composerMode(); });
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !("ontouchstart" in window)) { e.preventDefault(); sendMessage(); } });
    $("#send").onclick = () => ($("#send").dataset.mode === "send" ? sendMessage() : toggleRecord());
    $("#attach").onclick = () => $("#file").click();
    $("#file").onchange = (e) => { sendFiles([...e.target.files]); e.target.value = ""; };
  }
  view.querySelectorAll("[data-btn]").forEach((b) => b.addEventListener("click", async () => {
    haptic(); b.disabled = true;
    try { await api("button", { json: { data: b.dataset.btn } }); state.thinking = "думаю"; renderChat(); } catch (err) { toast(err.message); }
  }));
  window.scrollTo(0, document.body.scrollHeight);
}

function linkify(html) {
  return html
    .replace(/https?:\/\/[^\s<]+/g, (u) => `<a href="${u}" target="_blank" rel="noopener">${u}</a>`)
    .replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>");
}

/* Как в Telegram: пустое поле — микрофон, есть текст — «отправить», идёт запись — стоп. */
function composerMode() {
  const b = $("#send"), ta = $("#msg"); if (!b || !ta) return;
  const recording = recorder && recorder.state === "recording";
  const mode = recording ? "rec" : ta.value.trim() ? "send" : "mic";
  if (b.dataset.mode === mode) return;
  b.dataset.mode = mode;
  b.innerHTML = icon(mode === "rec" ? "stop" : mode);
  b.classList.toggle("rec", recording);
  b.setAttribute("aria-label", { rec: "Остановить запись", send: "Отправить", mic: "Голосовое сообщение" }[mode]);
}

async function sendMessage() {
  const ta = $("#msg");
  const text = ta.value.trim();
  if (!text) return;
  ta.value = ""; ta.style.height = "auto"; composerMode(); haptic();
  state.messages.push({ id: 0, at: new Date().toISOString(), who: "me", text, channel: "web", buttons: [] });
  state.thinking = "думаю"; renderChat();
  try { await api("message", { json: { text } }); } catch (err) { toast(err.message); }
}

/* Файлы Арвиксу: фото, PDF, документы, архив репозитория, аудио, видео — до 20 МБ.
 * Подпись — текст из поля ввода (к первому файлу). Ответ придёт в ленту потоком. */
const MAX_FILE = 20 * 1024 * 1024;
async function sendFiles(files) {
  const ta = $("#msg");
  let caption = ta.value.trim();
  for (const file of files) {
    if (file.size > MAX_FILE) { toast(`«${file.name}» больше 20 МБ — сожми или раздели`); continue; }
    state.messages.push({ id: 0, at: new Date().toISOString(), who: "me", text: "📎 " + file.name + (caption ? " — " + caption : ""), channel: "web", buttons: [] });
    state.thinking = "смотрю файл"; renderChat();
    try {
      const res = await fetch("/api/upload", { method: "POST", body: file, headers: { ...authHeaders(), "Content-Type": file.type || "application/octet-stream",
        "X-File-Name": encodeURIComponent(file.name), "X-Caption": encodeURIComponent(caption) } });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "Ошибка " + res.status);
      haptic();
    } catch (err) { toast(err.message); }
    caption = "";
  }
  ta.value = ""; ta.style.height = "auto"; composerMode();
}

/* --- Звонок Арвиксу (D34, D36): говоришь → Арвикс отвечает вслух → снова слушает. Без нажатий.
 * Конец фразы — по тишине (Web Audio). Голос ответа — сервера (Gemini, мужской Charon): он живой;
 * если сервер не смог (лимит, сеть, голос выключен) — голос телефона (speechSynthesis); нет и его — текст.
 * Звук «разблокируется» в момент нажатия на 📞: браузеры (и WebView Telegram) запрещают звук без жеста. */
const talk = { on: false, phase: "", stream: null, rec: null, ctx: null, raf: 0, source: null, el: null, lastId: 0, voice: null,
  serverVoice: false, note: "" };
const SILENT_WAV = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=";

function talkVoices() {
  if (!("speechSynthesis" in window)) return null;
  const list = speechSynthesis.getVoices().filter((v) => /^ru/i.test(v.lang));
  return list.find((v) => /google|милена|milena|irina|ирина/i.test(v.name)) || list[0] || null;
}
if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = () => { talk.voice = talkVoices(); };

async function openTalk() {
  if (talk.on) return;
  talk.on = true; talk.voice = talkVoices(); talk.nudged = false; talk.note = "";
  // Синхронно, пока идёт жест нажатия: контекст звука и элемент <audio> получают право играть.
  try { talk.ctx = new (window.AudioContext || window.webkitAudioContext)(); talk.ctx.resume(); } catch (_) { talk.ctx = null; }
  talk.el = new Audio(); talk.el.src = SILENT_WAV; talk.el.play().catch(() => {});
  const el = document.createElement("div");
  el.id = "talk"; el.className = "talk";
  el.innerHTML = `<div class="talk-head"><div class="talk-name">Арвикс</div><div class="talk-status" id="talk-status">Соединяю…</div></div>
    <button class="talk-orb" id="talk-orb" aria-label="Перебить или начать говорить"><span class="talk-ring" id="talk-level"></span>
      <img src="icon-192.png" alt="" class="talk-avatar"></button>
    <div class="talk-text" id="talk-text"></div>
    <div class="talk-bar">
      <div class="muted small talk-hint" id="talk-hint">Пауза в полторы секунды — «договорил». Тап по аватару — перебить.</div>
      <button class="talk-end" id="talk-end" aria-label="Завершить разговор">${icon("phoneOff")}</button>
    </div>`;
  document.body.appendChild(el);
  $("#talk-end").onclick = closeTalk;
  $("#talk-orb").onclick = () => { if (talk.phase === "speaking" || talk.phase === "idle") { stopSpeaking(); talkListen(); } };
  if (TG) { TG.BackButton.show(); TG.BackButton.onClick(closeTalk); }
  try {
    const [m, s] = await Promise.all([api("messages"), api("state")]);
    talk.lastId = Math.max(0, ...m.messages.map((x) => x.id || 0));  // старые ответы не озвучиваем
    state.data = s; talk.serverVoice = !!s.server_tts;
  } catch (_) { talk.lastId = Math.max(0, ...state.messages.map((x) => x.id || 0)); talk.serverVoice = !!(state.data && state.data.server_tts); }
  if (!talk.serverVoice) $("#talk-hint").textContent = "Голос сервера выключен — говорю голосом телефона. Включить живой голос: arvix setup --tts gemini.";
  talkListen();
}

function closeTalk() {
  talk.on = false; talk.phase = "";
  stopSpeaking();
  if (talk.rec && talk.rec.state === "recording") { talk.rec.onstop = null; talk.rec.stop(); }
  if (talk.stream) talk.stream.getTracks().forEach((t) => t.stop());
  if (talk.ctx) talk.ctx.close().catch(() => {});
  cancelAnimationFrame(talk.raf);
  talk.stream = talk.ctx = talk.rec = talk.analyser = talk.el = null;
  $("#talk") && $("#talk").remove();
  if (TG) { TG.BackButton.offClick(closeTalk); TG.BackButton.hide(); }
  if (state.tab === "chat") load("chat");
}

function talkStatus(text, phase) {
  talk.phase = phase || talk.phase;
  const s = $("#talk-status"); if (s) s.textContent = text;
  const orb = $("#talk-orb"); if (orb) orb.dataset.phase = talk.phase;
}

async function talkListen() {
  if (!talk.on) return;
  try {
    if (!talk.stream) talk.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    if (!talk.ctx) talk.ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (talk.ctx.state === "suspended") await talk.ctx.resume().catch(() => {});
    if (!talk.analyser) {
      talk.analyser = talk.ctx.createAnalyser(); talk.analyser.fftSize = 1024;
      talk.ctx.createMediaStreamSource(talk.stream).connect(talk.analyser);
    }
  } catch (err) { talkStatus("Нет доступа к микрофону: " + err.message, "idle"); return; }
  const type = ["audio/ogg;codecs=opus", "audio/webm;codecs=opus", "audio/mp4"].find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
  const rec = talk.rec = new MediaRecorder(talk.stream, type ? { mimeType: type } : undefined);
  const chunks = [];
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  rec.onstop = () => { const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" }); if (talk.on && spoke && blob.size > 1500) talkSend(blob); else if (talk.on && spoke) talkListen(); };
  rec.start(); haptic("light");
  talkStatus(talk.note ? `Слушаю… (${talk.note})` : "Слушаю…", "listening");
  const buf = new Uint8Array(talk.analyser.fftSize);
  let spoke = false, voiced = 0, quietSince = 0;
  const started = performance.now();
  const loop = () => {
    if (!talk.on || rec.state !== "recording") return;
    talk.analyser.getByteTimeDomainData(buf);
    let sum = 0; for (const v of buf) sum += (v - 128) ** 2;
    const rms = Math.sqrt(sum / buf.length) / 128, now = performance.now();
    const lvl = $("#talk-level"); if (lvl) lvl.style.transform = `scale(${1 + Math.min(rms * 6, 0.6)})`;
    if (rms > 0.035) { voiced += 1; quietSince = 0; if (voiced > 4) spoke = true; }
    else if (spoke && !quietSince) quietSince = now;
    if (spoke && quietSince && now - quietSince > 1500) { rec.stop(); return; }           // договорил
    if (now - started > 60000) { if (spoke) rec.stop(); else { rec.onstop = null; rec.stop(); talkStatus("Я здесь. Тапни аватар, когда захочешь продолжить.", "idle"); } return; }
    if (!spoke && now - started > 12000 && !talk.nudged) { talk.nudged = true; talkStatus("Я слушаю — скажи, что на душе или как прошёл день.", "listening"); }
    talk.raf = requestAnimationFrame(loop);
  };
  loop();
}

async function talkSend(blob) {
  talkStatus("Думаю…", "thinking");
  $("#talk-text").textContent = "";
  try { await api("voice", { body: blob, headers: { "Content-Type": blob.type.split(";")[0] } }); }
  catch (err) { talkStatus(err.message, "idle"); return; }
  const deadline = Date.now() + 200000;
  while (talk.on && Date.now() < deadline) {      // ответ придёт в журнал — ждём новое сообщение Арвикса
    await new Promise((r) => setTimeout(r, 1200));
    try {
      const r = await api("messages");
      const fresh = r.messages.filter((m) => m.id > talk.lastId);
      if (fresh.length) talk.lastId = Math.max(...fresh.map((m) => m.id));
      const mine = fresh.filter((m) => m.who === "me").pop();
      if (mine && $("#talk-text")) $("#talk-text").innerHTML = `<div class="muted small">ты: ${esc(mine.text.replace(/^🎙\s*/, ""))}</div>`;
      const answer = fresh.filter((m) => m.who === "arvix").map((m) => m.text).join("\n");
      if (answer) { state.messages = r.messages; await talkSpeak(answer); return; }
    } catch (_) { /* сеть моргнула — ждём дальше */ }
  }
  if (talk.on) talkStatus("Ответа нет — голова, похоже, недоступна. Тапни аватар, чтобы попробовать ещё.", "idle");
}

function stopSpeaking() {
  try { if ("speechSynthesis" in window) speechSynthesis.cancel(); } catch (_) { /* нет */ }
  if (talk.source) { try { talk.source.onended = null; talk.source.stop(); } catch (_) { /* уже */ } talk.source = null; }
  if (talk.el) { talk.el.onended = null; talk.el.pause(); }
}

/* Голос сервера: OGG от /api/tts → Web Audio (контекст разблокирован жестом), иначе <audio>. */
async function playServerVoice(text, done) {
  const res = await fetch("/api/tts", { method: "POST", headers: { ...authHeaders(), "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || "голос сервера недоступен");
  }
  const bytes = await res.arrayBuffer();
  if (!talk.on || talk.phase !== "speaking") return true;
  if (talk.ctx) {
    try {
      const buffer = await talk.ctx.decodeAudioData(bytes.slice(0));
      const src = talk.source = talk.ctx.createBufferSource();
      src.buffer = buffer; src.connect(talk.ctx.destination);
      src.onended = () => { if (talk.source === src) { talk.source = null; done(); } };
      src.start();
      return true;
    } catch (_) { /* формат не декодируется — попробуем <audio> */ }
  }
  const el = talk.el || (talk.el = new Audio());
  el.src = URL.createObjectURL(new Blob([bytes], { type: "audio/ogg" }));
  el.onended = done;
  await el.play();
  return true;
}

async function talkSpeak(text) {
  if (!talk.on) return;
  const box = $("#talk-text"); if (box) box.innerHTML += `<div class="talk-answer">${esc(text)}</div>`;
  talkStatus("Говорю… (тап — перебить)", "speaking");
  const clean = text.replace(/https?:\/\/\S+/g, "").replace(/[*_`#>|~=\[\]]/g, "").replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, "");
  const done = () => { if (talk.on && talk.phase === "speaking") talkListen(); };
  if (talk.serverVoice) {
    try { talk.note = ""; await playServerVoice(clean, done); return; }
    catch (err) { talk.note = "голос телефона: " + err.message; talkStatus(`Говорю голосом телефона — ${err.message}`, "speaking"); }
  }
  const voice = talk.voice || talkVoices();
  if (voice) {
    const parts = clean.match(/[^.!?…\n]+[.!?…]*/g) || [clean];
    parts.forEach((p, i) => {
      const u = new SpeechSynthesisUtterance(p.trim()); u.voice = voice; u.lang = voice.lang; u.rate = 1.12;
      if (i === parts.length - 1) u.onend = done;
      speechSynthesis.speak(u);
    });
    return;
  }
  talkStatus("Голоса для озвучки нет — читай ответ. Слушаю дальше через пару секунд.", "speaking");
  setTimeout(done, Math.min(8000, 1500 + clean.length * 25));
}

let recorder, chunks = [], recStart = 0;
async function toggleRecord() {
  if (recorder && recorder.state === "recording") { recorder.stop(); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const type = ["audio/ogg;codecs=opus", "audio/webm;codecs=opus", "audio/mp4"].find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
    recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    chunks = []; recStart = Date.now();
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      composerMode();
      if (Date.now() - recStart < 700) { toast("Слишком коротко"); return; }
      const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      state.messages.push({ id: 0, at: new Date().toISOString(), who: "me", text: "🎙 голосовое…", channel: "web", buttons: [] });
      state.thinking = "слушаю"; renderChat();
      try { await api("voice", { body: blob, headers: { "Content-Type": blob.type.split(";")[0] } }); } catch (err) { toast(err.message); }
    };
    recorder.start(); haptic("medium");
    composerMode();
  } catch (err) { toast("Нет доступа к микрофону: " + err.message); }
}

// --- Заметки -----------------------------------------------------------------------------------
function renderNotes() {
  if (state.note) { renderNote(); return; }
  if (state.notesView === undefined) { try { state.notesView = localStorage.getItem("arvix_notes_view") || "list"; } catch (_) { state.notesView = "list"; } }
  if (state.notesView === "graph" && !state.notesResults) { renderGraph(); return; }
  const list = state.notesList;
  let html = notesSwitch() + `<div class="search"><input id="n-q" type="search" placeholder="Поиск по заметкам" value="${esc(state.notesQuery || "")}"></div>
    <div class="card"><h3>Мысль в Inbox</h3><div class="field" style="margin:0"><textarea id="n-cap" rows="2" placeholder="Записать и не держать в голове"></textarea></div>
    <button class="pill primary" id="n-save" style="margin-top:8px">Записать</button></div>`;
  if (state.notesResults) {
    html += `<div class="section-title"><span>Найдено</span><button class="small" id="n-clear" style="color:var(--accent)">сбросить</button></div>`;
    html += state.notesResults.length ? state.notesResults.map((r) => `<button class="list-item" data-path="${esc(r.path)}"><span class="li-ic">${icon("file")}</span>
      <span class="grow"><b>${esc(r.path.split("/").pop().replace(/\.md$/, ""))}</b><br><span class="muted small">${esc(r.snippet)}</span></span></button>`).join("") :
      `<div class="empty">Ничего не нашлось.</div>`;
  } else if (list) {
    const parts = state.notesDir ? state.notesDir.split("/") : [];
    html += `<div class="crumbs-row"><div class="crumbs"><button data-dir="">Хранилище</button>${parts.map((p, i) => ` / <button data-dir="${esc(parts.slice(0, i + 1).join("/"))}">${esc(p)}</button>`).join("")}</div>
      <button class="pill" id="n-new">+ Заметка</button></div>`;
    html += list.dirs.map((d) => `<button class="list-item" data-dir="${esc(d.path)}"><span class="li-ic folder">${icon("folder")}</span><span class="grow">${esc(d.name)}</span><span class="muted">${icon("chevron")}</span></button>`).join("");
    html += list.files.map((f) => `<button class="list-item" data-path="${esc(f.path)}"><span class="li-ic">${icon("file")}</span><span class="grow">${esc(f.name)}</span>
      <span class="muted small">${new Date(f.modified * 1000).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}</span></button>`).join("");
    if (!list.dirs.length && !list.files.length) html += `<div class="empty">Пусто.</div>`;
  } else html += `<div class="empty">Загружаю…</div>`;
  view.innerHTML = html;
  const q = $("#n-q");
  q.addEventListener("keydown", async (e) => {
    if (e.key !== "Enter") return;
    state.notesQuery = q.value.trim();
    if (!state.notesQuery) { state.notesResults = null; renderNotes(); return; }
    try { state.notesResults = (await api("notes/search?q=" + encodeURIComponent(state.notesQuery))).results; renderNotes(); } catch (err) { toast(err.message); }
  });
  $("#n-clear") && ($("#n-clear").onclick = () => { state.notesResults = null; state.notesQuery = ""; renderNotes(); });
  $("#n-new") && ($("#n-new").onclick = newNote);
  bindNotesSwitch();
  $("#n-save").onclick = async () => {
    const text = $("#n-cap").value.trim(); if (!text) return;
    try { const r = await api("capture", { json: { text } }); notify("success"); toast("Записано" + (r.path ? ": " + r.path : "")); $("#n-cap").value = ""; } catch (err) { toast(err.message); }
  };
  view.querySelectorAll("[data-dir]").forEach((b) => b.addEventListener("click", async () => {
    state.notesDir = b.dataset.dir; state.notesList = null; renderNotes();
    try { state.notesList = await api("notes?dir=" + encodeURIComponent(state.notesDir)); renderNotes(); } catch (err) { toast(err.message); }
  }));
  view.querySelectorAll("[data-path]").forEach((b) => b.addEventListener("click", () => openNote(b.dataset.path)));
}

// --- Граф заметок: как в Obsidian + подсказки связей от Арвикса (D32) ---------------------------
const GRAPH_COLORS = ["#8a5cf5", "#19b394", "#4f6bff", "#e8a317", "#e5484d", "#2fb7d6", "#d65db1", "#7cb342", "#ff8a3d", "#9aa3b2"];
const graph = { data: null, nodes: [], edges: [], byId: new Map(), sel: null, hideDaily: true, query: "", local: false,
  zoom: 1, ox: 0, oy: 0, alpha: 1, raf: 0, drag: null, colors: new Map() };

async function loadGraph() {
  try { graph.data = await api("graph"); buildGraph(); } catch (err) { toast(err.message); }
  if (state.tab === "notes" && state.notesView === "graph" && !state.note) renderGraph();
}

function buildGraph() {
  const d = graph.data; if (!d) return;
  const old = new Map(graph.nodes.map((n) => [n.id, n]));
  let nodes = d.nodes.filter((n) => !(graph.hideDaily && n.kind === "daily"));
  let ids = new Set(nodes.map((n) => n.id));
  let edges = d.edges.filter((e) => ids.has(e.s) && ids.has(e.t));
  if (graph.local && graph.sel && ids.has(graph.sel)) {  // локальный граф: выбранная + 2 шага
    const near = new Set([graph.sel]);
    for (let step = 0; step < 2; step++) edges.forEach((e) => { if (near.has(e.s) || near.has(e.t)) { near.add(e.s); near.add(e.t); } });
    nodes = nodes.filter((n) => near.has(n.id)); ids = near; edges = edges.filter((e) => near.has(e.s) && near.has(e.t));
  }
  graph.colors.clear();
  const top = (n) => (n.folder || "").split("/")[0] || "·";
  [...new Set(d.nodes.map(top))].sort().forEach((f, i) => graph.colors.set(f, GRAPH_COLORS[i % GRAPH_COLORS.length]));
  graph.nodes = nodes.map((n, i) => {
    const prev = old.get(n.id), a = (i / Math.max(1, nodes.length)) * Math.PI * 2, r = 60 + Math.random() * 120;
    return { ...n, x: prev ? prev.x : Math.cos(a) * r, y: prev ? prev.y : Math.sin(a) * r, vx: 0, vy: 0,
      r: 4 + Math.sqrt(n.degree) * 2.6, color: graph.colors.get(top(n)) };
  });
  graph.byId = new Map(graph.nodes.map((n) => [n.id, n]));
  graph.edges = edges.map((e) => ({ s: graph.byId.get(e.s), t: graph.byId.get(e.t) }));
  graph.alpha = 1; graph.manual = false;
}

function renderGraph() {
  const d = graph.data;
  const sugg = d ? d.suggestions : [], orphans = d ? d.orphans : [], ghosts = d ? d.ghosts : [];
  const name = (id) => id.split("/").pop().replace(/\.md$/, "");
  const sel = graph.sel && graph.byId.get(graph.sel);
  view.innerHTML = `${notesSwitch()}
    <div class="graph-tools">
      <input id="g-q" type="search" placeholder="Найти на графе" value="${esc(graph.query)}">
      <button class="pill${graph.hideDaily ? " on" : ""}" id="g-daily" title="Отчёты дня">${icon("calendar")} ${graph.hideDaily ? "скрыты" : "видны"}</button>
    </div>
    <div class="graph-wrap"><canvas id="g-canvas" aria-label="Граф заметок"></canvas>
      ${sel ? `<div class="graph-card"><div class="grow"><b>${esc(sel.title)}</b><div class="muted small">${esc(sel.folder || "корень")} · связей ${sel.degree}</div></div>
        <button class="pill" id="g-local">${graph.local ? "Весь граф" : "Рядом"}</button><button class="pill primary" id="g-open">Открыть</button></div>` :
        `<div class="graph-hint muted small">${d ? `${graph.nodes.length} заметок · ${graph.edges.length} связей` : "Строю граф…"} · тап — заметка, щипок — масштаб</div>`}
    </div>
    ${sugg.length ? `<div class="card"><h3>Арвикс предлагает связать</h3>
      <p class="muted small">Заметки говорят об одном, но ссылок между ними нет. Связь — строка «Связи: [[…]]» в конце первой.</p>
      ${sugg.map((s, i) => `<div class="sugg"><div class="grow"><button class="link" data-open="${esc(s.a)}">${esc(name(s.a))}</button> ↔
        <button class="link" data-open="${esc(s.b)}">${esc(name(s.b))}</button>
        <div class="muted small">общее: ${esc([...s.tags.map((t) => "#" + t), ...s.why].join(", "))}</div></div>
        <button class="pill" data-link="${i}">Связать</button></div>`).join("")}</div>` : ""}
    ${orphans.length ? `<details class="card"><summary><b>Одинокие заметки</b> <span class="muted">· ${orphans.length}</span></summary>
      <p class="muted small">Ни одной связи — такую мысль потом не найти. Открой и сошлись на неё из близкой заметки.</p>
      ${orphans.map((o) => `<button class="list-item" data-open="${esc(o)}"><span class="li-ic">${icon("file")}</span><span class="grow">${esc(name(o))}</span></button>`).join("")}</details>` : ""}
    ${ghosts.length ? `<details class="card"><summary><b>Ссылки без заметок</b> <span class="muted">· ${ghosts.length}</span></summary>
      <p class="muted small">На них уже ссылаются, а заметки нет — хороший кандидат на следующую атомарную заметку.</p>
      ${ghosts.map((g) => `<div class="sugg"><span class="grow">${esc(g.name)} <span class="muted small">· ссылок ${g.refs}</span></span>
        <button class="pill" data-ghost="${esc(g.name)}">Создать</button></div>`).join("")}</details>` : ""}`;
  bindNotesSwitch();
  $("#g-daily").onclick = () => { graph.hideDaily = !graph.hideDaily; buildGraph(); renderGraph(); };
  $("#g-q").addEventListener("input", (e) => { graph.query = e.target.value.trim().toLowerCase(); graph.alpha = Math.max(graph.alpha, 0.05); kickGraph(); });
  $("#g-open") && ($("#g-open").onclick = () => openNote(graph.sel));
  $("#g-local") && ($("#g-local").onclick = () => { graph.local = !graph.local; buildGraph(); renderGraph(); });
  view.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => openNote(b.dataset.open)));
  view.querySelectorAll("[data-link]").forEach((b) => b.addEventListener("click", async () => {
    const s = sugg[+b.dataset.link]; b.disabled = true;
    try { await api("note/link", { json: { a: s.a, b: s.b } }); notify("success"); toast("Связал: в «" + name(s.a) + "» добавлена ссылка на «" + name(s.b) + "»"); await loadGraph(); }
    catch (err) { b.disabled = false; toast(err.message); }
  }));
  view.querySelectorAll("[data-ghost]").forEach((b) => b.addEventListener("click", async () => {
    try { const n = await api("note/new", { json: { dir: state.notesDir, name: b.dataset.ghost } }); await openNote(n.path, { edit: true }); }
    catch (err) { toast(err.message); }
  }));
  setupCanvas();
  if (!d) loadGraph();
}

function setupCanvas() {
  const canvas = $("#g-canvas"); if (!canvas) return;
  const dpr = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  graph.ctx = ctx; graph.w = w; graph.h = h;
  const css = getComputedStyle(document.documentElement);
  graph.ink = { text: css.getPropertyValue("--text").trim() || "#ddd", muted: css.getPropertyValue("--muted").trim() || "#888",
    line: css.getPropertyValue("--line").trim() || "#333", accent: css.getPropertyValue("--obs-accent").trim() || "#8a5cf5" };
  const toWorld = (px, py) => [(px - w / 2 - graph.ox) / graph.zoom, (py - h / 2 - graph.oy) / graph.zoom];
  const hit = (px, py) => {
    const [x, y] = toWorld(px, py);
    let best = null, bd = 1e9;
    graph.nodes.forEach((n) => { const dd = (n.x - x) ** 2 + (n.y - y) ** 2; if (dd < bd && dd < (n.r + 10 / graph.zoom) ** 2) { bd = dd; best = n; } });
    return best;
  };
  const pts = new Map();
  canvas.onpointerdown = (e) => {
    canvas.setPointerCapture(e.pointerId);
    const rect = canvas.getBoundingClientRect(), px = e.clientX - rect.left, py = e.clientY - rect.top;
    pts.set(e.pointerId, { x: px, y: py });
    if (pts.size === 2) { const [a, b] = [...pts.values()]; graph.manual = true; graph.drag = { pinch: Math.hypot(a.x - b.x, a.y - b.y), zoom: graph.zoom }; return; }
    const node = hit(px, py);
    graph.drag = node ? { node, moved: false, px, py } : { pan: true, px, py, ox: graph.ox, oy: graph.oy, moved: false };
  };
  canvas.onpointermove = (e) => {
    const rect = canvas.getBoundingClientRect(), px = e.clientX - rect.left, py = e.clientY - rect.top;
    if (pts.has(e.pointerId)) pts.set(e.pointerId, { x: px, y: py });
    const g = graph.drag; if (!g) return;
    if (g.pinch && pts.size === 2) { const [a, b] = [...pts.values()]; graph.zoom = Math.min(4, Math.max(0.25, g.zoom * Math.hypot(a.x - b.x, a.y - b.y) / g.pinch)); kickGraph(); return; }
    if (Math.hypot(px - g.px, py - g.py) > 4) g.moved = true;
    if (g.node && g.moved) { const [x, y] = toWorld(px, py); g.node.x = x; g.node.y = y; g.node.vx = g.node.vy = 0; graph.alpha = Math.max(graph.alpha, 0.3); kickGraph(); }
    else if (g.pan && g.moved) { graph.manual = true; graph.ox = g.ox + px - g.px; graph.oy = g.oy + py - g.py; kickGraph(); }
  };
  canvas.onpointerup = canvas.onpointercancel = (e) => {
    pts.delete(e.pointerId);
    const g = graph.drag; graph.drag = null;
    if (!g || g.pinch) return;
    if (!g.moved) {  // тап
      graph.sel = g.node ? g.node.id : null; haptic("soft");
      if (!graph.sel) graph.local = false;
      renderGraph();
    }
  };
  canvas.onwheel = (e) => { e.preventDefault(); graph.manual = true; graph.zoom = Math.min(4, Math.max(0.25, graph.zoom * (e.deltaY < 0 ? 1.1 : 0.9))); kickGraph(); };
  kickGraph();
}

function kickGraph() { if (!graph.raf) graph.raf = requestAnimationFrame(stepGraph); }

/* Физика: отталкивание всех от всех, пружины по связям, притяжение к центру, затухание.
 * Когда граф успокоился, кадры не рисуются — батарея не тратится. */
function stepGraph() {
  graph.raf = 0;
  if (!$("#g-canvas") || state.tab !== "notes" || state.notesView !== "graph" || state.note) return;
  const N = graph.nodes, a = graph.alpha;
  if (a > 0.004) {
    for (let i = 0; i < N.length; i++) {
      const p = N[i];
      for (let j = i + 1; j < N.length; j++) {
        const q = N[j]; let dx = p.x - q.x, dy = p.y - q.y, d2 = dx * dx + dy * dy || 0.01;
        if (d2 > 40000) continue;
        const f = (700 / d2) * a; dx *= f; dy *= f; p.vx += dx; p.vy += dy; q.vx -= dx; q.vy -= dy;
      }
      const pull = p.degree ? 0.012 : 0.03;  // одинокие держатся ближе, как в Obsidian, а не улетают за край
      p.vx -= p.x * pull * a; p.vy -= p.y * pull * a;
    }
    graph.edges.forEach(({ s, t }) => {
      const dx = t.x - s.x, dy = t.y - s.y, d = Math.hypot(dx, dy) || 1, f = ((d - 70) / d) * 0.05 * a;
      s.vx += dx * f; s.vy += dy * f; t.vx -= dx * f; t.vy -= dy * f;
    });
    N.forEach((n) => { if (graph.drag && graph.drag.node === n) return; n.vx *= 0.82; n.vy *= 0.82; n.x += n.vx; n.y += n.vy; });
    graph.alpha *= 0.985;
  }
  drawGraph();
  if (graph.alpha > 0.004 || graph.drag) graph.raf = requestAnimationFrame(stepGraph);
}

function fitGraph() {
  if (graph.manual || !graph.nodes.length) return;  // человек сам двигал — не мешаем
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  graph.nodes.forEach((n) => { x0 = Math.min(x0, n.x - n.r); y0 = Math.min(y0, n.y - n.r); x1 = Math.max(x1, n.x + n.r); y1 = Math.max(y1, n.y + n.r); });
  const pad = 36, zoom = Math.min(2, Math.max(0.25, Math.min((graph.w - pad * 2) / (x1 - x0 || 1), (graph.h - pad * 2) / (y1 - y0 || 1))));
  graph.zoom += (zoom - graph.zoom) * 0.2;  // плавно, а не рывком
  graph.ox += (-(x0 + x1) / 2 * graph.zoom - graph.ox) * 0.2; graph.oy += (-(y0 + y1) / 2 * graph.zoom - graph.oy) * 0.2;
}

function drawGraph() {
  const { ctx, w, h, ink } = graph; if (!ctx) return;
  fitGraph();
  ctx.clearRect(0, 0, w, h);
  ctx.save(); ctx.translate(w / 2 + graph.ox, h / 2 + graph.oy); ctx.scale(graph.zoom, graph.zoom);
  const sel = graph.sel, q = graph.query;
  const near = new Set();
  if (sel) graph.edges.forEach((e) => { if (e.s.id === sel) near.add(e.t.id); if (e.t.id === sel) near.add(e.s.id); });
  const match = (n) => q && (n.title.toLowerCase().includes(q) || n.name.toLowerCase().includes(q) || n.tags.some((t) => t.includes(q.replace(/^#/, ""))));
  const dim = (n) => (sel && n.id !== sel && !near.has(n.id)) || (q && !match(n));
  ctx.lineWidth = 1 / graph.zoom;
  graph.edges.forEach(({ s, t }) => {
    const on = sel && (s.id === sel || t.id === sel);
    ctx.strokeStyle = on ? ink.accent : ink.line; ctx.globalAlpha = on ? 0.9 : (sel || q ? 0.25 : 0.7);
    ctx.lineWidth = (on ? 2 : 1) / graph.zoom;
    ctx.beginPath(); ctx.moveTo(s.x, s.y); ctx.lineTo(t.x, t.y); ctx.stroke();
  });
  graph.nodes.forEach((n) => {
    ctx.globalAlpha = dim(n) ? 0.18 : 1;
    ctx.fillStyle = n.degree ? n.color : ink.muted;
    ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2); ctx.fill();
    if (n.id === sel || match(n)) { ctx.strokeStyle = ink.accent; ctx.lineWidth = 3 / graph.zoom; ctx.stroke(); }
  });
  ctx.font = `${12 / graph.zoom}px system-ui, sans-serif`; ctx.textAlign = "center"; ctx.fillStyle = ink.text;
  graph.nodes.forEach((n) => {
    const show = n.id === sel || near.has(n.id) || match(n) || graph.zoom > 1.3 || n.degree >= 4;
    if (!show) return;
    ctx.globalAlpha = dim(n) ? 0.25 : 0.95;
    ctx.fillText(n.title.length > 26 ? n.title.slice(0, 25) + "…" : n.title, n.x, n.y + n.r + 13 / graph.zoom);
  });
  ctx.restore(); ctx.globalAlpha = 1;
}

function notesSwitch() {
  return `<div class="seg notes-switch"><button type="button" data-view="list" class="${state.notesView !== "graph" ? "on" : ""}">${icon("list")} Папки</button>
    <button type="button" data-view="graph" class="${state.notesView === "graph" ? "on" : ""}">${icon("graph")} Граф</button></div>`;
}
function bindNotesSwitch() {
  view.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => {
    state.notesView = b.dataset.view; haptic("soft");
    try { localStorage.setItem("arvix_notes_view", state.notesView); } catch (_) { /* приватный режим */ }
    renderNotes();
  }));
}

async function openNote(path, opts = {}) {
  try {
    state.note = await api("note?path=" + encodeURIComponent(path));
    state.noteEdit = !!opts.edit;
    renderNote(); if (!opts.keepScroll) window.scrollTo(0, 0);
    if (TG) { TG.BackButton.show(); TG.BackButton.offClick(noteBack); TG.BackButton.onClick(noteBack); }
  } catch (err) { toast(err.message); }
}
function noteBack() {
  if (state.noteEdit) { leaveEditor(); return; }
  closeNote();
}
function closeNote() {
  state.note = null; state.noteEdit = false;
  if (TG) { TG.BackButton.offClick(noteBack); TG.BackButton.hide(); }
  state.notesList = null; renderNotes();
  api("notes?dir=" + encodeURIComponent(state.notesDir)).then((r) => { state.notesList = r; if (state.tab === "notes" && !state.note) renderNotes(); }).catch(() => {});
}

const noteName = (path) => String(path || "").split("/").pop().replace(/\.md$/, "");
const DRAFT_KEY = (path) => "arvix_draft:" + path;
const draftGet = (path) => { try { return JSON.parse(localStorage.getItem(DRAFT_KEY(path)) || "null"); } catch (_) { return null; } };
const draftSet = (path, d) => { try { d ? localStorage.setItem(DRAFT_KEY(path), JSON.stringify(d)) : localStorage.removeItem(DRAFT_KEY(path)); } catch (_) { /* приватный режим */ } };

function renderNote() {
  if (state.noteEdit) { renderEditor(); return; }
  const n = state.note;
  const doc = obsidian(n.text, n.tasks || {});
  const folder = n.path.includes("/") ? n.path.slice(0, n.path.lastIndexOf("/")) : "Хранилище";
  view.innerHTML = `<div class="note-bar"><button id="n-back" class="note-back">${icon("back")} ${esc(folder.split("/").pop())}</button>
      <button id="n-edit" class="icon-btn" aria-label="Править">${icon("pencil")}</button></div>
    <article class="obs">
      <h1 class="obs-title">${esc(noteName(n.path))}</h1>
      ${doc.props.length ? propsHtml(doc.props) : ""}
      ${doc.html || `<p class="muted">Пустая заметка. ✎ — написать.</p>`}
    </article>`;
  $("#n-back").onclick = closeNote;
  $("#n-edit").onclick = () => { state.noteEdit = true; renderNote(); };
  bindNote();
}

function propsHtml(props) {
  const icon = (p) => (/date|дата/i.test(p.key) || /^\d{4}-\d{2}-\d{2}/.test(p.value) ? "📅" : p.list ? "☰" : /^-?\d+([.,]\d+)?$/.test(p.value) ? "#" : /^(true|false)$/.test(p.value) ? "☑" : "≡");
  const val = (p) => {
    if (p.list) return p.list.length ? p.list.map((v) => `<span class="obs-tag">${esc(v)}</span>`).join(" ") : `<span class="obs-empty">Пусто</span>`;
    return p.value ? esc(p.value) : `<span class="obs-empty">Пусто</span>`;
  };
  return `<details class="obs-props" open><summary>Свойства</summary>
    ${props.map((p) => `<button class="obs-prop" data-prop="${esc(p.key)}" data-line="${p.line}" ${p.list ? "data-list=1" : ""}>
      <span class="obs-prop-key"><i>${icon(p)}</i>${esc(p.key)}</span><span class="obs-prop-val">${val(p)}</span></button>`).join("")}
  </details>`;
}

function bindNote() {
  const n = state.note;
  view.querySelectorAll(".obs input[data-line]").forEach((box) => box.addEventListener("click", async (e) => {
    e.preventDefault(); haptic();
    try {
      const r = await api("note/toggle", { json: { path: n.path, line: +box.dataset.line, sha: n.sha } });
      if (r.task) { await closeTaskFromNote(r.task); return; }
      state.note = r; renderNote(); notify("success");
    } catch (err) { await noteError(err); }
  }));
  view.querySelectorAll("[data-wiki]").forEach((a) => a.addEventListener("click", async (e) => {
    e.preventDefault();
    try {
      const r = await api("notes/search?q=" + encodeURIComponent(a.dataset.wiki));
      const name = a.dataset.wiki.toLowerCase();
      const hit = r.results.find((x) => x.path.toLowerCase().endsWith("/" + name + ".md") || x.path.toLowerCase() === name + ".md") || r.results[0];
      if (hit) openNote(hit.path); else toast("Заметки «" + a.dataset.wiki + "» ещё нет");
    } catch (err) { toast(err.message); }
  }));
  view.querySelectorAll("[data-tag]").forEach((t) => t.addEventListener("click", async () => {
    state.note = null; state.notesQuery = "#" + t.dataset.tag;
    try { state.notesResults = (await api("notes/search?q=" + encodeURIComponent(t.dataset.tag))).results; } catch (_) { state.notesResults = []; }
    if (TG) { TG.BackButton.offClick(noteBack); TG.BackButton.hide(); }
    renderNotes();
  }));
  view.querySelectorAll(".obs-prop").forEach((row) => row.addEventListener("click", () => editProp(row)));
  view.querySelectorAll(".callout.foldable > .callout-title").forEach((t) => t.addEventListener("click", () => t.parentElement.classList.toggle("folded")));
  hydrateAssets(view);
}

/* Галочка у строки-задачи Арвикса закрывает задачу тем же путём, что ✓ на «Сегодня». */
async function closeTaskFromNote(t) {
  const reopen = () => openNote(state.note.path, { keepScroll: true });
  if (t.proof && t.proof !== "confirm") { openReportSheet(t, reopen); return; }
  const r = await api(`tasks/${t.id}/done`, { json: {} });
  notify("success"); toast(`✓ ${t.title} — записал`);
  await reopen();
}

async function noteError(err) {
  if (err.data && err.data.conflict) {
    toast("Заметка изменилась на другом устройстве — открыл свежую");
    state.note = { ...state.note, text: err.data.text, sha: err.data.sha };
    await openNote(state.note.path, { keepScroll: true });
    return;
  }
  notify("error"); toast(err.message);
}

async function editProp(row) {
  const n = state.note, line = +row.dataset.line, key = row.dataset.prop;
  const lines = n.text.split("\n");
  if (row.dataset.list) { state.noteEdit = true; renderNote(); return; }  // списки — в исходнике
  const current = lines[line].slice(lines[line].indexOf(":") + 1).trim();
  const value = prompt(key, current);
  if (value === null || value.trim() === current) return;
  lines[line] = `${key}: ${value.trim()}`;
  try { state.note = await api("note", { json: { path: n.path, text: lines.join("\n"), sha: n.sha } }); renderNote(); notify("success"); }
  catch (err) { await noteError(err); }
}

// --- редактор: исходник, как «Режим исходного кода» в Obsidian ---------------------------------
const TOOLS = [
  ["☐", "Задача", { line: "- [ ] " }], ["H", "Заголовок", { line: "## " }], ["B", "Жирный", { wrap: "**" }], ["I", "Курсив", { wrap: "*" }],
  ["•", "Список", { line: "- " }], ["1.", "Нумерация", { line: "1. " }], ["[[ ]]", "Ссылка", { wrap: "[[", end: "]]" }],
  ["==", "Выделить", { wrap: "==" }], ["❝", "Цитата", { line: "> " }], ["#", "Тег", { insert: "#" }],
];

function renderEditor() {
  const n = state.note;
  const draft = draftGet(n.path);
  const text = draft && draft.sha === n.sha ? draft.text : n.text;
  view.innerHTML = `<div class="note-bar editing"><button id="e-cancel" class="note-back">Отмена</button>
      <span class="note-bar-title">${esc(noteName(n.path))}</span><button id="e-save" class="pill primary">Сохранить</button></div>
    <div class="md-tools">${TOOLS.map(([label, title], i) => `<button type="button" data-tool="${i}" title="${title}" aria-label="${title}">${esc(label)}</button>`).join("")}</div>
    <textarea id="e-text" class="md-source" spellcheck="true" autocapitalize="sentences">${esc(text)}</textarea>
    ${draft && draft.sha === n.sha && draft.text !== n.text ? `<p class="muted small">Восстановлен несохранённый черновик.</p>` : ""}`;
  const ta = $("#e-text");
  const grow = () => { ta.style.height = "auto"; ta.style.height = Math.max(ta.scrollHeight + 4, window.innerHeight * 0.6) + "px"; };
  grow();
  ta.addEventListener("input", () => { grow(); draftSet(n.path, { sha: n.sha, text: ta.value }); });
  ta.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const start = ta.selectionStart, before = ta.value.slice(0, start), line = before.slice(before.lastIndexOf("\n") + 1);
    const m = line.match(/^(\s*)([-*+] \[[ xX]\] |[-*+] |(\d+)[.)] |> )/);
    if (!m) return;
    e.preventDefault();
    if (line.trim() === m[2].trim()) { ta.setRangeText("", start - line.length, start, "end"); return; }  // пустой пункт — выйти из списка
    const next = m[3] ? m[2].replace(/^\d+/, String(+m[3] + 1)) : m[2].replace(/\[[xX]\]/, "[ ]");
    ta.setRangeText("\n" + m[1] + next, start, ta.selectionEnd, "end");
    ta.dispatchEvent(new Event("input"));
  });
  view.querySelectorAll("[data-tool]").forEach((b) => b.addEventListener("pointerdown", (e) => {
    e.preventDefault();  // не забирать фокус у текста — клавиатура не прячется
    applyTool(ta, TOOLS[+b.dataset.tool][2]); haptic("soft");
  }));
  $("#e-cancel").onclick = leaveEditor;
  $("#e-save").onclick = saveEditor;
}

function applyTool(ta, tool) {
  const { selectionStart: s, selectionEnd: e, value } = ta;
  if (tool.line) {
    const ls = value.lastIndexOf("\n", s - 1) + 1;
    const cur = value.slice(ls, value.indexOf("\n", ls) === -1 ? value.length : value.indexOf("\n", ls));
    if (cur.startsWith(tool.line)) ta.setRangeText(cur.slice(tool.line.length), ls, ls + cur.length, "end");
    else ta.setRangeText(tool.line + cur.replace(/^(#{1,6} |[-*+] \[[ xX]\] |[-*+] |\d+[.)] |> )/, ""), ls, ls + cur.length, "end");
  } else if (tool.wrap) {
    const end = tool.end || tool.wrap, sel = value.slice(s, e);
    ta.setRangeText(tool.wrap + sel + end, s, e, "select");
    if (!sel) ta.setSelectionRange(s + tool.wrap.length, s + tool.wrap.length);
    else ta.setSelectionRange(s + tool.wrap.length, e + tool.wrap.length);
  } else ta.setRangeText(tool.insert, s, e, "end");
  ta.focus(); ta.dispatchEvent(new Event("input"));
}

async function saveEditor() {
  const n = state.note, text = $("#e-text").value;
  if (text === n.text) { state.noteEdit = false; draftSet(n.path, null); renderNote(); return; }
  try {
    state.note = await api("note", { json: { path: n.path, text, sha: n.sha } });
    draftSet(n.path, null); state.noteEdit = false; renderNote(); notify("success"); toast("Сохранено");
  } catch (err) {
    if (!(err.data && err.data.conflict)) { notify("error"); toast(err.message); return; }
    openSheet(`<h2>Заметка изменилась</h2>
      <p class="muted small">Пока ты правил, её изменили на другом устройстве (Obsidian на ноутбуке или Арвикс). Выбери версию — вторая не пропадёт молча.</p>
      <div class="field"><label>Их версия</label><pre class="conflict">${esc(err.data.text.slice(0, 1500))}</pre></div>
      <div class="sheet-actions">
        <button class="btn primary" id="c-mine">Оставить мою (их уйдёт)</button>
        <button class="btn" id="c-theirs">Взять их (моя — в Inbox)</button>
      </div>`, () => {
      $("#c-mine").onclick = async () => {
        try { state.note = await api("note", { json: { path: n.path, text, sha: err.data.sha } }); draftSet(n.path, null); state.noteEdit = false; closeSheet(); renderNote(); toast("Сохранено"); }
        catch (e2) { toast(e2.message); }
      };
      $("#c-theirs").onclick = async () => {
        try { await api("capture", { json: { text: `Черновик «${noteName(n.path)}» (не сохранён из-за конфликта):\n${text}` } }); } catch (_) { /* Inbox — запасной путь */ }
        draftSet(n.path, null); state.noteEdit = false; closeSheet(); openNote(n.path); toast("Взял их версию, твою — в Inbox");
      };
    });
  }
}

function leaveEditor() {
  const ta = $("#e-text"), n = state.note;
  if (ta && ta.value !== n.text && !confirm("Выйти без сохранения? Черновик останется на этом устройстве.")) return;
  state.noteEdit = false; renderNote();
}

async function newNote() {
  const name = prompt("Название новой заметки" + (state.notesDir ? ` в «${state.notesDir.split("/").pop()}»` : ""));
  if (!name || !name.trim()) return;
  try {
    const n = await api("note/new", { json: { dir: state.notesDir, name: name.trim() } });
    await openNote(n.path, { edit: true });
    setTimeout(() => { const ta = $("#e-text"); if (ta) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); } }, 80);
  } catch (err) { toast(err.message); }
}

// --- вложения ![[…]]: картинка грузится с ключом в заголовке, а не в URL -----------------------
const assetCache = new Map();
function hydrateAssets(root) {
  root.querySelectorAll("[data-asset]").forEach(async (el) => {
    const path = el.dataset.asset;
    try {
      if (!assetCache.has(path)) {
        const res = await fetch("/api/file?path=" + encodeURIComponent(path), { headers: authHeaders() });
        if (!res.ok) throw new Error();
        assetCache.set(path, URL.createObjectURL(await res.blob()));
      }
      if (el.tagName === "IMG") el.src = assetCache.get(path);
      else { el.href = assetCache.get(path); el.target = "_blank"; }
    } catch (_) { el.replaceWith(Object.assign(document.createElement("span"), { className: "obs-missing", textContent: "⚠ " + path })); }
  });
}

/* Markdown → HTML в стиле режима чтения Obsidian. Сначала экранирование, потом разметка:
 * из заметки в страницу не попадёт ни один тег. Номера строк сохраняются — по ним галочка
 * правит ровно ту строку файла. */
const CALLOUTS = { note: "✎", info: "ℹ", tip: "💡", hint: "💡", important: "💡", success: "✓", check: "✓", done: "✓", question: "?", help: "?",
  faq: "?", warning: "⚠", caution: "⚠", attention: "⚠", failure: "✕", fail: "✕", missing: "✕", danger: "⚡", error: "⚡", bug: "🐞",
  example: "☰", quote: "❝", cite: "❝", abstract: "☰", summary: "☰", tldr: "☰", todo: "☐" };
const IMG_EXT = /\.(png|jpe?g|gif|webp|svg)$/i;

function inlineMd(s) {
  const keep = [];
  const hold = (html) => { keep.push(html); return `\u0001${keep.length - 1}\u0001`; };
  s = esc(s)
    .replace(/`([^`]+)`/g, (_, c) => hold(`<code>${c}</code>`))
    .replace(/!\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|(\d+)(?:x\d+)?)?\]\]/g, (_, name, w) => hold(IMG_EXT.test(name.trim())
      ? `<img class="obs-img" data-asset="${name.trim()}" alt="${name.trim()}"${w ? ` width="${w}"` : ""}>`
      : /\.pdf$/i.test(name.trim()) ? `<a class="obs-file" data-asset="${name.trim()}" href="#">📄 ${name.trim()}</a>`
      : `<a href="#" class="obs-link" data-wiki="${name.trim()}">↳ ${name.trim()}</a>`))
    .replace(/\[\[([^\]|#]+)(?:#([^\]|]*))?(?:\|([^\]]+))?\]\]/g, (_, name, head, alias) =>
      hold(`<a href="#" class="obs-link" data-wiki="${name.trim()}">${alias || name + (head ? " › " + head : "")}</a>`))
    .replace(/!\[([^\]]*)\]\((https:\/\/[^)\s]+)\)/g, (_, alt, url) => hold(`<img class="obs-img" src="${url}" alt="${alt}" loading="lazy">`))
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, (_, t, url) => hold(`<a href="${url}" target="_blank" rel="noopener" class="obs-ext">${t}</a>`))
    .replace(/(^|[\s(])(https?:\/\/[^\s<]+[^\s<.,;:!?)])/g, (_, pre, url) => pre + hold(`<a href="${url}" target="_blank" rel="noopener" class="obs-ext">${url}</a>`))
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/__([^_]+)__/g, "<b>$1</b>")
    .replace(/(^|[^*\w])\*([^*\n]+)\*/g, "$1<i>$2</i>").replace(/(^|[^_\w])_([^_\n]+)_(?!\w)/g, "$1<i>$2</i>")
    .replace(/~~([^~]+)~~/g, "<s>$1</s>")
    .replace(/==([^=]+)==/g, "<mark>$1</mark>")
    .replace(/(^|\s)#([\p{L}\d_/-]*[\p{L}_/-][\p{L}\d_/-]*)/gu, (_, pre, tag) => `${pre}<a href="#" class="obs-tag" data-tag="${tag}">#${tag}</a>`);
  return s.replace(/\u0001(\d+)\u0001/g, (_, i) => keep[+i]);
}

function frontmatter(lines) {
  if (lines[0] !== "---") return { props: [], start: 0 };
  const end = lines.indexOf("---", 1);
  if (end === -1) return { props: [], start: 0 };
  const props = [];
  for (let i = 1; i < end; i++) {
    const m = lines[i].match(/^([^\s:#][^:]*):\s*(.*)$/);
    if (m) {
      let value = m[2].trim().replace(/^["']|["']$/g, "");
      const p = { key: m[1].trim(), value, line: i };
      if (/^\[.*\]$/.test(value)) p.list = value.slice(1, -1).split(",").map((v) => v.trim().replace(/^["']|["']$/g, "")).filter(Boolean);
      props.push(p);
    } else if (props.length && /^\s+-\s*/.test(lines[i])) {
      const last = props[props.length - 1];
      last.list = (last.list || []).concat(lines[i].replace(/^\s+-\s*/, "").replace(/^["']|["']$/g, ""));
    }
  }
  return { props, start: end + 1 };
}

function obsidian(src, tasks = {}, nested = false) {
  const lines = String(src || "").replace(/\r\n?/g, "\n").split("\n");
  const fm = frontmatter(lines);
  const out = [];
  const stack = [];  // открытые списки: {tag, indent}
  let table = null, fence = null, comment = false, para = [];
  const flushPara = () => { if (para.length) { out.push(`<p>${para.map(inlineMd).join("<br>")}</p>`); para = []; } };
  const closeLists = (indent = -1) => {
    while (stack.length && stack[stack.length - 1].indent > indent) out.push(`</li></${stack.pop().tag}>`);
  };
  const closeTable = () => { if (table) { out.push(table.join("") + "</tbody></table></div>"); table = null; } };
  const closeAll = () => { flushPara(); closeLists(); closeTable(); };

  for (let i = fm.start; i < lines.length; i++) {
    let line = lines[i];
    if (fence) {
      if (/^\s*(```|~~~)/.test(line)) { out.push(`<pre class="obs-code"${fence.lang ? ` data-lang="${esc(fence.lang)}"` : ""}><code>${esc(fence.body.join("\n"))}</code></pre>`); fence = null; }
      else fence.body.push(line);
      continue;
    }
    // комментарии Obsidian %% … %% и HTML <!-- … --> в режиме чтения не видны
    if (comment) { if (/%%|-->/.test(line)) comment = false; continue; }
    if (/^\s*(%%|<!--)/.test(line)) { if (!/(%%|-->)\s*$/.test(line.replace(/^\s*(%%|<!--)/, ""))) comment = true; continue; }
    line = line.replace(/%%.*?%%/g, "").replace(/<!--.*?-->/g, "");

    let m;
    if ((m = line.match(/^\s*(```|~~~)\s*([\w+-]*)/))) { closeAll(); fence = { lang: m[2], body: [] }; continue; }
    if (!line.trim()) { flushPara(); closeTable(); if (!(lines[i + 1] || "").match(/^\s*([-*+]|\d+[.)])\s/)) closeLists(); continue; }
    if ((m = line.match(/^(#{1,6})\s+(.*)/))) { closeAll(); out.push(`<h${m[1].length} class="obs-h">${inlineMd(m[2].replace(/\s+#+\s*$/, ""))}</h${m[1].length}>`); continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { closeAll(); out.push("<hr>"); continue; }
    if ((m = line.match(/^>\s?(.*)/))) {
      closeAll();
      const body = [m[1]];
      while (i + 1 < lines.length && /^>/.test(lines[i + 1])) body.push(lines[++i].replace(/^>\s?/, ""));
      const head = body[0].match(/^\[!(\w+)\]([+-]?)\s*(.*)$/);
      if (head) {
        const kind = head[1].toLowerCase(), fold = head[2];
        const title = head[3] || kind.charAt(0).toUpperCase() + kind.slice(1);
        out.push(`<div class="callout c-${esc(kind)}${fold ? " foldable" : ""}${fold === "-" ? " folded" : ""}">
          <div class="callout-title"><span>${CALLOUTS[kind] || "✎"}</span> ${inlineMd(title)}${fold ? `<i class="fold">▾</i>` : ""}</div>
          <div class="callout-body">${obsidian(body.slice(1).join("\n"), {}, true).html}</div></div>`);
      } else out.push(`<blockquote>${obsidian(body.join("\n"), {}, true).html}</blockquote>`);
      continue;
    }
    if (/^\|.*\|\s*$/.test(line)) {
      flushPara(); closeLists();
      const cells = line.trim().slice(1, -1).split("|").map((c) => c.trim());
      if (!table) {
        const header = /^\|[\s:|-]+\|\s*$/.test(lines[i + 1] || "");
        table = [`<div class="obs-table"><table>${header ? `<thead><tr>${cells.map((c) => `<th>${inlineMd(c)}</th>`).join("")}</tr></thead>` : ""}<tbody>`];
        if (header) { i++; continue; }
      }
      table.push(`<tr>${cells.map((c) => `<td>${inlineMd(c)}</td>`).join("")}</tr>`);
      continue;
    }
    if ((m = line.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/)) || (m = line.match(/^(\s*)([-*+])()$/))) {
      flushPara(); closeTable();
      const indent = m[1].replace(/\t/g, "    ").length, tag = /\d/.test(m[2]) ? "ol" : "ul";
      closeLists(indent);
      if (stack.length && stack[stack.length - 1].indent === indent && stack[stack.length - 1].tag !== tag) out.push(`</li></${stack.pop().tag}>`);
      const top = stack[stack.length - 1];
      if (!top || top.indent < indent) { out.push(`<${tag}${tag === "ol" ? ` start="${parseInt(m[2], 10)}"` : ""}>`); stack.push({ tag, indent }); }
      else out.push("</li>");
      const task = m[3].match(/^\[([ xX/-])\]\s?(.*)$/);
      if (task) {
        const checked = task[1] !== " ", linked = tasks[String(i)];
        out.push(`<li class="task-item${checked ? " is-checked" : ""}"><label class="obs-check"><input type="checkbox"${nested ? " disabled" : ` data-line="${i}"`}${checked ? " checked" : ""}
          aria-label="${checked ? "Снять отметку" : "Отметить"}"></label><span class="task-text">${inlineMd(task[2]) || "&nbsp;"}${linked ? ` <span class="chip accent small">задача${linked.status === "done" ? " ✓" : ""}</span>` : ""}</span>`);
      } else out.push(`<li>${inlineMd(m[3])}`);
      continue;
    }
    if (stack.length && /^\s+\S/.test(line)) { out.push(`<br>${inlineMd(line.trim())}`); continue; }
    closeLists(); closeTable();
    para.push(line);
  }
  if (fence) out.push(`<pre class="obs-code"><code>${esc(fence.body.join("\n"))}</code></pre>`);
  closeAll();
  return { props: fm.props, html: out.join("\n") };
}

// --- Прогресс ----------------------------------------------------------------------------------
/* Год квадратами, как на GitHub: колонка — неделя (пн сверху), справа — сегодня.
 * Цвет считает код по сделанной работе (web/api.py::heat_level). Это история, а не игра: серий нет (D41). */
const MONTHS_SHORT = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
function heatCard(heat) {
  if (!heat || !heat.days.length) return "";
  const weeks = [];
  heat.days.forEach((d, i) => { (weeks[Math.floor(i / 7)] ||= []).push(d); });
  let lastMonth = -1;
  const months = weeks.map((w) => {
    const m = new Date(w[0].date).getMonth();
    const label = m !== lastMonth && new Date(w[0].date).getDate() <= 7 ? MONTHS_SHORT[m] : "";
    if (label) lastMonth = m;
    return `<span>${label}</span>`;
  }).join("");
  const today = heat.days[heat.days.length - 1].date;
  const cells = weeks.map((w) => `<div class="heat-col">${w.map((d) => `<button class="heat-cell l${d.level}${d.rest ? " rest" : ""}${d.date === today ? " today" : ""}"
    data-heat="${d.date}" aria-label="${esc(d.date)}"></button>`).join("")}</div>`).join("");
  return `<div class="card heat-card"><div class="heat-head">
      <div><b class="heat-big">${heat.active}</b><span class="muted small"> дн с работой за год</span></div></div>
    <div class="heat-scroll" id="heat-scroll"><div class="heat-grid">
      <div class="heat-days"><span></span><span>пн</span><span></span><span>ср</span><span></span><span>пт</span><span></span></div>
      <div><div class="heat-months">${months}</div><div class="heat-cols">${cells}</div></div></div></div>
    <div class="heat-foot"><span class="muted small" id="heat-info">Тап по дню — что в нём было</span>
      <span class="heat-legend muted small">меньше <i class="heat-cell l0"></i><i class="heat-cell l1"></i><i class="heat-cell l2"></i><i class="heat-cell l3"></i><i class="heat-cell l4"></i> больше</span></div></div>`;
}
function bindHeat(heat) {
  const box = $("#heat-scroll"); if (!box || !heat) return;
  box.scrollLeft = box.scrollWidth;  // сегодня — справа, как на GitHub
  const byDate = new Map(heat.days.map((d) => [d.date, d]));
  box.querySelectorAll("[data-heat]").forEach((c) => c.addEventListener("click", () => {
    const d = byDate.get(c.dataset.heat); if (!d) return;
    box.querySelectorAll(".heat-cell.sel").forEach((x) => x.classList.remove("sel")); c.classList.add("sel"); haptic("soft");
    const date = new Date(d.date).toLocaleDateString("ru-RU", { day: "numeric", month: "long", weekday: "short" });
    const parts = d.level < 0 ? ["до начала учёта"] : [
      d.total ? `${d.done} из ${d.total} задач${d.completion != null ? ` (${Math.round(d.completion)} %)` : ""}` : "задач не было",
      d.deep_min ? `глубокая ${hm(d.deep_min)}` : "", d.focus ? `фокус ×${d.focus}` : "", d.rest ? "день отдыха" : ""].filter(Boolean);
    $("#heat-info").textContent = `${date}: ${parts.join(" · ")}`;
  }));
}

function renderProgress() {
  const h = state.history;
  let html = "";
  if (!h) html = `<div class="empty">Загружаю…</div>`;
  else if (h.gentle) html = `<div class="card note-card">Сегодня без цифр. Прогресс подождёт — восстановление тоже часть плана.</div>`;
  else {
    const w = h.week;
    html += heatCard(h.heat);
    html += `<div class="card"><h3>Неделя</h3>
      <div class="row"><span>Сделано</span><b>${hm(w.productive_min)} из ${hm(w.budget_min)}</b></div><div class="bar"><i style="width:${Math.min(100, 100 * w.productive_min / Math.max(1, w.budget_min))}%"></i></div>
      <div class="row" style="margin-top:6px"><span>Глубокая работа</span><b>${hm(w.deep_min)} из ${hm(w.deep_budget_min)}</b></div><div class="bar deep"><i style="width:${Math.min(100, 100 * w.deep_min / Math.max(1, w.deep_budget_min))}%"></i></div>
      <div class="pills" style="margin-top:10px">${w.quotas.map((q) => `<span class="chip ${q.done >= q.need ? "green" : ""}">${esc(q.label)} ${q.done}/${q.need}</span>`).join("")}</div></div>`;
    html += chartCard("Выполнение, %", h.days, (d) => d.completion, 100, "var(--accent)");
    html += chartCard("Сон, часы", h.days, (d) => (d.sleep_min == null ? null : d.sleep_min / 60), 10, "var(--accent-2)", 7.5);
    html += chartCard("Глубокая работа, мин", h.days, (d) => d.deep_min, null, "var(--warn)");
    if (h.goals.length) {
      html += `<div class="card"><h3>Цели</h3>${h.goals.map((g) => `<div class="goal" style="padding-left:${g.depth * 14}px">
        <div class="t">${g.status === "done" ? "●" : "○"} ${esc(g.title)}</div>
        <div class="muted small">${[g.deadline ? "до " + esc(g.deadline) : "", g.metric ? esc(g.metric) : ""].filter(Boolean).join(" · ")}</div></div>`).join("")}</div>`;
    }
    if (h.lessons && h.lessons.length) {
      html += `<div class="card"><h3>Уроки</h3>${h.lessons.slice().reverse().map((x) => `<div class="row"><span>${esc(x.subject)}: ${esc(x.topic)}</span>
        <span class="chip ${x.score >= 70 ? "green" : x.score != null ? "yellow" : ""}">${x.score != null ? x.score + "%" : "—"}</span></div>`).join("")}</div>`;
    }
  }
  html += `<div class="card"><h3>Приложение</h3>
    ${TG ? `<button class="btn" id="install">${icon("download")} Установить на телефон</button><p class="muted small">Откроется Chrome — там кнопка «Установить» (или ⋮ → «Установить приложение»): появится иконка Арвикса, как у обычного приложения. Ссылка одноразовая, живёт 15 минут.</p>` :
    `${standalone() ? `<p class="muted small">Арвикс установлен как приложение.</p>` : `<button class="btn primary" id="install-pwa">${icon("download")} Установить как приложение</button>
     <p class="muted small">Нет кнопки — меню браузера ⋮ → «Установить приложение» / «На экран Домой».</p>`}
     <button class="btn danger" id="logout">Отвязать это устройство</button>`}
    <p class="muted small">Версия ${esc((state.data && state.data.app_version) || "")}</p></div>`;
  view.innerHTML = html;
  $("#install") && ($("#install").onclick = async () => {
    try { const r = await api("pair"); if (!r.url) { toast("На сервере не задан адрес приложения"); return; } TG.openLink(r.url); } catch (err) { toast(err.message); }
  });
  $("#install-pwa") && ($("#install-pwa").onclick = installApp);
  if (h && !h.gentle) bindHeat(h.heat);
  $("#logout") && ($("#logout").onclick = () => { try { localStorage.removeItem(TOKEN_KEY); } catch (_) { /* нет */ } renderLogin(); });
}

function chartCard(title, days, pick, max, color, target) {
  const vals = days.map(pick);
  const top = max || Math.max(1, ...vals.filter((v) => v != null));
  const W = 300, H = 110, n = vals.length, bw = W / n;
  const bars = vals.map((v, i) => v == null ? "" :
    `<rect x="${(i * bw + 1).toFixed(1)}" y="${(H - (H * Math.min(v, top)) / top).toFixed(1)}" width="${Math.max(1, bw - 2).toFixed(1)}" height="${((H * Math.min(v, top)) / top).toFixed(1)}" rx="2" fill="${color}" opacity="${i === n - 1 ? 1 : 0.75}"><title>${days[i].date}: ${Math.round(v * 10) / 10}</title></rect>`).join("");
  const line = target ? `<line x1="0" x2="${W}" y1="${H - (H * target) / top}" y2="${H - (H * target) / top}" stroke="var(--muted)" stroke-dasharray="4 4" stroke-width="1"/>` : "";
  const known = vals.filter((v) => v != null);
  const avg = known.length ? known.reduce((a, b) => a + b, 0) / known.length : null;
  return `<div class="card"><h3>${title}${avg != null ? ` <span style="float:right;text-transform:none">в среднем ${Math.round(avg * 10) / 10}</span>` : ""}</h3>
    <svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${title}">${bars}${line}</svg>
    <div class="legend"><span>${days[0].date.slice(8, 10)}.${days[0].date.slice(5, 7)}</span><span>сегодня</span></div></div>`;
}

// --- живые обновления --------------------------------------------------------------------------
async function stream() {
  let delay = 1000;
  for (;;) {
    try {
      const res = await fetch("/api/stream", { headers: authHeaders() });
      if (res.status === 401) { renderLogin(); return; }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      delay = 1000;
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
          const line = chunk.split("\n").find((l) => l.startsWith("data: "));
          if (line) onChange(JSON.parse(line.slice(6)));
        }
      }
    } catch (_) { /* сеть пропала — переподключимся */ }
    await new Promise((r) => setTimeout(r, delay));
    delay = Math.min(delay * 2, 15000);
  }
}

let refreshTimer;
function onChange(ev) {
  if (ev.v === state.version) return;
  state.version = ev.v;
  const wasThinking = state.thinking;
  state.thinking = ev.thinking || "";
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(async () => {
    try {
      state.data = await api("state"); renderTop();
      if (state.tab === "chat") {
        const r = await api("messages");
        state.messages = r.messages; state.thinking = r.thinking || "";
        if (!$("#msg") || document.activeElement !== $("#msg") || wasThinking) renderChat();
        else renderChat();
      } else {
        const r = await api("messages");
        const last = r.messages.length ? r.messages[r.messages.length - 1] : null;
        if (last && last.id > state.seen && last.who === "arvix") $("#chat-dot").classList.remove("hidden");
        if (state.tab === "today") renderToday();
        if (state.tab === "progress") { state.history = await api("history?days=30"); renderProgress(); }
      }
    } catch (err) { if (err.auth) renderLogin(); }
  }, 250);
}

// --- старт -------------------------------------------------------------------------------------
if (TG) {
  document.documentElement.classList.add("tg");
  TG.ready(); TG.expand();
  try { TG.setHeaderColor("secondary_bg_color"); TG.setBackgroundColor("secondary_bg_color"); } catch (_) { /* старый клиент */ }
  if (TG.colorScheme) document.documentElement.dataset.theme = TG.colorScheme;
}
if ("serviceWorker" in navigator && !TG) navigator.serviceWorker.register("sw.js").catch(() => {});

/* «Поделиться → Арвикс»: service worker сложил файлы и текст в кэш — отправляем их как из 📎. */
async function sendShared() {
  if (!("caches" in window)) return;
  const cache = await caches.open("arvix-share");
  const files = []; let text = "";
  for (const req of await cache.keys()) {
    const res = await cache.match(req);
    if (req.url.endsWith("/text")) text += (text ? "\n" : "") + await res.text();
    else files.push(new File([await res.blob()], decodeURIComponent(res.headers.get("X-File-Name") || "файл"), { type: res.headers.get("Content-Type") || "" }));
    await cache.delete(req);
  }
  history.replaceState(null, "", "/?tab=chat");
  if (files.length) { const ta = $("#msg"); if (ta) ta.value = text; await sendFiles(files); }
  else if (text) { const ta = $("#msg"); if (ta) { ta.value = text; ta.focus(); } }
}

(async function boot() {
  await pairFromHash();
  if (!TG && !token()) { renderLogin(); return; }
  const params = new URLSearchParams(location.search);
  const start = params.get("tab") || (TG && TG.initDataUnsafe && TG.initDataUnsafe.start_param) || "today";
  setTab(["today", "chat", "notes", "progress"].includes(start) ? start : "today");
  stream();
  if (params.get("shared")) sendShared().catch((err) => toast(err.message));
})();
