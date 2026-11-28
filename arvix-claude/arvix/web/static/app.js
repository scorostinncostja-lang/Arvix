/* Arvix — приложение: Mini App в Telegram, PWA на телефоне. Без сборки и зависимостей.
 * Данные — только через /api (arvix/web/server.py). Живые обновления — поток /api/stream. */
"use strict";

const TG = window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData ? window.Telegram.WebApp : null;
const $ = (sel, root = document) => root.querySelector(sel);
const view = $("#view");
const TOKEN_KEY = "arvix_token";
const state = { tab: "today", data: null, messages: [], history: null, notesDir: "", note: null, thinking: "", seen: 0, version: "" };

// --- вход --------------------------------------------------------------------------------------
/* Привязка телефона: #p=<одноразовый код> из ссылки Arvix (живёт 15 минут, срабатывает
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
window.addEventListener("appinstalled", () => { installPrompt = null; toast("Arvix установлен — ищи иконку на экране"); });
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
  study: '<path d="M3 5h6a3 3 0 0 1 3 3v13a4 4 0 0 0-4-3H3zM21 5h-6a3 3 0 0 0-3 3v13a4 4 0 0 1 4-3h5z"/>',
  reply: '<path d="m9 17-5-5 5-5"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/>',
  copy: '<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  chevronDown: '<path d="m6 9 6 6 6-6"/>',
  clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  checks: '<path d="M18 6 7 17l-5-5"/><path d="m22 10-7.5 7.5L13 16"/>',
  mic: '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><path d="M12 19v3"/>',
  clip: '<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
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
  pen: '<path d="M12 20h9"/><path d="M16.376 3.622a1 1 0 0 1 3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506l-2.872.838a.5.5 0 0 1-.62-.62l.838-2.872a2 2 0 0 1 .506-.854z"/>',
  marker: '<path d="m9 11-6 6v3h9l3-3"/><path d="m22 12-4.6 4.6a2 2 0 0 1-2.8 0l-5.2-5.2a2 2 0 0 1 0-2.8L14 4"/>',
  eraser: '<path d="m7 21-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21"/><path d="M22 21H7"/><path d="m5 11 9 9"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
  redo: '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
  sidebar: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/><path d="m16 15-3-3 3-3"/>',
};
const icon = (name, cls = "") => `<svg class="ic${cls ? " " + cls : ""}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON_PATHS[name] || ""}</svg>`;

const MODE_CLASS = { green: "green", normal: "green", yellow: "yellow", red: "red", pressure: "yellow" };

/* Ноутбук: от 900 px слева боковая панель, «Сегодня» в две колонки, заметки — список и заметка рядом
 * (как в Obsidian), окна — по центру. Порог тот же, что в app.css. Телефон и Mini App не меняются. */
const WIDE = window.matchMedia("(min-width: 900px)");
const isWide = () => WIDE.matches;
WIDE.addEventListener("change", () => { if (token() || TG) render(); });

// --- каркас ------------------------------------------------------------------------------------
document.querySelectorAll("[data-ic]").forEach((el) => { el.innerHTML = icon(el.dataset.ic); });

function setTab(tab) {
  if (tab === "chat" && state.tab !== "chat") { chatUI.stick = true; chatUI.unread = 0; }
  if (tab !== "chat") closeMsgMenu();
  state.tab_prev = state.tab;
  state.tab = tab;
  renderTop();
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  if (tab === "chat") { $("#chat-dot").classList.add("hidden"); }
  state.note = tab === "notes" ? state.note : null;
  render();
  load(tab);
  window.scrollTo(0, tab === "chat" ? document.body.scrollHeight : 0);
}

/* Свернуть боковую панель (от 900 px: ноутбук, планшет горизонтально) в полосу значков. Выбор помнится
 * на этом устройстве; подписи разделов уходят в подсказку. На телефоне панели нет — там нижние вкладки. */
const SIDE_KEY = "arvix_side_mini";
function setSideMini(mini, animate = false) {
  const root = document.documentElement;
  if (animate) { root.classList.add("side-anim"); setTimeout(() => { root.classList.remove("side-anim"); window.dispatchEvent(new Event("resize")); }, 220); }
  root.classList.toggle("side-mini", mini);
  const t = $("#side-toggle"), label = mini ? "Развернуть панель" : "Свернуть панель";
  t.setAttribute("aria-expanded", String(!mini)); t.setAttribute("aria-label", label); t.title = `${label} (Ctrl+B)`;
  document.querySelectorAll("#tabs button[data-tab]").forEach((b) => {
    b.title = mini ? `${b.querySelector(".lbl").textContent} (Ctrl+${TABS.indexOf(b.dataset.tab) + 1})` : `Ctrl+${TABS.indexOf(b.dataset.tab) + 1}`;
  });
  try { mini ? localStorage.setItem(SIDE_KEY, "1") : localStorage.removeItem(SIDE_KEY); } catch (_) { /* приватный режим */ }
}
const toggleSide = () => setSideMini(!document.documentElement.classList.contains("side-mini"), true);
$("#side-toggle").onclick = () => { haptic(); toggleSide(); };

$("#tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-tab]");
  if (b) { haptic(); setTab(b.dataset.tab); }
});

async function load(tab = state.tab) {
  try {
    if (tab === "today" || tab === "study" || !state.data) state.data = await api("state");
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
  $("#top-sub").classList.remove("typing-sub");
  if (state.tab === "chat") { chatHeader(); renderMode(d); return; }  // в чате шапка — как у собеседника в Telegram
  if (!d) return;
  const date = new Date(d.now);
  $("#top-day").textContent = d.weekday + ", " + date.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
  const s = d.stats;
  $("#top-sub").textContent = d.gentle ? "Мягкий день" : s ? `${s.done} из ${s.total}` : "";
  renderMode(d);
}

function renderMode(d) {
  if (!d) return;
  const mode = $("#top-mode");
  mode.textContent = d.mode_label;
  mode.className = "chip mode " + (MODE_CLASS[d.mode] || "");
}

function render() {
  if (state.tab === "today") renderToday();
  else if (state.tab === "chat") renderChat();
  else if (state.tab === "notes") renderNotes();
  else if (state.tab === "study") renderStudy();
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
    <img src="icon.svg" alt="">
    <h1>Arvix</h1>
    <p class="muted">Откройте приложение из Telegram — кнопка «Arvix» слева от поля ввода в чате с ботом.</p>
    <p class="muted small">Чтобы установить на телефон: в Telegram откройте приложение → «Прогресс» → «Установить на телефон».</p>
  </div>`;
}

// --- Сегодня -----------------------------------------------------------------------------------
function renderToday() {
  const d = state.data;
  if (!d) { view.innerHTML = `<div class="empty">Загружаю…</div>`; return; }
  let html = `<div class="today-grid"><div class="today-side">`;
  if (d.gentle) {
    html += `<div class="card note-card">${richText(d.note)}</div>`;
  } else if (d.stats) {
    const s = d.stats;
    // Только факты дня (D41): задачи, глубокая работа, сон. Ни очков, ни здоровья, ни уровня.
    const sleep = s.sleep_min == null ? `<b>${s.sleep_guess ? "≈" + hm(s.sleep_guess.duration_min) : "—"}</b><span>${s.sleep_guess ? "сон — подтверди" : "сон не записан"}</span>`
      : `<b>${hm(s.sleep_min)}</b><span>сон, норма ${hm(s.sleep_target)}</span>`;
    html += `<div class="stats">
      <div class="stat"><b>${s.done}/${s.total}</b><span>задач</span><div class="bar"><i style="width:${s.total ? (100 * s.done / s.total) : 0}%"></i></div></div>
      <div class="stat"><b>${hm(s.deep_min)}</b><span>глубокая из ${hm(s.deep_target)}</span><div class="bar deep"><i style="width:${Math.min(100, 100 * s.deep_min / Math.max(1, s.deep_target))}%"></i></div></div>
      <div class="stat tap" id="sleep-stat" role="button" tabindex="0" title="${s.sleep_min == null ? "Записать сон" : "Поправить сон"}">${sleep}<div class="bar"><i style="width:${s.sleep_min == null ? 0 : Math.min(100, 100 * s.sleep_min / Math.max(1, s.sleep_target))}%"></i></div></div>
    </div>`;
  }
  if (installPrompt && !TG && !standalone()) {
    html += `<div class="card install-card"><div><b>Arvix как приложение</b><div class="muted small">Иконка на экране, своё окно, без адресной строки</div></div>
      <button class="pill primary" id="install-now">Установить</button></div>`;
  }
  const due = (d.study_topics || []).filter((topic) => topic.review_due && topic.review_due <= d.date);
  if (due.length) html += '<button id="study-due" class="card study-topic"><strong>Пора повторить</strong><span class="muted small">' +
    esc(due.slice(0, 3).map((topic) => topic.title).join(" · ")) + '</span></button>';
  html += focusCard(d);
  html += `</div><div class="today-main">`;
  const items = [...(d.tasks || []).map((t) => ({ ...t, kind: "task" })), ...(d.busy || []).map((b) => ({ ...b, kind: "busy" }))]
    .sort((a, b) => (a.start || "99").localeCompare(b.start || "99"));
  if (d.yesterday && d.yesterday.length) {  // после полуночи, до 04:00: вчерашнее ещё можно закрыть
    html += `<div class="section-title first"><span>Вчера — не закрыто</span><span>до 04:00</span></div>` + d.yesterday.map((t) => taskRow(t)).join("");
  }
  html += `<div class="section-title${d.yesterday && d.yesterday.length ? "" : " first"}"><span>План дня</span><span>${d.day_type ? esc(d.day_type) : ""}</span></div>`;
  html += items.length ? items.map((t) => (t.kind === "busy" ? busyRow(t) : taskRow(t))).join("") :
    `<div class="empty">На сегодня задач нет.<br><span class="small">Нажми «+»${isWide() ? " (Alt+N)" : ""} или напиши Arvix: «добавь физику в 18:00 на час».</span></div>`;
  if (d.debts && d.debts.length) {
    html += `<div class="section-title"><span>Долг</span><span>${d.debts.length}</span></div>` + d.debts.map((t) => taskRow(t, true)).join("");
  }
  if (d.tomorrow && d.tomorrow.length) {
    html += `<details class="card"><summary><b>Завтра</b> <span class="muted">· ${d.tomorrow.length}</span></summary>
      <div style="margin-top:8px">${d.tomorrow.map((t) => `<div class="row"><span>${esc(t.start || "--:--")} ${esc(t.title)}</span><span class="muted small">${hm(t.duration_min)}</span></div>`).join("")}</div></details>`;
  }
  html += `</div></div>`;
  view.innerHTML = html;
  bindToday();
  if ($("#study-due")) $("#study-due").onclick = () => setTab("study");
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
        ${(() => { const t = f.task_id && findTask(f.task_id); return t && t.guide ? guideHtml(t.guide, true) : ""; })()}
        <div class="pills">${f.study ? `<button class="pill primary" data-act="study" data-id="${esc(f.task_id)}">Занятие</button>` : ""}${paused ? `<button class="pill primary" data-act="focus-op" data-op="resume">${icon("play")} Дальше</button>` : `<button class="pill" data-act="focus-op" data-op="pause">${icon("pause")} Пауза</button>`}
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
    <div class="muted small" style="margin-top:6px">${isWide() ? "Телефон — подальше от стола." : "Телефон экраном вниз."} Пауза и отмена — на таймере.</div>${list}</div>`;
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
  // «Как сделать» (D62): шаги есть — сколько; нет, а задача открыта — спросить Arvix одним касанием
  if (t.guide) chips.push(`<button type="button" class="chip guide-chip" data-act="${t.sphere === "learning" && t.open ? "study" : "more"}" data-id="${t.id}">🧭 ${t.guide.steps.length} ${plural(t.guide.steps.length, "шаг", "шага", "шагов")}</button>`);
  else if (t.open && !debt) chips.push(`<button type="button" class="chip guide-chip ask" data-act="guide" data-id="${t.id}">🧭 Как?</button>`);
  let acts = "";
  if (t.status === "planned") acts = `<button class="icon-btn go" data-act="start" data-id="${t.id}" aria-label="Начать">${icon("play")}</button>`;
  if (t.open || debt) acts += `<button class="icon-btn ok" data-act="done" data-id="${t.id}" aria-label="Сделано">${icon("check")}</button>
    <button class="icon-btn" data-act="more" data-id="${t.id}" aria-label="Ещё">${icon("more")}</button>`;
  return `<div class="task ${esc(t.status)}${debt ? " debt" : ""}"><div class="time"><b>${esc(t.start || "—")}</b>${esc(t.end || "")}</div>
    <div class="body"><div class="title">${esc(t.title)}</div><div class="meta">${chips.join("")}</div>
      ${t.status === "active" && t.guide ? guideHtml(t.guide, true) : ""}</div>
    <div class="acts">${acts}</div></div>`;
}

const plural = (n, one, few, many) => (n % 10 === 1 && n % 100 !== 11 ? one : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? few : many);

/* «Как сделать» (D62): что сделать и чем — шаги в твоих инструментах, «готово, когда», куда записать.
 * Пишет Arvix, проверяет код; результат живёт в инструменте (Решу ОГЭ, Anki, заметка), а не в приложении. */
function guideHtml(g, compact = false) {
  if (!g) return "";
  const steps = (g.steps || []).map((s) => `<li><span>${richInline(s.do)}</span>${s.tool ? ` <span class="g-tool">${esc(s.tool)}</span>` : ""}${s.min ? ` <span class="g-min">${s.min} мин</span>` : ""}</li>`).join("");
  return `<div class="guide${compact ? " compact" : ""}"><ol>${steps}</ol>
    ${g.done ? `<div class="g-done"><b>Готово, когда:</b> ${esc(g.done)}</div>` : ""}
    ${!compact && g.save ? `<div class="g-save">Записать: ${esc(g.save)}</div>` : ""}
    ${!compact && g.note_path ? `<button type="button" class="link small" data-open-note="${esc(g.note_path)}">📝 ${esc(noteName(g.note_path))}</button>` : ""}</div>`;
}

/* Заметка из «Сегодня»: шаги прислали путь (заметка своими словами, список инструментов) — открыть во вкладке «Заметки». */
function openNoteFromToday(path) {
  closeSheet(); setTab("notes"); openNote(path);
}

async function askGuide(t) {
  openSheet(`<h2>${esc(t.title)}</h2><div class="guide-wait"><span class="spin"></span>Arvix смотрит твои инструменты, роадмап и журнал ошибок — 10–60 секунд…</div>`);
  try {
    const r = await api(`tasks/${t.id}/guide`, { json: {} });
    notify("success");
    await load("today");
    openTaskSheet(findTask(t.id) || r.task);
  } catch (err) { notify("error"); closeSheet(); toast(err.message); }
}

function findTask(id) {
  const d = state.data || {};
  return [...(d.tasks || []), ...(d.yesterday || []), ...(d.debts || []), ...(d.tomorrow || [])].find((t) => t.id === id);
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

/* Сон (D48): код угадал ночь по «ложусь» и первому сообщению — одно касание; иначе отбой и подъём руками.
 * Запись идёт той же кнопкой z:ok, что в Telegram: одна дорога, ответ приходит в чат. */
function openSleepSheet(guess) {
  const g = guess || {};
  const src = { noted: "ты написал, что ложишься", last: "последнее сообщение" };
  openSheet(`<h2>Как спал?</h2>
    ${guess ? `<p class="muted small">Отбой ≈${g.bedtime} (${src[g.bed_src] || ""}), подъём ≈${g.wake} (первое сообщение) → ${hm(g.duration_min)}</p>
      <button class="btn primary" id="sl-yes">Да, ${hm(g.duration_min)}</button>` : ""}
    <div class="field"><label>Лёг и встал</label><div style="display:flex;gap:8px">
      <input id="sl-bed" type="time" value="${g.bedtime || ""}" style="flex:1"><input id="sl-wake" type="time" value="${g.wake || ""}" style="flex:1">
    </div></div>
    <button class="btn${guess ? "" : " primary"}" id="sl-save">Записать</button>`, () => {
    const send = async (bed, wake) => {
      if (!bed || !wake || bed === wake) { toast("Нужны отбой и подъём"); return; }
      try { await api("button", { json: { data: `z:ok:${bed}-${wake}` } }); notify("success"); closeSheet(); toast("Сон записан"); setTimeout(() => load("today"), 400); }
      catch (err) { toast(err.message); }
    };
    $("#sl-yes") && ($("#sl-yes").onclick = () => send(g.bedtime, g.wake));
    $("#sl-save").onclick = () => send($("#sl-bed").value, $("#sl-wake").value);
  });
}

function bindToday() {
  bindFocusSetup();
  const sleepStat = $("#sleep-stat");
  if (sleepStat) {
    const open = () => { haptic(); openSleepSheet(state.data && state.data.stats && state.data.stats.sleep_guess); };
    sleepStat.onclick = open;
    sleepStat.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } };
  }
  view.querySelectorAll("[data-open-note]").forEach((el) => el.addEventListener("click", () => openNoteFromToday(el.dataset.openNote)));
  view.querySelectorAll("[data-act]").forEach((el) => el.addEventListener("click", async () => {
    const act = el.dataset.act, id = el.dataset.id;
    haptic();
    try {
      if (act === "start") {
        await api(`tasks/${id}/start`, { json: {} });
        await load("today");
        const started = findTask(id);
        if (started && started.sphere === "learning") openStudy(id);
        else toast("Начали");
        return;
      } else if (act === "done") {
        const t = findTask(id);
        if (t && t.proof && t.proof !== "confirm") { openReportSheet(t); return; }
        const r = await api(`tasks/${id}/done`, { json: {} });
        notify("success"); toast("✓ Записал" + (r.debt_closed ? " · долг закрыт" : "") + (r.warnings && r.warnings.length ? "\n" + r.warnings.join("\n") : ""));
      } else if (act === "more") { openTaskSheet(findTask(id)); return; }
      else if (act === "guide") { askGuide(findTask(id)); return; }
      else if (act === "study") { openStudy(id); return; }
      else if (act === "focus-go") {
        const f = state.focusForm, topic = f.target === "topic" ? ($("#focus-topic") ? $("#focus-topic").value.trim() : f.topic) : "";
        await api("focus", { json: { minutes: +f.minutes, task: f.target === "topic" ? null : f.target, topic: topic || null } });
        f.topic = "";
        await load("today");
        toast("Фокус пошёл. Таймер есть и в Telegram.");
        return;
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

/* «Обучение» (D65): навигатор, а не репетитор. Код ведёт шаги, тему, итог и повторения;
 * Arvix зовётся только кнопкой «Разобрать» — на вопрос или фото решения. */
const LADDER_RU = "ошибки → завтра; чисто → 1 · 3 · 7 · 14 · 30 дней";

function relDay(iso, today) {
  const d = Math.round((new Date(iso) - new Date(today)) / 864e5);
  return d < 0 ? "просрочен" : d === 0 ? "сегодня" : d === 1 ? "завтра" : `через ${d} дн`;
}
function scoreText(score) { return score ? `${score.correct}/${score.total}` : ""; }
function topicMeta(t, today) {
  const bits = [];
  if (t.score) bits.push(scoreText(t.score));
  if (t.review === "due") bits.push("пора повторить");
  else if (t.review === "planned") bits.push("повтор " + relDay(t.review_due, today));
  else if (t.review === "mastered") bits.push("закреплено");
  return bits.join(" · ");
}
function trailHtml(history) {
  return (history || []).length ? `<span class="study-trail" aria-label="последние итоги">${history.map((h) =>
    `<i class="${h.clean ? "ok" : "bad"}" title="${esc(h.day)}${h.score ? " · " + scoreText(h.score) : ""}"></i>`).join("")}</span>` : "";
}

function renderStudy() {
  const d = state.data;
  if (!d) return;
  const topics = d.study_topics || [];
  const due = topics.filter((t) => t.review === "due");
  const tasks = (d.tasks || []).filter((t) => t.sphere === "learning");
  const open = tasks.filter((t) => t.open), doneN = tasks.length - open.length;
  const f = d.focus, now = f && f.study ? findTask(f.task_id) : null;
  const taskRowHtml = (t) => `<button class="study-row" data-study-id="${esc(t.id)}">
      <span class="study-time">${esc(t.start || "—")}</span>
      <span class="grow"><strong>${esc(t.title)}</strong><span class="muted small">${hm(t.duration_min)} · ${t.guide ? `${t.guide.steps.length} ${plural(t.guide.steps.length, "шаг", "шага", "шагов")}` : "без шагов"}</span></span>
      <span class="study-go" aria-hidden="true">›</span></button>`;
  const topicRowHtml = (t) => `<button class="study-row" data-topic="${esc(t.title)}">
      <span class="grow"><strong>${esc(t.title)}</strong><span class="muted small">${esc(topicMeta(t, d.date)) || "итога ещё нет"}</span></span>
      ${trailHtml(t.history.slice(-5))}<span class="study-go" aria-hidden="true">›</span></button>`;
  view.innerHTML = `<section class="study-home">
    <h1>Обучение</h1>
    ${now ? `<button class="card study-now" data-study-id="${esc(now.id)}"><span class="muted small">Сейчас идёт фокус</span>
      <strong>${esc(now.title)}</strong><span class="pill primary">Открыть занятие</span></button>` : ""}
    <section class="card"><h3>Сегодня</h3>
      ${open.length ? open.map(taskRowHtml).join("") : `<p class="muted small">Открытых учебных задач нет.</p>`}
      ${doneN ? `<p class="muted small">Сделано сегодня: ${doneN}</p>` : ""}</section>
    ${due.length ? `<section class="card"><h3>Пора повторить · ${due.length}</h3>${due.map((t) => `<div class="study-due-row">
      <button class="study-row" data-topic="${esc(t.title)}"><span class="grow"><strong>${esc(t.title)}</strong>
        <span class="muted small">${t.score ? "прошлый раз " + scoreText(t.score) : ""}${t.mistakes ? (t.score ? " · " : "") + esc(t.mistakes.slice(0, 60)) : ""}</span></span></button>
      ${t.review_task ? `<span class="chip green">в плане</span>` : `<button class="pill" data-plan-review="${esc(t.title)}">В план · 20 мин</button>`}</div>`).join("")}</section>` : ""}
    <div class="study-quick">
      <button class="study-act" data-quick="help"><b>Разобрать</b><span>вопрос или фото решения</span></button>
      <button class="study-act" data-quick="record"><b>Записать занятие</b><span>занимался вне плана</span></button>
      <button class="study-act" data-quick="add"><b>+ Учебная задача</b><span>в план дня</span></button>
    </div>
    <section class="card"><h3>Темы${topics.length ? " · " + topics.length : ""}</h3>
      ${topics.length ? topics.map(topicRowHtml).join("") : `<p class="muted small">Тема появится после первого итога: сколько верно и где ошибки. Повторения Arvix поставит сам (${LADDER_RU}).</p>`}</section>
    ${d.tools_note ? '<button class="link" id="study-tools">Мои учебные инструменты ↗</button>' : ""}
  </section>`;
  view.querySelectorAll("[data-study-id]").forEach((b) => { b.onclick = () => { haptic(); openStudy(b.dataset.studyId); }; });
  view.querySelectorAll("[data-topic]").forEach((b) => { b.onclick = () => { haptic(); openTopic(b.dataset.topic); }; });
  view.querySelectorAll("[data-plan-review]").forEach((b) => { b.onclick = () => planReview(b.dataset.planReview, b); });
  view.querySelectorAll("[data-quick]").forEach((b) => {
    b.onclick = () => {
      haptic();
      if (b.dataset.quick === "help") openStudyHelp({});
      else if (b.dataset.quick === "record") openStudyRecord();
      else openAddSheet();
    };
  });
  if ($("#study-tools")) $("#study-tools").onclick = () => openNoteFromToday(d.tools_note);
}

function bindStudyRecorder(button, input) {
  let stop;
  button.onclick = async () => {
    if (stop) { stop(); return; }
    button.disabled = true;
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!button.isConnected || $("#sheet").classList.contains("hidden")) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      const type = ["audio/ogg", "audio/webm", "audio/mp4"].find((format) => MediaRecorder.isTypeSupported(format));
      const recording = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
      const audio = [];
      const active = () => button.isConnected && !$("#sheet").classList.contains("hidden");
      stop = () => { if (recording.state === "recording") recording.stop(); };
      recording.ondataavailable = (event) => { if (event.data.size) audio.push(event.data); };
      recording.onstop = async () => {
        clearInterval(watch);
        stream.getTracks().forEach((track) => track.stop());
        stop = null;
        if (!active()) return;
        button.disabled = true;
        button.textContent = "Распознаю…";
        try {
          const blob = new Blob(audio, { type: recording.mimeType || "audio/webm" });
          if (!blob.size) throw new Error("Пустая запись");
          const r = await api("study-transcribe", { body: blob, headers: { "Content-Type": blob.type } });
          if (active()) input.value = [input.value.trim(), r.text].filter(Boolean).join(" ").slice(0, 3000);
        } catch (err) { if (active()) toast(err.message); }
        finally { button.disabled = false; button.textContent = "Надиктовать"; }
      };
      recording.start();
      button.textContent = "Готово, распознать";
      const started = Date.now();
      const watch = setInterval(() => { if (!active() || Date.now() - started >= 60000) stop?.(); }, 300);
    } catch (err) {
      stream?.getTracks().forEach((track) => track.stop());
      toast(err.message);
    } finally { button.disabled = false; }
  };
}

async function encodeStudyPhoto(file) {
  const bitmap = await createImageBitmap(file);
  try {
    const scale = Math.min(1, 1800 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.88).split(",")[1];
  } finally { bitmap.close(); }
}

function studyApi(body, taskId) {
  return api(taskId ? `tasks/${encodeURIComponent(taskId)}/study` : "study", { json: body });
}

/* Итог занятия — одна форма для задачи и для занятия вне плана. Пусто = «сделал, ошибок нет». */
function finishFormHtml(doneText = "") {
  return `<div class="study-finish">
    ${doneText ? `<p class="muted small"><b>Готово, когда:</b> ${esc(doneText)}</p>` : ""}
    <div class="study-score"><span>Верно</span><input id="st-correct" type="number" inputmode="numeric" min="0" max="999" placeholder="—">
      <span>из</span><input id="st-total" type="number" inputmode="numeric" min="1" max="999" placeholder="—"></div>
    <div class="field"><label for="st-mistakes">Ошибки — где и почему</label>
      <textarea id="st-mistakes" rows="2" maxlength="1500" placeholder="№2: забыл скобки при подстановке. Пусто — без ошибок"></textarea></div>
    <p class="muted small">Повторение поставит Arvix: ${LADDER_RU}.</p></div>`;
}
function readFinish(root) {
  const correct = root.querySelector("#st-correct").value, total = root.querySelector("#st-total").value;
  const mistakes = root.querySelector("#st-mistakes").value.trim();
  if ((correct === "") !== (total === "")) throw new Error("Заполни оба числа: сколько верно и из скольких");
  if (total !== "" && +correct > +total) throw new Error("Верных больше, чем всего");
  const body = { mistakes };
  if (total !== "") { body.correct = +correct; body.total = +total; }
  if (!mistakes && total === "") body.result = "Сделано по плану, без ошибок";
  return body;
}
function recordToast(step) {
  const due = step.review === "mastered" ? "тема закреплена" : step.review_due ? "повтор " + relDay(step.review_due, state.data?.date || step.review_due) : "";
  toast(["Итог записан", step.closed ? "задача закрыта" : "", due].filter(Boolean).join(" · "));
}

/* Занятие по задаче: текущий шаг крупно, «Сделал» двигает дальше (код, без модели), в конце — итог.
 * Номер шага — только в этом браузере: это указатель, а не факт для журнала. */
function openStudy(id, topicOverride = "") {
  const t = findTask(id);
  if (!t) return;
  const steps = t.guide?.steps || [];
  const key = "arvix-step-" + id;
  let at = Math.min(+(localStorage.getItem(key) || 0), steps.length);
  let finishing = !steps.length || at >= steps.length;
  let topic = null, timer;
  const setAt = (n) => { at = Math.max(0, Math.min(n, steps.length)); localStorage.setItem(key, String(at)); };
  const focus = () => { const f = state.data?.focus; return f && f.task_id === id ? f : null; };
  const left = (f) => {
    const ms = Math.max(0, new Date(f.until).getTime() - (f.paused_at ? new Date(f.paused_at).getTime() : Date.now()));
    return `${String(Math.floor(ms / 60000)).padStart(2, "0")}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, "0")}`;
  };
  const draw = (error = "") => {
    clearInterval(timer);
    const f = focus(), s = steps[at];
    const last = topic && (topic.score || topic.mistakes) ? `Прошлый раз: ${[scoreText(topic.score), topic.mistakes].filter(Boolean).join(" · ")}` : "";
    openSheet(`<div class="study-session">
      <div><h2>${esc(t.title)}</h2>
        <button class="chip study-topic-chip" id="st-topic">Тема: ${esc(topic?.title || "…")} ✎</button></div>
      ${last ? `<p class="muted small">${esc(last)}</p>` : ""}
      ${f ? `<div class="study-timer">${f.paused_at ? "Пауза" : "Фокус"} · <b id="st-left">${left(f)}</b></div>`
          : t.status === "planned" ? `<button class="pill" data-st="start">${icon("play")} Таймер ${hm(t.duration_min)}</button>` : ""}
      ${error ? `<p role="alert" class="study-error">${esc(error)}</p>` : ""}
      ${steps.length ? `<div class="study-progress" aria-label="шаг ${Math.min(at + 1, steps.length)} из ${steps.length}">${steps.map((_, i) =>
        `<i class="${i < at ? "done" : i === at ? "on" : ""}"></i>`).join("")}</div>` : ""}
      ${!finishing && s ? `<div class="study-step">
          <div class="muted small">Шаг ${at + 1} из ${steps.length}${s.tool ? ` · <span class="g-tool">${esc(s.tool)}</span>` : ""}${s.min ? ` · ${s.min} мин` : ""}</div>
          <p class="study-do">${richInline(s.do)}</p></div>
        <div class="pills"><button class="pill primary" data-st="next">✓ Сделал${at + 1 < steps.length ? ", дальше" : ""}</button>
          <button class="pill" data-st="help">Застрял</button>
          ${at > 0 ? `<button class="pill" data-st="back">← Назад</button>` : ""}</div>
        <button class="link small" data-st="finish">Закончить раньше и записать итог →</button>` : ""}
      ${!steps.length ? `<p class="muted small">Шагов нет — можно попросить Arvix расписать, что сделать и в каком инструменте.</p>
        <button class="pill" data-st="guide">🧭 Как сделать?</button>` : ""}
      ${finishing ? `<h3>Итог</h3>${finishFormHtml(t.guide?.done)}
        <button class="btn primary" data-st="record">Записать итог и закрыть задачу</button>
        <button class="link small" data-st="help">Не понял ошибку — разобрать с Arvix</button>` : ""}
      ${steps.length ? `<details class="study-plan"><summary>Весь план</summary><ol>${steps.map((x, i) =>
        `<li class="${i < at ? "done" : ""}">${richInline(x.do)}</li>`).join("")}</ol>
        ${t.guide?.save ? `<p class="muted small">Записать: ${esc(t.guide.save)}</p>` : ""}</details>` : ""}
      <div class="pills"><button class="pill" data-st="note">📝 Конспект</button><button class="pill" id="st-close">Закрыть</button></div>
    </div>`, (root) => {
      root.querySelector("#st-close").onclick = closeSheet;
      root.querySelector("#st-topic").onclick = () => chooseTopic(topic?.title || "", (chosen) => { topicOverride = chosen; reload(); });
      root.querySelectorAll("[data-st]").forEach((b) => { b.onclick = () => act(b.dataset.st, b); });
      const fl = focus();
      if (fl && !fl.paused_at) timer = setInterval(() => {
        const el = $("#st-left"); if (!el) return clearInterval(timer);
        el.textContent = left(fl);
      }, 1000);
    });
  };
  const reload = async (error = "") => {
    try { topic = await studyApi({ action: "open", topic: topicOverride || undefined }, id); }
    catch (err) { error = err.message; }
    draw(error);
  };
  const act = async (op, button) => {
    haptic();
    if (op === "next") { setAt(at + 1); finishing = at >= steps.length; return draw(); }
    if (op === "back") { setAt(at - 1); finishing = false; return draw(); }
    if (op === "finish") { finishing = true; return draw(); }
    if (op === "help") return openStudyHelp({ taskId: id, topic: topic?.title, back: () => openStudy(id, topicOverride) });
    if (op === "guide") { askGuide(t); return; }
    button.disabled = true;
    try {
      if (op === "start") {
        await api(`tasks/${id}/start`, { json: {} });
        await load(state.tab);
        return draw();
      }
      if (op === "note") {
        const r = await studyApi({ action: "note", topic: topic.title, revision: topic.revision }, id);
        return openNoteFromToday(r.note_path);
      }
      if (op === "record") {
        const body = { action: "record", topic: topic.title, revision: topic.revision, close: true, ...readFinish($("#sheet")) };
        const r = await studyApi(body, id);
        if (focus()) await api("focus/stop", { json: {} }).catch(() => null);
        localStorage.removeItem(key);
        notify("success"); recordToast(r); closeSheet(); load(state.tab);
      }
    } catch (err) { notify("error"); button.disabled = false; toast(err.message); }
  };
  draw();
  reload();
}

function chooseTopic(current, done) {
  openSheet(`<form class="study-topic-form"><h2>Тема</h2>
    <p class="muted small">Одна тема — одна линия итогов и повторений. «№20» на разных днях — одна тема.</p>
    <input required id="st-topic-input" maxlength="160" list="known-study-topics" value="${esc(current)}" placeholder="Например: Математика ОГЭ: №20">
    <datalist id="known-study-topics">${(state.data?.study_topics || []).map((t) => `<option value="${esc(t.title)}"></option>`).join("")}</datalist>
    <button class="btn primary">Готово</button></form>`, (sheet) => {
    sheet.querySelector("form").onsubmit = (e) => { e.preventDefault(); const v = sheet.querySelector("input").value.trim(); if (v) done(v); };
  });
}

function topicInputHtml(value = "") {
  return `<div class="field"><label for="st-topic-input">Тема</label>
    <input id="st-topic-input" maxlength="160" list="known-study-topics" value="${esc(value)}" placeholder="Например: Математика ОГЭ: №20">
    <datalist id="known-study-topics">${(state.data?.study_topics || []).map((t) => `<option value="${esc(t.title)}"></option>`).join("")}</datalist></div>`;
}

/* Разбор — единственное место, где зовётся модель. Ничего не записывает в итог. */
function openStudyHelp({ taskId = null, topic = "", back = null }) {
  let photo, answer;
  const draw = (error = "", draft = "") => {
    openSheet(`<div class="study-session">
      <h2>Разобрать с Arvix</h2>
      ${topic ? `<p class="muted small">Тема: ${esc(topic)}</p>` : topicInputHtml()}
      <div class="field"><label for="sh-q">Что не получается</label>
        <textarea id="sh-q" rows="4" maxlength="3000" placeholder="Условие и твой ход. Где застрял?">${esc(draft)}</textarea></div>
      <div class="pills">
        <label class="pill study-file"><input id="sh-photo" type="file" accept="image/*" hidden>📷 ${photo ? esc(photo.name.slice(0, 18)) : "Фото решения"}</label>
        ${navigator.mediaDevices?.getUserMedia && window.MediaRecorder ? '<button class="pill" id="sh-mic">Надиктовать</button>' : ""}</div>
      <button class="btn primary" id="sh-go">Разобрать</button>
      <p class="muted small" id="sh-status" role="status"></p>
      ${error ? `<p role="alert" class="study-error">${esc(error)}</p>` : ""}
      ${answer ? `<div class="card study-answer"><p>${esc(answer.feedback)}</p>
        ${answer.visual ? `<pre class="study-visual">${esc(answer.visual)}</pre>` : ""}
        ${answer.next_step ? `<p><b>Дальше:</b> ${esc(answer.next_step)}</p>` : ""}
        ${answer.source ? `<p class="muted small">${esc(answer.source)}</p>` : ""}</div>` : ""}
      <div class="pills"><button class="pill" id="sh-back">${back ? "← К занятию" : "Закрыть"}</button></div>
    </div>`, (root) => {
      root.querySelector("#sh-back").onclick = () => (back ? back() : closeSheet());
      const mic = root.querySelector("#sh-mic");
      if (mic) bindStudyRecorder(mic, root.querySelector("#sh-q"));
      root.querySelector("#sh-photo").onchange = (e) => { photo = e.target.files[0] || photo; draw("", root.querySelector("#sh-q").value); };
      root.querySelector("#sh-go").onclick = () => submit(root);
    });
  };
  const submit = async (root) => {
    const q = root.querySelector("#sh-q").value.trim();
    const name = topic || root.querySelector("#st-topic-input")?.value.trim() || "";
    if (!name && !taskId) { toast("Укажи тему"); return; }
    if (!q && !photo) { root.querySelector("#sh-q").focus(); return; }
    root.querySelector("#sh-go").disabled = true;
    root.querySelector("#sh-status").textContent = "Arvix разбирает… 10–60 секунд";
    const alive = () => root.isConnected && !$("#sheet").classList.contains("hidden");
    try {
      const opened = await studyApi({ action: "open", topic: name || undefined }, taskId);
      const image = photo ? await encodeStudyPhoto(photo) : undefined;
      const r = await studyApi({ action: "help", topic: opened.title, revision: opened.revision, question: q, photo: image }, taskId);
      topic = r.title; answer = r.help; photo = undefined;
      if (alive()) draw("", q);
    } catch (err) { if (alive()) draw(err.message, q); }
  };
  draw();
}

/* Занимался вне плана: тема + итог, без задачи и без модели. */
function openStudyRecord(topic = "") {
  openSheet(`<div class="study-session"><h2>Записать занятие</h2>${topicInputHtml(topic)}${finishFormHtml()}
    <button class="btn primary" id="sr-save">Записать итог</button></div>`, (root) => {
    root.querySelector("#sr-save").onclick = async (e) => {
      const name = root.querySelector("#st-topic-input").value.trim();
      if (!name) { toast("Укажи тему"); return; }
      e.target.disabled = true;
      try {
        const opened = await studyApi({ action: "open", topic: name });
        const r = await studyApi({ action: "record", topic: opened.title, revision: opened.revision, ...readFinish(root) });
        notify("success"); recordToast(r); closeSheet(); load(state.tab);
      } catch (err) { e.target.disabled = false; toast(err.message); }
    };
  });
}

async function planReview(title, button) {
  if (button) button.disabled = true;
  try {
    const opened = await studyApi({ action: "open", topic: title });
    await studyApi({ action: "plan_review", topic: opened.title, revision: opened.revision });
    notify("success"); toast("Повтор в плане на сегодня · 20 мин"); closeSheet(); load(state.tab);
  } catch (err) { if (button) button.disabled = false; toast(err.message); }
}

/* Карточка темы: итоги подряд, последние ошибки, срок повтора, последний разбор. */
function openTopic(title) {
  const t = (state.data?.study_topics || []).find((x) => x.title === title);
  if (!t) return;
  const today = state.data.date;
  const review = t.review === "due" ? "Пора повторить" : t.review === "planned" ? "Повтор " + relDay(t.review_due, today) + ` (${t.review_due})`
    : t.review === "mastered" ? "Закреплено — повторять не нужно" : "";
  openSheet(`<div class="study-session"><h2>${esc(t.title)}</h2>
    ${review ? `<p class="${t.review === "due" ? "study-due-text" : "muted small"}">${esc(review)}</p>` : ""}
    ${t.history.length ? `<div class="study-history">${t.history.map((h) => `<span class="chip ${h.clean ? "green" : "red"}">${esc(h.day.slice(8, 10) + "." + h.day.slice(5, 7))}${h.score ? " · " + scoreText(h.score) : ""}</span>`).join("")}</div>` : ""}
    ${t.mistakes ? `<p><b>Последние ошибки:</b> ${esc(t.mistakes)}</p>` : ""}
    ${t.help ? `<details><summary>Последний разбор</summary><p>${esc(t.help.feedback)}</p>${t.help.next_step ? `<p><b>Дальше:</b> ${esc(t.help.next_step)}</p>` : ""}</details>` : ""}
    <div class="pills">
      ${t.review !== "mastered" && !t.review_task ? `<button class="pill${t.review === "due" ? " primary" : ""}" id="tp-plan">Повтор в план · 20 мин</button>` : ""}
      ${t.review_task ? `<span class="chip green">повтор в плане</span>` : ""}
      <button class="pill" id="tp-record">Записать итог</button>
      <button class="pill" id="tp-help">Разобрать</button>
      <button class="pill" id="tp-note">📝 Конспект</button></div>
  </div>`, (root) => {
    const plan = root.querySelector("#tp-plan");
    if (plan) plan.onclick = () => planReview(t.title, plan);
    root.querySelector("#tp-record").onclick = () => openStudyRecord(t.title);
    root.querySelector("#tp-help").onclick = () => openStudyHelp({ topic: t.title, back: () => openTopic(title) });
    root.querySelector("#tp-note").onclick = async () => {
      try {
        const opened = await studyApi({ action: "open", topic: t.title });
        const r = await studyApi({ action: "note", topic: opened.title, revision: opened.revision });
        openNoteFromToday(r.note_path);
      } catch (err) { toast(err.message); }
    };
  });
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
    <p class="muted small">Без времени — оставь поле пустым, Arvix не станет напоминать. Можно и словами в чате: «добавь физику на завтра в 18:00».</p>`,
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
  const open = t.open || t.status === "debt";
  openSheet(`<h2>${esc(t.title)}</h2>
    <p class="muted small">${esc(t.start || "без времени")} · ${hm(t.duration_min)} · ${esc(t.sphere_ru)}</p>
    ${open && t.sphere === "learning" ? `<button class="btn primary" data-op="study">📘 Открыть занятие</button>`
      : t.guide ? `<div class="guide-box"><h3>🧭 Как сделать</h3>${guideHtml(t.guide)}</div>` : ""}
    ${open ? `<div class="sheet-actions">
      <button class="btn" data-op="part">◐ Сделано частично…</button>
      <button class="btn" data-op="report">📝 Сделано, с отчётом…</button>
      <button class="btn" data-op="defer" data-min="15">⏳ Перенести на 15 мин</button>
      <button class="btn" data-op="defer" data-min="30">⏳ Перенести на 30 мин</button>
      <button class="btn" data-op="defer" data-min="60">⏳ Перенести на час</button>
      <button class="btn danger" data-op="fail">✕ Не сделано…</button>
      <button class="btn danger" data-op="cancel">Отменить задачу…</button>
    </div>` : ""}`, (root) => {
    root.querySelectorAll("[data-open-note]").forEach((el) => { el.onclick = () => openNoteFromToday(el.dataset.openNote); });
    root.querySelectorAll("[data-op]").forEach((b) => b.addEventListener("click", async () => {
      const op = b.dataset.op;
      haptic();
      try {
        if (op === "study") { openStudy(t.id); return; }
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

/* Отчёт: слова и/или фото (D49). Фото уходят в хранилище сразу при выборе — «Сделано» несёт их пути,
 * и голова видит отчёт и фото в контексте дня. На телефоне кнопка открывает камеру или галерею. */
function openReportSheet(t, after = null) {
  const photos = [];  // {path, url}
  openSheet(`<h2>Отчёт</h2><p class="muted small">${esc(t.title)}</p>
    <div class="field"><textarea id="r-report" rows="4" placeholder="Что сделано: цифры, темы, результат"></textarea></div>
    <div class="field"><div class="r-photos" id="r-photos"></div>
      <label class="btn r-add">${icon("clip")} Фото<input id="r-file" type="file" accept="image/*" multiple hidden></label></div>
    <button class="btn primary" id="r-save">Сделано</button>`, () => {
    setTimeout(() => $("#r-report").focus(), 50);
    const draw = () => {
      $("#r-photos").innerHTML = photos.map((p, i) => `<div class="r-photo"><img src="${p.url}" alt=""><button type="button" data-i="${i}" aria-label="Убрать фото">${icon("x")}</button></div>`).join("");
      $("#r-photos").querySelectorAll("button[data-i]").forEach((b) => b.onclick = () => { URL.revokeObjectURL(photos[+b.dataset.i].url); photos.splice(+b.dataset.i, 1); draw(); });
    };
    $("#r-file").onchange = async (e) => {
      const files = [...e.target.files]; e.target.value = "";
      for (const f of files) {
        if (photos.length >= 10) { toast("Не больше 10 фото"); break; }
        try {
          toast("Загружаю фото…");
          const r = await api(`tasks/${t.id}/photo`, { body: f, headers: { "Content-Type": f.type || "image/jpeg", "X-File-Name": encodeURIComponent(f.name || "фото.jpg") } });
          photos.push({ path: r.path, url: URL.createObjectURL(f) }); draw();
        } catch (err) { toast(err.message); }
      }
    };
    $("#r-save").onclick = async () => {
      const report = $("#r-report").value.trim();
      if (!report && !photos.length) { toast("Пара слов или фото"); return; }
      try {
        await api(`tasks/${t.id}/done`, { json: { report: report || null, photos: photos.map((p) => p.path) } });
        notify("success"); closeSheet(); toast(photos.length ? `✓ Записал, фото: ${photos.length}` : "✓ Записал");
        if (after) after(); else load("today");
      } catch (err) { toast(err.message); }
    };
  });
}

// --- Чат ---------------------------------------------------------------------------------------
/* Как в Telegram (D52): ответ на сообщение — свайп влево по пузырю, двойной клик или меню (долгое нажатие,
 * правый клик); цитата в пузыре ведёт к оригиналу; лента не прыгает вниз, пока читаешь старое — для этого ↓.
 * Arvix тоже отвечает цитатой, когда без неё непонятно, на что ответ, — это решает сервер. */
const chatUI = { reply: null, stick: true, unread: 0, lastId: 0 };
const WHO = { me: "Ты", arvix: "Arvix" };
const nearBottom = () => window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 160;
const hhmm = (d) => d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });

function dayLabel(d) {
  const today = new Date(), y = new Date(); y.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "Сегодня";
  if (d.toDateString() === y.toDateString()) return "Вчера";
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "long", ...(d.getFullYear() !== today.getFullYear() ? { year: "numeric" } : {}) });
}

function quoteHtml(q) {
  if (!q) return "";
  return `<button type="button" class="quote ${q.who === "me" ? "q-me" : "q-arvix"}" data-goto="${q.id}"><b>${WHO[q.who] || "Arvix"}</b><span>${esc(plainText(q.text) || "…")}</span></button>`;
}

function msgHtml(m, prev, next, answered) {
  const at = new Date(m.at);
  const same = (o) => o && o.who === m.who && Math.abs(new Date(o.at) - at) < 5 * 60e3 && new Date(o.at).toDateString() === at.toDateString();
  const btns = (m.buttons || []).flat().filter((b) => b && b[1] && !String(b[1]).startsWith("app:"));
  // ✓ — дошло, ✓✓ — Arvix ответил после; часы — ещё в пути
  const ticks = m.who !== "me" ? "" : !m.id ? `<i class="tick wait">${icon("clock")}</i>` : `<i class="tick${answered ? " read" : ""}">${icon(answered ? "checks" : "check")}</i>`;
  const cls = ["msg", m.who === "me" ? "me" : "", same(prev) ? "cont" : "", same(next) ? "" : "tail"].filter(Boolean).join(" ");
  const ava = m.who !== "me" && !same(next) ? `<img class="m-ava" src="icon.svg" alt="">` : "";  // аватар — у последнего в группе, как в мессенджере
  return `<div class="${cls}" data-id="${m.id || ""}">${ava}<span class="swipe-ic">${icon("reply")}</span>${quoteHtml(m.reply_to)}<div class="mtext">${richText(m.text)}</div>${btns.length ? `<div class="btns">${btns.map((b) =>
    String(b[1]).startsWith("url:") ? `<a class="pill" href="${esc(String(b[1]).slice(4))}" target="_blank" rel="noopener">${esc(b[0])}</a>` :
    `<button data-btn="${esc(b[1])}">${esc(b[0])}</button>`).join("")}</div>` : ""}<div class="mfoot">${m.reaction ? `<button type="button" class="react-chip" data-unreact="${m.id}" aria-label="Убрать реакцию ${esc(m.reaction)}">${esc(m.reaction)}</button>` : ""}<time>${m.channel && m.channel !== "telegram" && m.channel !== "web" ? esc(m.channel) + " · " : ""}${hhmm(at)}${ticks}</time></div></div>`;
}

function renderChat(opts = {}) {
  const stick = opts.bottom || chatUI.stick || !$("#chat");
  const keepY = window.scrollY;
  const msgs = state.messages;
  let html = `<div class="chat" id="chat">`;
  let lastDay = "", lastArvix = -1;
  msgs.forEach((m, i) => { if (m.who === "arvix") lastArvix = i; });
  msgs.forEach((m, i) => {
    const day = dayLabel(new Date(m.at));
    if (day !== lastDay) { html += `<div class="day-sep"><span>${day}</span></div>`; lastDay = day; }
    const prev = msgs[i - 1], next = msgs[i + 1];
    html += msgHtml(m, prev && dayLabel(new Date(prev.at)) === day ? prev : null, next && dayLabel(new Date(next.at)) === day ? next : null, i < lastArvix);
  });
  if (state.thinking) html += `<div class="typing" title="${esc(state.thinking)}"><img class="m-ava" src="icon.svg" alt=""><i></i><i></i><i></i></div>`;
  if (!msgs.length && !state.thinking) html += `<div class="empty">Напиши или скажи что угодно — как в Telegram.</div>`;
  html += `</div>`;
  view.innerHTML = html;
  if (!$(".composer")) {
    const c = document.createElement("div");
    c.className = "composer";
    c.innerHTML = `<div class="reply-bar hidden" id="reply-bar"></div>
      <button class="round ghost" id="attach" aria-label="Прислать файл">${icon("clip")}</button>
      <input type="file" id="file" multiple hidden>
      <textarea id="msg" rows="1" placeholder="Сообщение Arvix"></textarea>
      <button class="round send" id="send" aria-label="Голосовое сообщение" data-mode="mic">${icon("mic")}</button>
      <button class="to-bottom hidden" id="to-bottom" aria-label="Вниз, к новым">${icon("chevronDown")}<b id="to-bottom-n"></b></button>`;
    document.body.appendChild(c);
    const ta = $("#msg");
    ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = Math.min(140, ta.scrollHeight) + "px"; composerMode(); });
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !("ontouchstart" in window)) { e.preventDefault(); sendMessage(); }
      else if (e.key === "Escape" && chatUI.reply) { e.preventDefault(); e.stopPropagation(); setReply(null); }
      else if (e.key === "ArrowUp" && (e.ctrlKey || e.metaKey) && !ta.value) {  // Ctrl+↑ — ответить на последнее Arvix
        const last = [...state.messages].reverse().find((m) => m.who === "arvix" && m.id);
        if (last) { e.preventDefault(); setReply(last); }
      }
    });
    $("#send").onclick = () => ($("#send").dataset.mode === "send" ? sendMessage() : toggleRecord());
    $("#attach").onclick = () => $("#file").click();
    $("#file").onchange = (e) => { sendFiles([...e.target.files]); e.target.value = ""; };
    $("#to-bottom").onclick = () => { haptic(); window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" }); };
  }
  drawReplyBar();
  if (state.chatDraft) {  // «Спросить Arvix» из заметки: начало вопроса уже в поле
    const ta = $("#msg"); ta.value = state.chatDraft; state.chatDraft = "";
    ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); composerMode();
  }
  view.querySelectorAll("[data-btn]").forEach((b) => b.addEventListener("click", async () => {
    haptic(); b.disabled = true;
    try { await api("button", { json: { data: b.dataset.btn } }); state.thinking = "думаю"; renderChat({ bottom: true }); } catch (err) { toast(err.message); }
  }));
  bindChat($("#chat"));
  // Новое от Arvix, пока читаешь старое, — счётчик на ↓, а не прыжок вниз
  const newest = msgs.reduce((a, m) => Math.max(a, m.id || 0), 0);
  if (!stick && newest > chatUI.lastId) chatUI.unread += msgs.filter((m) => m.id > chatUI.lastId && m.who === "arvix").length;
  chatUI.lastId = Math.max(chatUI.lastId, newest);
  if (stick) { window.scrollTo(0, document.documentElement.scrollHeight); chatUI.stick = true; chatUI.unread = 0; }
  else window.scrollTo(0, keepY);
  chatHeader(); toBottomButton(); pingSoon();
}

function chatHeader() {
  if (state.tab !== "chat") return;
  $("#top-day").textContent = "Arvix";
  const busy = state.thinking;
  $("#top-sub").textContent = !busy ? "в сети" : /слуша/.test(busy) ? "слушает…" : /файл/.test(busy) ? "смотрит файл…" : "печатает…";
  $("#top-sub").classList.toggle("typing-sub", !!busy);
}

function toBottomButton() {
  const b = $("#to-bottom"); if (!b) return;
  b.classList.toggle("hidden", chatUI.stick);
  $("#to-bottom-n").textContent = chatUI.unread ? String(chatUI.unread) : "";
}

window.addEventListener("scroll", () => {
  if (state.tab !== "chat") return;
  chatUI.stick = nearBottom();
  if (chatUI.stick) { chatUI.unread = 0; pingSoon(); }
  toBottomButton(); closeMsgMenu();
}, { passive: true });

const msgById = (id) => state.messages.find((m) => String(m.id) === String(id));

function setReply(m) {
  chatUI.reply = m && m.id ? { id: m.id, who: m.who, text: String(m.text || "").replace(/\s+/g, " ").slice(0, 160) } : null;
  drawReplyBar();
  if (chatUI.reply) { haptic(); const ta = $("#msg"); if (ta) ta.focus({ preventScroll: true }); }
}

function drawReplyBar() {
  const bar = $("#reply-bar"); if (!bar) return;
  const r = chatUI.reply;
  bar.classList.toggle("hidden", !r);
  if (!r) { bar.innerHTML = ""; return; }
  bar.innerHTML = `<span class="rb-ic">${icon("reply")}</span>
    <button type="button" class="rb-body" data-goto="${r.id}"><b>В ответ ${r.who === "me" ? "себе" : "Arvix"}</b><span>${esc(r.text || "…")}</span></button>
    <button type="button" class="rb-x" aria-label="Не отвечать на сообщение">${icon("x")}</button>`;
  bar.querySelector(".rb-x").onclick = () => setReply(null);
  bar.querySelector(".rb-body").onclick = () => gotoMsg(r.id);
}

function gotoMsg(id) {
  const key = CSS.escape(String(id));
  const el = view.querySelector(`.msg[data-id="${key}"], .msg[data-pid="${key}"]`);
  if (!el) { toast("Это сообщение старше загруженной ленты"); return; }
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
}

const REACTIONS = ["👍", "👎", "❤️", "💔", "❓", "🔥", "😂", "🙏"];  // = Core.REACTIONS

async function setReaction(m, emoji) {
  const before = m.reaction || "";
  m.reaction = emoji; haptic(); renderChat();
  try {
    await api("react", { json: { message: m.id, emoji } });
    if (emoji === "❓") { state.thinking = "думаю"; renderChat({ bottom: true }); }
  } catch (err) { m.reaction = before; renderChat(); toast(err.message); }
}

/* Что Arvix видит, как в мессенджере (D52): «в сети» — пульс раз в 30 с, пока приложение на экране;
 * «прочитано» — лента чата открыта и долистана до конца. Свёрнуто или другая вкладка браузера — ничего не шлём. */
const seenState = { upto: 0, timer: 0 };
function ping(force = false) {
  if (document.visibilityState !== "visible") return;
  const atEnd = state.tab === "chat" && chatUI.stick;
  const upto = atEnd ? state.messages.reduce((a, x) => (x.who === "arvix" ? Math.max(a, x.id || 0) : a), 0) : 0;
  const fresh = upto > seenState.upto;
  if (!force && !fresh) return;
  if (fresh) seenState.upto = upto;
  api("seen", { json: fresh ? { upto } : {} }).catch(() => {});
}
const pingSoon = () => { clearTimeout(seenState.timer); seenState.timer = setTimeout(() => ping(), 700); };
setInterval(() => ping(true), 30000);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") ping(true); });

let msgMenu = null;
function closeMsgMenu() { if (msgMenu) { msgMenu.remove(); msgMenu = null; } }
function openMsgMenu(el, x, y) {
  const m = msgById(el.dataset.id); if (!m) return;
  closeMsgMenu(); haptic("medium");
  msgMenu = document.createElement("div");
  msgMenu.className = "msg-menu";
  // Реакции — только на сообщения Arvix: он их видит и учитывает (D52); ❓ — объяснит проще
  const row = m.who === "arvix" ? `<div class="react-row">${REACTIONS.map((e) => `<button data-react="${e}" class="${m.reaction === e ? "on" : ""}" aria-label="Реакция ${e}">${e}</button>`).join("")}</div>` : "";
  msgMenu.innerHTML = `${row}<button data-act="reply">${icon("reply")} Ответить</button><button data-act="copy">${icon("copy")} Копировать</button>`;
  document.body.appendChild(msgMenu);
  const w = msgMenu.offsetWidth, h = msgMenu.offsetHeight;
  msgMenu.style.left = Math.max(8, Math.min(x, window.innerWidth - w - 8)) + "px";
  msgMenu.style.top = Math.max(8, Math.min(y, window.innerHeight - h - 8)) + "px";
  msgMenu.onclick = async (e) => {
    const r = e.target.closest("[data-react]");
    if (r) { closeMsgMenu(); setReaction(m, m.reaction === r.dataset.react ? "" : r.dataset.react); return; }
    const act = e.target.closest("[data-act]"); if (!act) return;
    closeMsgMenu();
    if (act.dataset.act === "reply") setReply(m);
    else { try { await navigator.clipboard.writeText(plainText(m.text)); toast("Скопировано"); } catch (_) { toast("Не скопировалось"); } }
  };
}
document.addEventListener("pointerdown", (e) => { if (msgMenu && !msgMenu.contains(e.target)) closeMsgMenu(); }, true);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && msgMenu) { e.stopPropagation(); closeMsgMenu(); } }, true);

/* Жесты на пузырях: свайп влево — ответить (как в Telegram на телефоне), долгое нажатие — меню,
 * правый клик — меню, двойной клик — ответить (как в Telegram на компьютере), цитата — к оригиналу. */
function bindChat(root, onReply = setReply, find = msgById) {
  if (!root) return;
  root.querySelectorAll("[data-goto]").forEach((q) => q.onclick = (e) => { e.stopPropagation(); gotoMsg(q.dataset.goto); });
  root.querySelectorAll("[data-unreact]").forEach((b) => b.onclick = (e) => {
    e.stopPropagation(); const m = find(b.dataset.unreact); if (m) setReaction(m, "");
  });
  root.querySelectorAll(".msg[data-id]").forEach((el) => {
    if (!el.dataset.id) return;
    let x0 = 0, y0 = 0, dx = 0, swiping = false, press = 0, opened = false;
    el.addEventListener("touchstart", (e) => {
      const t = e.touches[0]; x0 = t.clientX; y0 = t.clientY; dx = 0; swiping = false; opened = false;
      clearTimeout(press);
      press = setTimeout(() => { press = 0; if (!swiping) { opened = true; el.dataset.pressed = "1"; openMsgMenu(el, x0, y0 + 12); } }, 450);
    }, { passive: true });
    el.addEventListener("touchmove", (e) => {
      const t = e.touches[0], mx = t.clientX - x0, my = t.clientY - y0;
      if (Math.abs(mx) > 8 || Math.abs(my) > 8) { clearTimeout(press); press = 0; }
      if (!swiping && mx < -12 && Math.abs(mx) > Math.abs(my) * 1.5) swiping = true;
      if (!swiping) return;
      dx = Math.max(-80, Math.min(0, mx));
      el.style.transform = `translateX(${dx}px)`;
      el.classList.toggle("swipe-ready", dx <= -56);
    }, { passive: true });
    const end = (e) => {
      clearTimeout(press); press = 0;
      if (opened && e.cancelable) e.preventDefault();  // отпускание пальца не должно нажать пункт меню под ним
      opened = false;
      if (swiping) {
        el.style.transform = ""; el.classList.remove("swipe-ready");
        if (dx <= -56) { const m = find(el.dataset.id); if (m) onReply(m); }
      }
      swiping = false; dx = 0;
    };
    el.addEventListener("touchend", end);
    el.addEventListener("touchcancel", end);
    el.addEventListener("contextmenu", (e) => {
      if (e.target.closest("a")) return;  // у ссылки — меню браузера
      e.preventDefault();
      if (el.dataset.pressed) { delete el.dataset.pressed; return; }  // телефон: меню уже открыто долгим нажатием
      openMsgMenu(el, e.clientX, e.clientY);
    });
    el.addEventListener("dblclick", (e) => {
      if (e.target.closest("a, button") || matchMedia("(hover: none)").matches) return;  // на телефоне — свайп
      const m = find(el.dataset.id); if (!m) return;
      window.getSelection && window.getSelection().removeAllRanges();
      onReply(m);
    });
  });
}

/* rich:start — разметка сообщений Arvix (чат, шаги задач). Та же, что понимает Telegram (telegram/fmt.py):
 * **жирный**, *курсив*, `код`, ~~зачёркнутый~~, ссылки; строки «— », «- », «1. » — список, «> » — цитата, ``` — блок кода.
 * Сначала экранирование, потом разметка: из текста модели в страницу не попадёт ни один тег. */
function richInline(s) {
  const keep = [];
  const hold = (html) => { keep.push(html); return `\u0001${keep.length - 1}\u0001`; };
  s = esc(s)
    .replace(/`([^`\n]+)`/g, (_, c) => hold(`<code>${c}</code>`))
    .replace(/\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g, (_, t, u) => hold(`<a href="${u}" target="_blank" rel="noopener">${t}</a>`))
    .replace(/https?:\/\/[^\s<]*[^\s<.,;:!?)»]/g, (u) => hold(`<a href="${u}" target="_blank" rel="noopener">${u}</a>`))
    .replace(/\*\*(?=\S)([^\n]*?\S)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*\p{L}\d])\*(?=\S)([^*\n]*?\S)\*(?![*\p{L}\d])/gu, "$1<i>$2</i>")
    .replace(/~~(?=\S)([^~\n]*?\S)~~/g, "<s>$1</s>")
    .replace(/==(?=\S)([^=\n]*?\S)==/g, "<mark>$1</mark>");
  return s.replace(/\u0001(\d+)\u0001/g, (_, i) => keep[+i]);
}

function richText(text) {
  const out = [];
  let para = [], list = null, quote = [], fence = null;
  const flushPara = () => { if (para.length) { out.push(`<p>${para.map(richInline).join("<br>")}</p>`); para = []; } };
  const flushList = () => {
    if (!list) return;
    out.push(`<${list.tag} class="m-list"${list.tag === "ol" && list.start !== 1 ? ` start="${list.start}"` : ""}>${list.items.map((li) => `<li>${richInline(li)}</li>`).join("")}</${list.tag}>`);
    list = null;
  };
  const flushQuote = () => { if (quote.length) { out.push(`<blockquote>${quote.map(richInline).join("<br>")}</blockquote>`); quote = []; } };
  const flushAll = () => { flushPara(); flushList(); flushQuote(); };
  for (const line of String(text ?? "").replace(/\r\n?/g, "\n").split("\n")) {
    if (fence) {
      if (/^\s*```/.test(line)) { out.push(`<pre class="m-code"><code>${esc(fence.join("\n"))}</code></pre>`); fence = null; } else fence.push(line);
      continue;
    }
    let m;
    if (/^\s*```/.test(line)) { flushAll(); fence = []; continue; }
    if (!line.trim()) { flushAll(); continue; }
    if ((m = line.match(/^\s*#{1,6}\s+(.*)$/))) { flushAll(); out.push(`<p class="m-h">${richInline(m[1])}</p>`); continue; }
    if ((m = line.match(/^\s*>\s?(.*)$/))) { flushPara(); flushList(); quote.push(m[1]); continue; }
    flushQuote();
    if ((m = line.match(/^\s*[-*•–—]\s+(.*)$/))) {
      flushPara();
      if (!list || list.tag !== "ul") { flushList(); list = { tag: "ul", items: [] }; }
      list.items.push(m[1]); continue;
    }
    if ((m = line.match(/^\s*(\d{1,3})[.)]\s+(.*)$/))) {
      flushPara();
      if (!list || list.tag !== "ol") { flushList(); list = { tag: "ol", start: +m[1], items: [] }; }
      list.items.push(m[2]); continue;
    }
    flushList();
    para.push(line);
  }
  if (fence) out.push(`<pre class="m-code"><code>${esc(fence.join("\n"))}</code></pre>`);
  flushAll();
  return out.join("");
}

/* Без разметки — для цитаты, копирования и превью: звёздочки и обратные кавычки человеку не нужны. */
function plainText(text) {
  return String(text ?? "").replace(/\*\*(?=\S)([^\n]*?\S)\*\*/g, "$1").replace(/(^|[^*\p{L}\d])\*(?=\S)([^*\n]*?\S)\*(?![*\p{L}\d])/gu, "$1$2")
    .replace(/`([^`\n]+)`/g, "$1").replace(/~~([^~\n]+)~~/g, "$1").replace(/==([^=\n]+)==/g, "$1");
}
/* rich:end */

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
  const reply = chatUI.reply;
  ta.value = ""; ta.style.height = "auto"; composerMode(); haptic(); setReply(null);
  state.messages.push({ id: 0, at: new Date().toISOString(), who: "me", text, channel: "web", buttons: [], reply_to: reply });
  state.thinking = "думаю"; renderChat({ bottom: true });
  try { await api("message", { json: { text, ...(reply ? { reply_to: reply.id } : {}) } }); } catch (err) { toast(err.message); }
}

/* Ответ на сообщение уходит и с голосовым, и с файлом: заголовок X-Reply-To (D52). */
function takeReply() {
  const r = chatUI.reply; setReply(null);
  return r;
}

/* Файлы Arvix: фото, PDF, документы, архив репозитория, аудио, видео — до 20 МБ.
 * Подпись — текст из поля ввода (к первому файлу). Ответ придёт в ленту потоком. */
const MAX_FILE = 20 * 1024 * 1024;
async function sendFiles(files) {
  const ta = $("#msg");
  let caption = ta.value.trim(), reply = takeReply();
  for (const file of files) {
    if (file.size > MAX_FILE) { toast(`«${file.name}» больше 20 МБ — сожми или раздели`); continue; }
    state.messages.push({ id: 0, at: new Date().toISOString(), who: "me", text: "📎 " + file.name + (caption ? " — " + caption : ""), channel: "web", buttons: [], reply_to: reply });
    state.thinking = "смотрю файл"; renderChat({ bottom: true });
    try {
      const res = await fetch("/api/upload", { method: "POST", body: file, headers: { ...authHeaders(), "Content-Type": file.type || "application/octet-stream",
        "X-File-Name": encodeURIComponent(file.name), "X-Caption": encodeURIComponent(caption), ...(reply ? { "X-Reply-To": String(reply.id) } : {}) } });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "Ошибка " + res.status);
      haptic();
    } catch (err) { toast(err.message); }
    caption = ""; reply = null;
  }
  ta.value = ""; ta.style.height = "auto"; composerMode();
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
      const reply = takeReply();
      state.messages.push({ id: 0, at: new Date().toISOString(), who: "me", text: "🎙 голосовое…", channel: "web", buttons: [], reply_to: reply });
      state.thinking = "слушаю"; renderChat({ bottom: true });
      try { await api("voice", { body: blob, headers: { "Content-Type": blob.type.split(";")[0], ...(reply ? { "X-Reply-To": String(reply.id) } : {}) } }); } catch (err) { toast(err.message); }
    };
    recorder.start(); haptic("medium");
    composerMode();
  } catch (err) { toast("Нет доступа к микрофону: " + err.message); }
}

// --- Заметки -----------------------------------------------------------------------------------
function renderNotes() {
  if (state.notesView === undefined) { try { state.notesView = localStorage.getItem("arvix_notes_view") || "list"; } catch (_) { state.notesView = "list"; } }
  const wide = isWide();
  if (state.note && !wide) { renderNote(); return; }
  if (state.notesView === "graph" && !state.notesResults && !state.note) { renderGraph(); return; }
  if (!wide) { view.innerHTML = notesSwitch() + notesListHtml(true); bindNotesList(view); bindNotesSwitch(); return; }
  renderNotesShell();
  if (state.note) renderNote(); else renderNoteEmpty();
}

/* Правая половина без открытой заметки: быстрая запись в Inbox и подсказка по клавишам. */
function renderNoteEmpty() {
  const pane = $("#note-pane"); if (!pane) return;
  pane.innerHTML = `${captureHtml()}<div class="empty">Выбери заметку слева или создай новую.<br>
    <span class="small"><kbd>/</kbd> — поиск · <kbd>Ctrl</kbd>+<kbd>S</kbd> — сохранить · <kbd>Esc</kbd> — закрыть</span></div>`;
  bindCapture(pane);
}

/* Список слева обновляется сам по себе: открытая справа заметка (и черновик в редакторе) не пересобирается. */
function refreshNotesList() {
  const side = $("#notes-side");
  if (!side) { renderNotes(); return; }
  const top = side.scrollTop;
  side.innerHTML = notesSwitch() + notesListHtml(false); bindNotesList(side); bindNotesSwitch(); side.scrollTop = top;
}

function captureHtml() {
  return `<div class="card"><h3>Мысль в Inbox</h3><div class="field" style="margin:0"><textarea id="n-cap" rows="2" placeholder="Записать и не держать в голове"></textarea></div>
    <button class="pill primary" id="n-save" style="margin-top:8px">Записать</button></div>`;
}
function bindCapture(root) {
  const save = root.querySelector("#n-save"); if (!save) return;
  save.onclick = async () => {
    const box = root.querySelector("#n-cap"), text = box.value.trim(); if (!text) return;
    try { const r = await api("capture", { json: { text } }); notify("success"); toast("Записано" + (r.path ? ": " + r.path : "")); box.value = ""; } catch (err) { toast(err.message); }
  };
}

function notesListHtml(withCapture) {
  const list = state.notesList, open = state.note && state.note.path;
  let html = `<div class="search"><input id="n-q" type="search" placeholder="Поиск по заметкам${isWide() ? "  ( / )" : ""}" value="${esc(state.notesQuery || "")}"></div>`;
  if (withCapture) html += captureHtml();
  const on = (path) => (path === open ? " on" : "");
  if (state.notesResults) {
    html += `<div class="section-title"><span>Найдено</span><button class="small" id="n-clear" style="color:var(--accent)">сбросить</button></div>`;
    html += state.notesResults.length ? state.notesResults.map((r) => `<button class="list-item${on(r.path)}" data-path="${esc(r.path)}"><span class="li-ic">${icon("file")}</span>
      <span class="grow"><b>${esc(r.path.split("/").pop().replace(/\.md$/, ""))}</b><br><span class="muted small">${esc(r.snippet)}</span></span></button>`).join("") :
      `<div class="empty">Ничего не нашлось.</div>`;
  } else if (list) {
    const parts = state.notesDir ? state.notesDir.split("/") : [];
    html += `<div class="crumbs-row"><div class="crumbs"><button data-dir="">Хранилище</button>${parts.map((p, i) => ` / <button data-dir="${esc(parts.slice(0, i + 1).join("/"))}">${esc(p)}</button>`).join("")}</div>
      <span class="crumbs-actions"><button class="pill" id="n-ink-new" title="Конспект стилусом на планшете">✍ От руки</button><button class="pill" id="n-new">+ Заметка</button></span></div>`;
    html += list.dirs.map((d) => `<button class="list-item" data-dir="${esc(d.path)}"><span class="li-ic folder">${icon("folder")}</span><span class="grow">${esc(d.name)}</span><span class="muted">${icon("chevron")}</span></button>`).join("");
    html += list.files.map((f) => `<button class="list-item${on(f.path)}" data-path="${esc(f.path)}"><span class="li-ic">${icon("file")}</span><span class="grow">${esc(f.name)}</span>
      <span class="muted small">${new Date(f.modified * 1000).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}</span></button>`).join("");
    if (!list.dirs.length && !list.files.length) html += `<div class="empty">Пусто.</div>`;
  } else html += `<div class="empty">Загружаю…</div>`;
  return html;
}

function bindNotesList(root) {
  const q = root.querySelector("#n-q");
  q.addEventListener("keydown", async (e) => {
    if (e.key !== "Enter") return;
    state.notesQuery = q.value.trim();
    if (!state.notesQuery) { state.notesResults = null; refreshNotesList(); return; }
    try { state.notesResults = (await api("notes/search?q=" + encodeURIComponent(state.notesQuery))).results; refreshNotesList(); } catch (err) { toast(err.message); }
  });
  const clear = root.querySelector("#n-clear");
  clear && (clear.onclick = () => { state.notesResults = null; state.notesQuery = ""; refreshNotesList(); });
  const add = root.querySelector("#n-new");
  add && (add.onclick = newNote);
  const inkNew = root.querySelector("#n-ink-new");
  inkNew && (inkNew.onclick = newInkNote);
  bindCapture(root);
  root.querySelectorAll("[data-dir]").forEach((b) => b.addEventListener("click", async () => {
    state.notesDir = b.dataset.dir; state.notesList = null; refreshNotesList();
    try { state.notesList = await api("notes?dir=" + encodeURIComponent(state.notesDir)); refreshNotesList(); } catch (err) { toast(err.message); }
  }));
  root.querySelectorAll("[data-path]").forEach((b) => b.addEventListener("click", async () => {
    if (state.noteEdit && !confirmLeaveEditor()) return;
    openNote(b.dataset.path);
  }));
}

// --- Граф заметок: как в Obsidian + подсказки связей от Arvix (D32) ---------------------------
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
    ${sugg.length ? `<div class="card"><h3>Arvix предлагает связать</h3>
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
    if (state.noteEdit && !confirmLeaveEditor()) return;
    state.notesView = b.dataset.view; haptic("soft");
    try { localStorage.setItem("arvix_notes_view", state.notesView); } catch (_) { /* приватный режим */ }
    if (state.notesView === "graph") { state.note = null; state.noteEdit = false; state.notesResults = null; }
    renderNotes();
  }));
}

async function openNote(path, opts = {}) {
  try {
    state.note = await api("note?path=" + encodeURIComponent(path));
    state.noteEdit = !!opts.edit;
    renderNote(); if (!opts.keepScroll) window.scrollTo(0, 0);
    const side = $("#notes-side");
    side && side.querySelectorAll(".list-item[data-path]").forEach((x) => x.classList.toggle("on", x.dataset.path === path));
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
  if (!isWide()) state.notesList = null;
  renderNotes();
  api("notes?dir=" + encodeURIComponent(state.notesDir)).then((r) => { state.notesList = r; if (state.tab === "notes" && !state.note) refreshNotesList(); }).catch(() => {});
}

const noteName = (path) => String(path || "").split("/").pop().replace(/\.md$/, "");
const DRAFT_KEY = (path) => "arvix_draft:" + path;
const draftGet = (path) => { try { return JSON.parse(localStorage.getItem(DRAFT_KEY(path)) || "null"); } catch (_) { return null; } };
const draftSet = (path, d) => { try { d ? localStorage.setItem(DRAFT_KEY(path), JSON.stringify(d)) : localStorage.removeItem(DRAFT_KEY(path)); } catch (_) { /* приватный режим */ } };

/* Куда рисовать заметку: на ноутбуке — в правую панель рядом со списком, на телефоне — на весь экран. */
function noteRoot() {
  if (!isWide()) return view;
  if (!$("#note-pane")) renderNotesShell();
  return $("#note-pane");
}
function renderNotesShell() {
  view.innerHTML = `<div class="notes-split"><aside class="notes-side" id="notes-side">${notesSwitch()}${notesListHtml(false)}</aside>
    <section class="notes-main" id="note-pane"></section></div>`;
  bindNotesList($("#notes-side")); bindNotesSwitch();
  if (!state.notesList) api("notes?dir=" + encodeURIComponent(state.notesDir)).then((r) => { state.notesList = r; if ($("#notes-side")) refreshNotesList(); }).catch(() => {});
}

function renderNote() {
  if (state.noteEdit) { renderEditor(); return; }
  const n = state.note;
  const root = noteRoot();
  const doc = obsidian(n.text, n.tasks || {});
  const props = n.ink ? doc.props.filter((p) => p.key !== "ink") : doc.props;  // служебная ссылка на папку страниц
  const folder = n.path.includes("/") ? n.path.slice(0, n.path.lastIndexOf("/")) : "Хранилище";
  root.innerHTML = `<div class="note-bar"><button id="n-back" class="note-back" title="Esc">${isWide() ? icon("x") + " Закрыть" : icon("back") + " " + esc(folder.split("/").pop())}</button>
      ${isWide() ? `<span class="note-bar-title muted small">${esc(folder)}</span>` : ""}
      ${n.ink ? `<button id="n-ink" class="pill primary small-pill" title="Писать стилусом">✍ Писать</button>` : ""}
      <button id="n-ask" class="pill small-pill" title="Спросить Arvix про эту заметку: что с ней делать и чем">${icon("chat")} Спросить Arvix</button>
      <button id="n-edit" class="icon-btn" aria-label="Править" title="Править (E)">${icon("pencil")}</button></div>
    <article class="obs${n.ink ? " ink-view" : ""}">
      <h1 class="obs-title">${esc(noteName(n.path))}</h1>
      ${n.ink ? inkStatusHtml(n.ink) : ""}
      ${props.length ? propsHtml(props) : ""}
      ${doc.html || `<p class="muted">Пустая заметка. ✎ — написать.</p>`}
    </article>`;
  $("#n-back").onclick = closeNote;
  $("#n-edit").onclick = () => { state.noteEdit = true; renderNote(); };
  $("#n-ask").onclick = () => askAboutNote(n.path);
  if (n.ink) {
    $("#n-ink").onclick = () => openInk(n.path);
    const retry = $("#ink-retry"); if (retry) retry.onclick = () => inkRetry(n.path);
  }
  bindNote(root);
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

function bindNote(root = view) {
  const n = state.note;
  root.querySelectorAll(".obs input[data-line]").forEach((box) => box.addEventListener("click", async (e) => {
    e.preventDefault(); haptic();
    try {
      const r = await api("note/toggle", { json: { path: n.path, line: +box.dataset.line, sha: n.sha } });
      if (r.task) { await closeTaskFromNote(r.task); return; }
      state.note = r; renderNote(); notify("success");
    } catch (err) { await noteError(err); }
  }));
  root.querySelectorAll("[data-wiki]").forEach((a) => a.addEventListener("click", async (e) => {
    e.preventDefault();
    try {
      const r = await api("notes/search?q=" + encodeURIComponent(a.dataset.wiki));
      const name = a.dataset.wiki.toLowerCase();
      const hit = r.results.find((x) => x.path.toLowerCase().endsWith("/" + name + ".md") || x.path.toLowerCase() === name + ".md") || r.results[0];
      if (hit) openNote(hit.path); else toast("Заметки «" + a.dataset.wiki + "» ещё нет");
    } catch (err) { toast(err.message); }
  }));
  root.querySelectorAll("[data-tag]").forEach((t) => t.addEventListener("click", async () => {
    state.note = null; state.notesQuery = "#" + t.dataset.tag;
    try { state.notesResults = (await api("notes/search?q=" + encodeURIComponent(t.dataset.tag))).results; } catch (_) { state.notesResults = []; }
    if (TG) { TG.BackButton.offClick(noteBack); TG.BackButton.hide(); }
    renderNotes();
  }));
  root.querySelectorAll(".obs-prop").forEach((row) => row.addEventListener("click", () => editProp(row)));
  root.querySelectorAll(".callout.foldable > .callout-title").forEach((t) => t.addEventListener("click", () => t.parentElement.classList.toggle("folded")));
  hydrateAssets(root, n.ink ? n.ink.version : "");
}

/* «Спросить Arvix» (D62): чат с готовым началом — путь заметки голова откроет сама (Read) и ответит,
 * что с ней делать и каким инструментом: карточки в Anki, задачи в Решу ОГЭ, шаги к блоку. Вопрос дописывает человек. */
function askAboutNote(path) {
  state.chatDraft = `По заметке «${noteName(path)}» (${path}): `;
  state.note = null; state.noteEdit = false;
  if (TG) { TG.BackButton.offClick(noteBack); TG.BackButton.hide(); }
  setTab("chat");
}

/* Галочка у строки-задачи Arvix закрывает задачу тем же путём, что ✓ на «Сегодня». */
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
  const root = noteRoot();
  root.innerHTML = `<div class="note-bar editing"><button id="e-cancel" class="note-back">Отмена</button>
      <span class="note-bar-title">${esc(noteName(n.path))}</span><button id="e-save" class="pill primary" title="Ctrl+S">Сохранить</button></div>
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
  root.querySelectorAll("[data-tool]").forEach((b) => b.addEventListener("pointerdown", (e) => {
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
      <p class="muted small">Пока ты правил, её изменили на другом устройстве (Obsidian на ноутбуке или Arvix). Выбери версию — вторая не пропадёт молча.</p>
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

function confirmLeaveEditor() {
  const ta = $("#e-text"), n = state.note;
  return !(ta && n && ta.value !== n.text) || confirm("Выйти без сохранения? Черновик останется на этом устройстве.");
}
function leaveEditor() {
  if (!confirmLeaveEditor()) return;
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

// --- Конспект от руки (D66): стилус на планшете, почерк остаётся почерком -----------------------
/* Страница — 1000×1414 единиц (A4); точки штрихов — целые десятые доли единицы, нажим — 0…1000.
 * Холст рисует браузер; на сохранение уходят штрихи (чтобы дописать позже) и PNG изменённых страниц
 * (их видят Obsidian и голова). «Только стилус»: перо пишет, палец листает — ладонь не оставляет следов. */
const INK_W = 1000, INK_H = 1414, INK_EXPORT = 1.4;
const INK_COLORS = [["#1b1f3b", "Чёрная"], ["#2346d6", "Синяя"], ["#d6334a", "Красная"], ["#1f9d55", "Зелёная"]];
const INK_WIDTHS = [[1.3, "Тонкая"], [2.3, "Средняя"], [4, "Толстая"]];
const INK_HL = { c: "#ffd43b", w: 20 };
const INK_BG = { grid: "Клетка", lines: "Линейка", blank: "Чистый" };
const INK_ERASER = 14;
const inkKey = (path) => "arvix_ink:" + path;
const inkPref = (key, fallback) => { try { const v = localStorage.getItem("arvix_ink_" + key); return v === null ? fallback : JSON.parse(v); } catch (_) { return fallback; } };
const inkSetPref = (key, v) => { try { localStorage.setItem("arvix_ink_" + key, JSON.stringify(v)); } catch (_) { /* приватный режим */ } };
const ink = { note: null, page: 0, tool: "pen", color: inkPref("color", INK_COLORS[0][0]), width: inkPref("width", 1),
  penOnly: inkPref("pen_only", null), dirty: new Set(), undo: [], redo: [], cur: null, pointers: new Map(), pan: null,
  raf: 0, lastPen: 0, saving: false, idle: 0, draft: 0, scale: 1, dpr: 1, el: null };
const inkOpen = () => !!ink.el;

function inkBg(ctx, bg) {
  ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, INK_W, INK_H);
  ctx.lineWidth = 0.9;
  if (bg === "grid") {
    ctx.strokeStyle = "#d9e2ee"; ctx.beginPath();
    for (let x = 23.8; x < INK_W; x += 23.8) { ctx.moveTo(x, 0); ctx.lineTo(x, INK_H); }
    for (let y = 23.8; y < INK_H; y += 23.8) { ctx.moveTo(0, y); ctx.lineTo(INK_W, y); }
    ctx.stroke();
  } else if (bg === "lines") {
    ctx.strokeStyle = "#cfdcec"; ctx.beginPath();
    for (let y = 110; y < INK_H - 20; y += 38) { ctx.moveTo(0, y); ctx.lineTo(INK_W, y); }
    ctx.stroke();
    ctx.strokeStyle = "#f2b8c0"; ctx.beginPath(); ctx.moveTo(90, 0); ctx.lineTo(90, INK_H); ctx.stroke();
  }
}

/* Перо — отрезки по средним точкам (гладко), толщина — от нажима. Маркер — один путь с умножением:
 * перекрытия не темнеют, текст под ним остаётся чёрным. */
function inkStroke(ctx, s) {
  const p = s.p, n = p.length / 3;
  if (!n) return;
  const X = (i) => p[i * 3] / 10, Y = (i) => p[i * 3 + 1] / 10, P = (i) => p[i * 3 + 2] / 1000;
  ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.strokeStyle = s.c; ctx.fillStyle = s.c;
  if (s.t === "hl") {
    ctx.save(); ctx.globalCompositeOperation = "multiply"; ctx.globalAlpha = 0.55; ctx.lineWidth = s.w;
    ctx.beginPath(); ctx.moveTo(X(0), Y(0));
    for (let i = 1; i < n; i++) ctx.lineTo(X(i), Y(i));
    if (n === 1) ctx.lineTo(X(0) + 0.1, Y(0));
    ctx.stroke(); ctx.restore();
    return;
  }
  const width = (i) => s.w * (0.45 + 0.85 * P(i));
  if (n === 1) { ctx.beginPath(); ctx.arc(X(0), Y(0), width(0) / 2, 0, Math.PI * 2); ctx.fill(); return; }
  let mx = X(0), my = Y(0);
  for (let i = 1; i < n; i++) {
    const nx = i < n - 1 ? (X(i) + X(i + 1)) / 2 : X(i), ny = i < n - 1 ? (Y(i) + Y(i + 1)) / 2 : Y(i);
    ctx.beginPath(); ctx.lineWidth = (width(i - 1) + width(i)) / 2;
    ctx.moveTo(mx, my); ctx.quadraticCurveTo(X(i), Y(i), nx, ny); ctx.stroke();
    mx = nx; my = ny;
  }
}

function inkPaint(ctx, page) {
  inkBg(ctx, page.bg);
  for (const s of page.strokes) inkStroke(ctx, s);
}

function inkPage() { return ink.note.pages[ink.page]; }

function inkHtml() {
  const n = ink.note;
  const tool = (t, label, ic) => `<button type="button" class="ink-btn${ink.tool === t ? " on" : ""}" data-tool="${t}" title="${label}" aria-label="${label}">${ic}</button>`;
  return `<div class="ink-bar">
    <button type="button" class="ink-btn" id="ink-close" title="Сохранить и закрыть (Esc)" aria-label="Закрыть">${icon("x")}</button>
    <span class="ink-title">${esc(n.title)}</span>
    <div class="ink-tools">
      ${tool("pen", "Ручка (P)", icon("pen"))}
      <span class="ink-colors">${INK_COLORS.map(([c, name]) => `<button type="button" class="ink-color${ink.color === c ? " on" : ""}" data-color="${c}" style="--c:${c}" title="${name}" aria-label="${name}"></button>`).join("")}</span>
      <span class="ink-widths">${INK_WIDTHS.map(([w, name], i) => `<button type="button" class="ink-width${ink.width === i ? " on" : ""}" data-width="${i}" title="${name}" aria-label="${name}"><i style="--d:${3 + i * 3}px"></i></button>`).join("")}</span>
      ${tool("hl", "Маркер (H)", icon("marker"))}
      ${tool("eraser", "Ластик (E) — стирает штрих целиком", icon("eraser"))}
      <span class="ink-sep"></span>
      <button type="button" class="ink-btn" id="ink-undo" title="Отменить (Ctrl+Z)" aria-label="Отменить">${icon("undo")}</button>
      <button type="button" class="ink-btn" id="ink-redo" title="Вернуть (Ctrl+Shift+Z)" aria-label="Вернуть">${icon("redo")}</button>
      <button type="button" class="ink-btn ink-text" id="ink-bg" title="Фон страницы">${INK_BG[inkPage().bg]}</button>
      <button type="button" class="ink-btn ink-text${ink.penOnly ? " on" : ""}" id="ink-pen" title="Только стилус: пальцем — листать, ладонь не рисует">✍ Стилус</button>
    </div>
    <div class="ink-nav">
      <button type="button" class="ink-btn" id="ink-prev" aria-label="Предыдущая страница"${ink.page ? "" : " disabled"}>‹</button>
      <span class="ink-count">${ink.page + 1}/${n.pages.length}</span>
      <button type="button" class="ink-btn" id="ink-next" aria-label="Следующая страница"${ink.page < n.pages.length - 1 ? "" : " disabled"}>›</button>
      <button type="button" class="ink-btn ink-text" id="ink-add" title="Новая страница">+ стр.</button>
    </div>
    <button type="button" class="pill primary" id="ink-done" title="Сохранить — Arvix расшифрует">Готово</button>
  </div>
  <div class="ink-scroll" id="ink-scroll"><div class="ink-paper" id="ink-paper"><canvas id="ink-base"></canvas><canvas id="ink-live"></canvas></div>
    <p class="ink-foot muted small">Стр. ${ink.page + 1} · ${ink.penOnly ? "пишет только стилус, пальцем — листать" : "пишет палец и стилус · двумя пальцами — листать"} · <span id="ink-saved">${ink.dirty.size ? "не сохранено" : "сохранено"}</span></p></div>`;
}

async function openInk(path) {
  try {
    const n = await api("ink?path=" + encodeURIComponent(path));
    ink.note = n; ink.page = 0; ink.dirty = new Set(); ink.undo = []; ink.redo = []; ink.cur = null; ink.saved = n.pages.length;
    const draft = (() => { try { return JSON.parse(localStorage.getItem(inkKey(n.path)) || "null"); } catch (_) { return null; } })();
    if (draft && draft.rev === n.rev && Array.isArray(draft.pages) && draft.pages.length >= n.pages.length) {
      n.pages = draft.pages; ink.dirty = new Set(draft.dirty || []); toast("Восстановил несохранённое с этого устройства");
    }
    ink.page = n.pages.length - 1;  // продолжить с последней страницы
    if (!ink.el) {
      ink.el = Object.assign(document.createElement("section"), { id: "ink", className: "ink" });
      ink.el.setAttribute("role", "dialog"); ink.el.setAttribute("aria-label", "Конспект от руки");
      document.body.appendChild(ink.el);
      document.documentElement.classList.add("ink-on");
      window.addEventListener("resize", inkLayout);
      document.addEventListener("visibilitychange", inkHidden);
    }
    try { TG && TG.disableVerticalSwipes && TG.disableVerticalSwipes(); } catch (_) { /* старый клиент */ }
    if (TG) { TG.BackButton.show(); TG.BackButton.offClick(noteBack); TG.BackButton.onClick(closeInk); }
    inkRender();
  } catch (err) { toast(err.message); }
}

function inkRender() {
  const top = $("#ink-scroll") ? $("#ink-scroll").scrollTop : 0;
  ink.el.innerHTML = inkHtml();
  inkBind(); inkLayout();
  $("#ink-scroll").scrollTop = top;
}

function inkLayout() {
  if (!ink.el) return;
  const scroll = $("#ink-scroll"), paper = $("#ink-paper"), base = $("#ink-base"), live = $("#ink-live");
  const cssW = Math.max(280, Math.min(scroll.clientWidth - 16, 980));
  ink.dpr = Math.min(window.devicePixelRatio || 1, 2); ink.scale = cssW / INK_W;
  paper.style.width = cssW + "px"; paper.style.height = cssW * INK_H / INK_W + "px";
  for (const c of [base, live]) {
    c.width = Math.round(cssW * ink.dpr); c.height = Math.round(cssW * INK_H / INK_W * ink.dpr);
    c.getContext("2d").setTransform(ink.dpr * ink.scale, 0, 0, ink.dpr * ink.scale, 0, 0);
  }
  inkRedraw();
}

function inkRedraw() {
  const base = $("#ink-base"); if (!base) return;
  inkPaint(base.getContext("2d"), inkPage());
}

function inkLive() {
  ink.raf = 0;
  const live = $("#ink-live"); if (!live) return;
  const ctx = live.getContext("2d");
  ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, live.width, live.height); ctx.restore();
  if (ink.cur && ink.cur.s) inkStroke(ctx, ink.cur.s);
  if (ink.cur && ink.cur.eraser && ink.cur.at) {
    ctx.beginPath(); ctx.strokeStyle = "#8a94a6"; ctx.lineWidth = 1.2;
    ctx.arc(ink.cur.at[0], ink.cur.at[1], INK_ERASER, 0, Math.PI * 2); ctx.stroke();
  }
}
const inkFrame = () => { if (!ink.raf) ink.raf = requestAnimationFrame(inkLive); };

function inkPoint(e, rect) {
  const x = (e.clientX - rect.left) / rect.width * INK_W, y = (e.clientY - rect.top) / rect.width * INK_W;
  const pressure = e.pointerType === "pen" ? (e.pressure || 0.5) : 0.5;
  return [Math.round(Math.max(0, Math.min(INK_W, x)) * 10), Math.round(Math.max(0, Math.min(INK_H, y)) * 10), Math.round(pressure * 1000)];
}

function inkSnapshot() {
  ink.undo.push({ page: ink.page, strokes: inkPage().strokes.slice() });
  if (ink.undo.length > 120) ink.undo.shift();
  ink.redo = [];
}

function inkChanged() {
  ink.dirty.add(ink.page);
  const mark = $("#ink-saved"); if (mark) mark.textContent = "не сохранено";
  clearTimeout(ink.draft);
  ink.draft = setTimeout(() => {
    try { localStorage.setItem(inkKey(ink.note.path), JSON.stringify({ rev: ink.note.rev, pages: ink.note.pages, dirty: [...ink.dirty] })); } catch (_) { /* места нет — сохранит сервер */ }
  }, 800);
  clearTimeout(ink.idle);
  ink.idle = setTimeout(() => inkSave(false, true), 20000);  // пауза 20 с — тихо сохранить на сервер
}

/* Стёрка — штрих целиком: попал в его рамку и прошёл ближе радиуса к любому отрезку. */
function inkErase(at) {
  const [x, y] = at, r = INK_ERASER, page = inkPage();
  const hit = (s) => {
    const p = s.p, pad = r + s.w / 2;
    if (!s.box) {
      let a = Infinity, b = Infinity, c = -Infinity, d = -Infinity;
      for (let i = 0; i < p.length; i += 3) { a = Math.min(a, p[i]); b = Math.min(b, p[i + 1]); c = Math.max(c, p[i]); d = Math.max(d, p[i + 1]); }
      Object.defineProperty(s, "box", { value: [a / 10, b / 10, c / 10, d / 10], enumerable: false });
    }
    if (x < s.box[0] - pad || x > s.box[2] + pad || y < s.box[1] - pad || y > s.box[3] + pad) return false;
    for (let i = 0; i < p.length; i += 3) {
      const ax = p[i] / 10, ay = p[i + 1] / 10, bx = i + 3 < p.length ? p[i + 3] / 10 : ax, by = i + 3 < p.length ? p[i + 4] / 10 : ay;
      const dx = bx - ax, dy = by - ay, len = dx * dx + dy * dy;
      const t = len ? Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / len)) : 0;
      if (Math.hypot(ax + t * dx - x, ay + t * dy - y) <= pad) return true;
    }
    return false;
  };
  const keep = page.strokes.filter((s) => !hit(s));
  if (keep.length === page.strokes.length) return;
  if (!ink.cur.erased) { inkSnapshot(); ink.cur.erased = true; }
  page.strokes = keep; inkRedraw(); inkChanged();
}

function inkPanMove() {
  const ys = [...ink.pointers.values()].map((p) => p.y), y = ys.reduce((a, b) => a + b, 0) / ys.length;
  // ладонь, лежащая на экране, пока пишет перо, страницу не двигает
  const palm = (ink.cur && !ink.cur.touch) || performance.now() - ink.lastPen < 400;
  if (ink.pan !== null && !palm) $("#ink-scroll").scrollTop -= y - ink.pan;
  ink.pan = y;
}

function inkBind() {
  const live = $("#ink-live");
  live.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "pen") ink.lastPen = performance.now();
    if (e.pointerType === "pen" && ink.penOnly === null) {
      ink.penOnly = true; inkSetPref("pen_only", true);
      toast("Стилус найден: пишет только он, пальцем — листать"); setTimeout(inkRender, 0);
    }
    if (e.pointerType === "touch") {
      ink.pointers.set(e.pointerId, { y: e.clientY });
      if (ink.penOnly || ink.pointers.size > 1) {
        if (ink.cur && ink.cur.touch) { ink.cur = null; inkFrame(); }  // второй палец — это прокрутка, а не штрих
        ink.pan = null; inkPanMove(); return;
      }
    }
    if (e.pointerType === "mouse" && e.button !== 0) return;
    if (ink.cur) return;
    e.preventDefault();
    try { live.setPointerCapture(e.pointerId); } catch (_) { /* уже отпущен */ }
    const rect = live.getBoundingClientRect(), pt = inkPoint(e, rect);
    const eraser = ink.tool === "eraser" || (e.pointerType === "pen" && (e.buttons & 32));  // обратный конец пера — ластик
    ink.cur = { id: e.pointerId, rect, touch: e.pointerType === "touch", eraser };
    if (eraser) { ink.cur.at = [pt[0] / 10, pt[1] / 10]; inkErase(ink.cur.at); }
    else {
      const hl = ink.tool === "hl";
      ink.cur.s = { t: hl ? "hl" : "pen", c: hl ? INK_HL.c : ink.color, w: hl ? INK_HL.w : INK_WIDTHS[ink.width][0], p: pt };
    }
    inkFrame();
  });
  live.addEventListener("pointermove", (e) => {
    if (e.pointerType === "pen") ink.lastPen = performance.now();
    if (ink.pointers.has(e.pointerId) && (ink.penOnly || ink.pointers.size > 1)) { ink.pointers.get(e.pointerId).y = e.clientY; inkPanMove(); return; }
    if (!ink.cur || ink.cur.id !== e.pointerId) return;
    e.preventDefault();
    const events = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
    for (const ev of events.length ? events : [e]) {
      const pt = inkPoint(ev, ink.cur.rect);
      if (ink.cur.eraser) { ink.cur.at = [pt[0] / 10, pt[1] / 10]; inkErase(ink.cur.at); continue; }
      const p = ink.cur.s.p, n = p.length;
      if (Math.abs(p[n - 3] - pt[0]) + Math.abs(p[n - 2] - pt[1]) < 6) { p[n - 1] = Math.max(p[n - 1], pt[2]); continue; }  // < 0,6 ед. — та же точка
      p.push(...pt);
    }
    inkFrame();
  });
  const end = (e) => {
    if (ink.pointers.delete(e.pointerId)) { ink.pan = null; if (ink.pointers.size) inkPanMove(); }
    if (!ink.cur || ink.cur.id !== e.pointerId) return;
    const cur = ink.cur; ink.cur = null;
    if (cur.s && e.type !== "pointercancel") {
      inkSnapshot(); inkPage().strokes.push(cur.s);
      inkStroke($("#ink-base").getContext("2d"), cur.s); inkChanged();
    }
    inkFrame();
  };
  live.addEventListener("pointerup", end);
  live.addEventListener("pointercancel", end);
  live.addEventListener("contextmenu", (e) => e.preventDefault());

  ink.el.querySelectorAll("[data-tool]").forEach((b) => b.addEventListener("click", () => { ink.tool = b.dataset.tool; haptic("soft"); inkRender(); }));
  ink.el.querySelectorAll("[data-color]").forEach((b) => b.addEventListener("click", () => {
    ink.color = b.dataset.color; ink.tool = "pen"; inkSetPref("color", ink.color); haptic("soft"); inkRender();
  }));
  ink.el.querySelectorAll("[data-width]").forEach((b) => b.addEventListener("click", () => {
    ink.width = +b.dataset.width; if (ink.tool === "eraser") ink.tool = "pen"; inkSetPref("width", ink.width); haptic("soft"); inkRender();
  }));
  $("#ink-undo").onclick = () => inkUndo(ink.undo, ink.redo);
  $("#ink-redo").onclick = () => inkUndo(ink.redo, ink.undo);
  $("#ink-bg").onclick = () => {
    const keys = Object.keys(INK_BG), page = inkPage();
    page.bg = keys[(keys.indexOf(page.bg) + 1) % keys.length]; inkSetPref("bg", page.bg); inkChanged(); inkRender();
  };
  $("#ink-pen").onclick = () => { ink.penOnly = !ink.penOnly; inkSetPref("pen_only", ink.penOnly); toast(ink.penOnly ? "Пишет только стилус, пальцем — листать" : "Пишут палец и стилус"); inkRender(); };
  $("#ink-prev").onclick = () => inkGo(ink.page - 1);
  $("#ink-next").onclick = () => inkGo(ink.page + 1);
  $("#ink-add").onclick = () => {
    const pages = ink.note.pages;
    if (pages.length >= 60) { toast("В одном конспекте до 60 страниц — начни новый"); return; }
    pages.push({ bg: inkPref("bg", inkPage().bg), strokes: [] }); ink.dirty.add(pages.length - 1); inkGo(pages.length - 1);
  };
  $("#ink-done").onclick = async () => { if (await inkSave(true)) closeInk(true); };
  $("#ink-close").onclick = () => closeInk();
}

function inkUndo(from, to) {
  const step = from.pop(); if (!step) return;
  const page = ink.note.pages[step.page];
  to.push({ page: step.page, strokes: page.strokes.slice() });
  page.strokes = step.strokes;
  if (step.page !== ink.page) { ink.page = step.page; inkRender(); } else inkRedraw();
  inkChanged(); haptic("soft");
}

function inkGo(i) {
  if (i < 0 || i >= ink.note.pages.length) return;
  ink.page = i; inkRender(); $("#ink-scroll").scrollTop = 0;
}

function inkPng(page) {
  const c = document.createElement("canvas");
  c.width = Math.round(INK_W * INK_EXPORT); c.height = Math.round(INK_H * INK_EXPORT);
  const ctx = c.getContext("2d"); ctx.setTransform(INK_EXPORT, 0, 0, INK_EXPORT, 0, 0);
  inkPaint(ctx, page);
  return c.toDataURL("image/png").split(",")[1];
}

/* Сохранить: лишние пустые страницы в конце (новые) отбрасываются, PNG — только изменённых. */
async function inkSave(transcribe, quiet = false) {
  if (!ink.note || ink.saving) return false;
  clearTimeout(ink.idle);
  const n = ink.note;
  while (n.pages.length > Math.max(1, ink.saved) && !n.pages[n.pages.length - 1].strokes.length) { n.pages.pop(); ink.dirty.delete(n.pages.length); }
  if (ink.page >= n.pages.length) ink.page = n.pages.length - 1;
  if (!ink.dirty.size && !transcribe) return true;
  ink.saving = true;
  const mark = $("#ink-saved"); if (mark) mark.textContent = "сохраняю…";
  const send = async (rev) => {
    const png = {};
    for (const i of ink.dirty) if (n.pages[i]) png[i] = inkPng(n.pages[i]);
    return api("ink", { json: { path: n.path, rev, pages: n.pages, png, transcribe } });
  };
  try {
    let r;
    try { r = await send(n.rev); }
    catch (err) {
      if (!(err.data && err.data.conflict) || quiet) throw err;
      if (!confirm("Конспект изменился на другом устройстве. Сохранить версию с этого? Отмена — открыть ту версию.")) {
        try { localStorage.removeItem(inkKey(n.path)); } catch (_) { /* нет */ }
        ink.saving = false; await openInk(n.path); return false;
      }
      r = await send(err.data.sha);
    }
    n.rev = r.rev; n.status = r.status; ink.saved = r.pages.length; ink.dirty.clear();
    try { localStorage.removeItem(inkKey(n.path)); } catch (_) { /* нет */ }
    for (const key of [...assetCache.keys()]) if (key.startsWith(n.dir + "/")) { URL.revokeObjectURL(assetCache.get(key)); assetCache.delete(key); }
    const m2 = $("#ink-saved"); if (m2) m2.textContent = "сохранено";
    if (!quiet) notify("success");
    return true;
  } catch (err) {
    const m3 = $("#ink-saved"); if (m3) m3.textContent = "не сохранено";
    if (!quiet) { notify("error"); toast(err.message); }
    return false;
  } finally { ink.saving = false; }
}

function inkHidden() { if (document.visibilityState === "hidden" && ink.dirty.size) inkSave(false, true); }

async function closeInk(saved = false) {
  if (!ink.el) return;
  if (!saved && ink.dirty.size && !(await inkSave(false)) && !confirm("Не сохранилось. Закрыть? Черновик останется на этом устройстве.")) return;
  const path = ink.note.path;
  clearTimeout(ink.idle); clearTimeout(ink.draft);
  window.removeEventListener("resize", inkLayout);
  document.removeEventListener("visibilitychange", inkHidden);
  ink.el.remove(); ink.el = null; ink.note = null; ink.pointers.clear(); ink.cur = null;
  document.documentElement.classList.remove("ink-on");
  try { TG && TG.enableVerticalSwipes && TG.enableVerticalSwipes(); } catch (_) { /* старый клиент */ }
  if (TG) TG.BackButton.offClick(closeInk);
  if (state.tab !== "notes") setTab("notes");
  await openNote(path, { keepScroll: true });
  if (saved) toast("Сохранено. Arvix расшифрует в фоне — почерк останется почерком");
}

document.addEventListener("keydown", (e) => {
  if (!inkOpen()) return;
  e.stopImmediatePropagation();
  const mod = e.ctrlKey || e.metaKey;
  if (e.key === "Escape") { e.preventDefault(); closeInk(); }
  else if (mod && e.code === "KeyZ") { e.preventDefault(); e.shiftKey ? inkUndo(ink.redo, ink.undo) : inkUndo(ink.undo, ink.redo); }
  else if (mod && e.code === "KeyY") { e.preventDefault(); inkUndo(ink.redo, ink.undo); }
  else if (mod && e.code === "KeyS") { e.preventDefault(); inkSave(false); }
  else if (!mod && !e.altKey && { KeyP: "pen", KeyH: "hl", KeyE: "eraser" }[e.code]) { ink.tool = { KeyP: "pen", KeyH: "hl", KeyE: "eraser" }[e.code]; inkRender(); }
  else if (!mod && (e.code === "PageDown" || e.code === "ArrowRight")) inkGo(ink.page + 1);
  else if (!mod && (e.code === "PageUp" || e.code === "ArrowLeft")) inkGo(ink.page - 1);
}, true);

/* Новый конспект от руки — в открытой папке (в корне — в папке конспектов из настроек). */
async function newInkNote() {
  const d = new Date();
  const name = prompt("Название конспекта", `Конспект ${d.toLocaleDateString("ru-RU")}`);
  if (!name || !name.trim()) return;
  try {
    const n = await api("ink/new", { json: { dir: state.notesDir, name: name.trim() } });
    state.notesList = null;
    await openInk(n.path);
  } catch (err) { toast(err.message); }
}

/* Строка над рукописной заметкой: идёт ли разбор, что не расшифровано, кнопка повтора. */
function inkStatusHtml(st) {
  if (!st) return "";
  let line;
  if (st.pending) line = `<span class="spin"></span> Arvix расшифровывает страницы…`;
  else if (st.error && st.stale.length) line = `⚠ Не расшифровал: ${esc(st.error)} <button class="pill small-pill" id="ink-retry">Повторить</button>`;
  else if (st.stale.length) line = `${st.stale.length} ${plural(st.stale.length, "страница", "страницы", "страниц")} без расшифровки <button class="pill small-pill" id="ink-retry">Расшифровать</button>`;
  else if (st.pages) line = `✓ Arvix прочитал${st.summary ? ": " + esc(st.summary) : ""} · текст — в «Расшифровке» внизу`;
  else line = `Пока пусто — нажми «✍ Писать»`;
  return `<div class="ink-status muted small">${line}</div>`;
}

async function inkRetry(path) {
  try { await api("ink/transcribe", { json: { path } }); state.note.ink = { ...state.note.ink, pending: true, error: "" }; renderNote(); }
  catch (err) { toast(err.message); }
}

// --- вложения ![[…]]: картинка грузится с ключом в заголовке, а не в URL -----------------------
const assetCache = new Map();
function hydrateAssets(root, version = "") {
  root.querySelectorAll("[data-asset]").forEach(async (el) => {
    const path = el.dataset.asset;
    try {
      if (!assetCache.has(path)) {
        // version — у страниц конспекта от руки: тот же файл после дописывания не берётся из кэша браузера
        const res = await fetch("/api/file?path=" + encodeURIComponent(path) + (version ? "&v=" + version : ""), { headers: authHeaders() });
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
    <div class="heat-foot"><span class="muted small" id="heat-info">${isWide() ? "Клик" : "Тап"} по дню — что в нём было</span>
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
    html += heatCard(h.heat) + `<div class="progress-grid">`;
    // Нормы недели нет (распорядок не сохранён) — «2ч из 0м» бессмысленно: показываем факт без полосы
    const weekRow = (label, done, need, cls, top) => `<div class="row"${top ? ' style="margin-top:6px"' : ""}><span>${label}</span><b>${hm(done)}${need ? " из " + hm(need) : ""}</b></div>`
      + (need ? `<div class="bar${cls}"><i style="width:${Math.min(100, 100 * done / need)}%"></i></div>` : "");
    html += `<div class="card"><h3>Неделя</h3>
      ${weekRow("Сделано", w.productive_min, w.budget_min, "", false)}
      ${weekRow("Глубокая работа", w.deep_min, w.deep_budget_min, " deep", true)}
      ${!w.budget_min ? `<div class="muted small" style="margin-top:6px">Нормы недели нет: распорядок дней не сохранён. Скажи Arvix «собери распорядок».</div>` : ""}
      <div class="pills" style="margin-top:10px">${w.quotas.map((q) => `<span class="chip ${q.done >= q.need ? "green" : ""}">${esc(q.label)} ${q.done}/${q.need}</span>`).join("")}</div></div>`;
    html += chartCard("Выполнение, %", h.days, (d) => d.completion, 100, "var(--accent)");
    html += chartCard("Сон, часы", h.days, (d) => (d.sleep_min == null ? null : d.sleep_min / 60), 10, "var(--accent-2)", 7.5);
    html += chartCard("Глубокая работа, мин", h.days, (d) => d.deep_min, null, "var(--warn)");
    if (h.goals.length) {
      html += `<div class="card"><h3>Цели</h3>${h.goals.map((g) => `<div class="goal" style="padding-left:${g.depth * 14}px">
        <div class="t">${g.status === "done" ? "●" : "○"} ${esc(g.title)}</div>
        <div class="muted small">${[g.deadline ? "до " + esc(g.deadline) : "", g.metric ? esc(g.metric) : ""].filter(Boolean).join(" · ")}</div></div>`).join("")}</div>`;
    }
    html += `</div>`;
  }
  html += `<div class="card"><h3>Приложение</h3>
    ${TG ? `<button class="btn" id="install">${icon("download")} Установить на телефон</button><p class="muted small">Откроется Chrome — там кнопка «Установить» (или ⋮ → «Установить приложение»): появится иконка Arvix, как у обычного приложения. Ссылка одноразовая, живёт 15 минут.</p>` :
    `${standalone() ? `<p class="muted small">Arvix установлен как приложение.</p>` : `<button class="btn primary" id="install-pwa">${icon("download")} Установить как приложение</button>
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
        if (state.tab === "notes" && state.note && state.note.ink && !state.noteEdit && !inkOpen()) {
          const r = await api("note?path=" + encodeURIComponent(state.note.path));  // идёт расшифровка — статус и текст обновятся сами
          if (state.note && r.path === state.note.path && !state.noteEdit && !inkOpen()
              && (r.sha !== state.note.sha || JSON.stringify(r.ink) !== JSON.stringify(state.note.ink))) { state.note = r; renderNote(); }
        }
      }
    } catch (err) { if (err.auth) renderLogin(); }
  }, 250);
}

// --- клавиатура (ноутбук) ----------------------------------------------------------------------
/* Ctrl/Alt+1…5 — вкладки, Alt+N — новая задача, / — поиск или поле сообщения, E — править заметку
 * (клавиши — по e.code, чтобы работали и на русской раскладке),
 * Ctrl+S — сохранить, Esc — закрыть окно, заметку или разговор. На телефоне клавиатуры нет — ничего не мешает. */
const TABS = ["today", "chat", "notes", "progress", "study"];
document.addEventListener("keydown", (e) => {
  if (inkOpen()) return;  // у холста свои клавиши
  const typing = e.target instanceof Element && !!e.target.closest("input, textarea, select, [contenteditable]");
  if ((e.ctrlKey || e.metaKey) && e.code === "KeyS" && $("#e-text")) { e.preventDefault(); saveEditor(); return; }
  if (e.key === "Escape") {
    if (!$("#sheet").classList.contains("hidden")) { closeSheet(); return; }
    if (state.tab === "notes" && state.note) { e.preventDefault(); noteBack(); return; }
    if (typing) e.target.blur();
    return;
  }
  if ((e.altKey || e.ctrlKey) && !e.shiftKey && /^Digit[1-5]$/.test(e.code)) {
    e.preventDefault();
    const tab = TABS[+e.code.slice(5) - 1];
    if (tab !== state.tab && !(state.noteEdit && !confirmLeaveEditor())) setTab(tab);
    return;
  }
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.code === "KeyB" && isWide()) { e.preventDefault(); toggleSide(); return; }
  if (e.altKey && e.code === "KeyN") { e.preventDefault(); if (state.data && !state.data.gentle) openAddSheet(); return; }
  if (typing || e.ctrlKey || e.metaKey || e.altKey || !$("#sheet").classList.contains("hidden")) return;
  if (e.key === "/" || e.code === "Slash") {  // физическая клавиша: на русской раскладке она даёт «.»
    const box = state.tab === "notes" ? $("#n-q") : state.tab === "chat" ? $("#msg") : null;
    if (box) { e.preventDefault(); box.focus(); }
  } else if (e.code === "KeyE" && state.tab === "notes" && state.note && !state.noteEdit) {
    e.preventDefault(); state.noteEdit = true; renderNote();
    setTimeout(() => $("#e-text") && $("#e-text").focus(), 30);
  }
});

// --- старт -------------------------------------------------------------------------------------
if (TG) {
  document.documentElement.classList.add("tg");
  TG.ready(); TG.expand();
  try { TG.setHeaderColor("secondary_bg_color"); TG.setBackgroundColor("secondary_bg_color"); } catch (_) { /* старый клиент */ }
  if (TG.colorScheme) document.documentElement.dataset.theme = TG.colorScheme;
}
if ("serviceWorker" in navigator && !TG) navigator.serviceWorker.register("sw.js").catch(() => {});

/* «Поделиться → Arvix»: service worker сложил файлы и текст в кэш — отправляем их как из 📎. */
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

try { setSideMini(localStorage.getItem(SIDE_KEY) === "1"); } catch (_) { setSideMini(false); }

(async function boot() {
  await pairFromHash();
  if (!TG && !token()) { renderLogin(); return; }
  const params = new URLSearchParams(location.search);
  const start = params.get("tab") || (TG && TG.initDataUnsafe && TG.initDataUnsafe.start_param) || "today";
  setTab(TABS.includes(start) ? start : "today");
  stream();
  ping(true);
  if (params.get("shared")) sendShared().catch((err) => toast(err.message));
})();
