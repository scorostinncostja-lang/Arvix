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
  study: '<path d="M21.42 10.92a1 1 0 0 0-.02-1.84l-8.57-3.9a2 2 0 0 0-1.66 0l-8.57 3.9a1 1 0 0 0 0 1.83l8.57 3.91a2 2 0 0 0 1.66 0z"/><path d="M22 10v6"/><path d="M6 12.5V16a6 3 0 0 0 12 0v-3.5"/>',
  projects: '<path d="M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/><rect width="20" height="14" x="2" y="6" rx="2"/>',
  github: '<path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/><path d="M9 18c-4.51 2-5-2-7-2"/>',
  sidebar: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/><path d="m16 15-3-3 3-3"/>',
  map: '<path d="M14.106 5.553a2 2 0 0 0 1.788 0l3.659-1.83A1 1 0 0 1 21 4.619v12.764a1 1 0 0 1-.553.894l-4.553 2.277a2 2 0 0 1-1.788 0l-4.212-2.106a2 2 0 0 0-1.788 0l-3.659 1.83A1 1 0 0 1 3 19.381V6.618a1 1 0 0 1 .553-.894l4.553-2.277a2 2 0 0 1 1.788 0z"/><path d="M15 5.764v15"/><path d="M9 3.236v15"/>',
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
  if (tab === "study" && state.tab_prev !== "study") studyUI.auto = !studyUI.open;  // вход во вкладку: идёт урок — на стол
  if (tab !== "projects" && state.project) { state.project = null; if (TG) { TG.BackButton.offClick(projectBack); TG.BackButton.hide(); } }
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
    if (tab === "today" || !state.data) state.data = await api("state");
    if (tab === "chat") {
      const r = await api("messages");
      const last = r.messages.length ? r.messages[r.messages.length - 1].id : 0;
      state.messages = r.messages; state.thinking = r.thinking || "";
      state.seen = Math.max(state.seen, last);
    }
    if (tab === "progress") state.history = await api("history?days=30");
    if (tab === "projects") await loadProjects();
    if (tab === "study") await loadStudy();
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
  view.classList.toggle("full", state.tab === "projects" || state.tab === "study");  // окна проектов и сессии — на всю ширину
  if (state.tab === "today") renderToday();
  else if (state.tab === "chat") renderChat();
  else if (state.tab === "notes") renderNotes();
  else if (state.tab === "projects") renderProjects();
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
    <h1>Арвикс</h1>
    <p class="muted">Откройте приложение из Telegram — кнопка «Арвикс» слева от поля ввода в чате с ботом.</p>
    <p class="muted small">Чтобы установить на телефон: в Telegram откройте приложение → «Прогресс» → «Установить на телефон».</p>
  </div>`;
}

// --- Сегодня -----------------------------------------------------------------------------------
function renderToday() {
  const d = state.data;
  if (!d) { view.innerHTML = `<div class="empty">Загружаю…</div>`; return; }
  let html = `<div class="today-grid"><div class="today-side">`;
  if (d.gentle) {
    html += `<div class="card note-card">${esc(d.note)}</div>`;
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
    html += `<div class="card install-card"><div><b>Арвикс как приложение</b><div class="muted small">Иконка на экране, своё окно, без адресной строки</div></div>
      <button class="pill primary" id="install-now">Установить</button></div>`;
  }
  html += focusCard(d);
  if (d.lesson && d.lesson.topic) {
    html += `<div class="card"><h3>Урок</h3><div><b>${esc(d.lesson.topic)}</b></div>
      <div class="muted small">${d.lesson.started ? "идёт — в конце вопросы проверки" : "план готов — ▶ на рабочем столе"}</div>
      <button class="pill small-pill primary" data-act="study-open" style="margin-top:8px">${icon("study")} Открыть сессию</button></div>`;
  }
  html += `</div><div class="today-main">`;
  const items = [...(d.tasks || []).map((t) => ({ ...t, kind: "task" })), ...(d.busy || []).map((b) => ({ ...b, kind: "busy" }))]
    .sort((a, b) => (a.start || "99").localeCompare(b.start || "99"));
  if (d.yesterday && d.yesterday.length) {  // после полуночи, до 04:00: вчерашнее ещё можно закрыть
    html += `<div class="section-title first"><span>Вчера — не закрыто</span><span>до 04:00</span></div>` + d.yesterday.map((t) => taskRow(t)).join("");
  }
  html += `<div class="section-title${d.yesterday && d.yesterday.length ? "" : " first"}"><span>План дня</span><span>${d.day_type ? esc(d.day_type) : ""}</span></div>`;
  html += items.length ? items.map((t) => (t.kind === "busy" ? busyRow(t) : taskRow(t))).join("") :
    `<div class="empty">На сегодня задач нет.<br><span class="small">Нажми «+»${isWide() ? " (Alt+N)" : ""} или напиши Арвиксу: «добавь физику в 18:00 на час».</span></div>`;
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
  view.querySelectorAll("[data-act]").forEach((el) => el.addEventListener("click", async () => {
    const act = el.dataset.act, id = el.dataset.id;
    haptic();
    try {
      if (act === "start") {
        const t = findTask(id);
        if (t && t.sphere === "learning") {  // учебный блок — урок на рабочем столе «Обучения»: план, окна, таймер (D55)
          await api("lesson/" + id, { json: {} }); toast("Готовлю сессию — план и окна появятся в «Обучении»");
          studyUI.open = true; studyUI.task = id; studyUI.notes = {}; setTab("study"); return;
        }
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
      } else if (act === "study-open") { studyUI.open = true; studyUI.task = null; setTab("study"); return; }
      else if (act === "focus-note") { openFocusNoteSheet({ event_id: +el.dataset.event, minutes: +el.dataset.min, title: el.dataset.title }); return; }
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
  if (TG) { TG.BackButton.offClick(closeSheet); if (!state.note && !state.project) TG.BackButton.hide(); }
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
      ${t.sphere === "learning" ? `<button class="btn" data-op="lesson">📚 ${t.open ? "Сессия: план, окна, таймер, проверка" : "Посмотреть сессию"}</button>` : ""}
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
        if (op === "lesson") { closeSheet(); openStudySession({ task: t.id }); return; }
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
 * Арвикс тоже отвечает цитатой, когда без неё непонятно, на что ответ, — это решает сервер. */
const chatUI = { reply: null, stick: true, unread: 0, lastId: 0 };
const WHO = { me: "Ты", arvix: "Арвикс" };
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
  return `<button type="button" class="quote ${q.who === "me" ? "q-me" : "q-arvix"}" data-goto="${q.id}"><b>${WHO[q.who] || "Арвикс"}</b><span>${esc(q.text || "…")}</span></button>`;
}

function msgHtml(m, prev, next, answered) {
  const at = new Date(m.at);
  const same = (o) => o && o.who === m.who && Math.abs(new Date(o.at) - at) < 5 * 60e3 && new Date(o.at).toDateString() === at.toDateString();
  const btns = (m.buttons || []).flat().filter((b) => b && b[1] && !String(b[1]).startsWith("app:"));
  // ✓ — дошло, ✓✓ — Арвикс ответил после; часы — ещё в пути
  const ticks = m.who !== "me" ? "" : !m.id ? `<i class="tick wait">${icon("clock")}</i>` : `<i class="tick${answered ? " read" : ""}">${icon(answered ? "checks" : "check")}</i>`;
  const cls = ["msg", m.who === "me" ? "me" : "", same(prev) ? "cont" : "", same(next) ? "" : "tail"].filter(Boolean).join(" ");
  return `<div class="${cls}" data-id="${m.id || ""}"><span class="swipe-ic">${icon("reply")}</span>${quoteHtml(m.reply_to)}<div class="mtext">${linkify(esc(m.text))}</div>${btns.length ? `<div class="btns">${btns.map((b) =>
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
  if (state.thinking) html += `<div class="typing" title="${esc(state.thinking)}"><i></i><i></i><i></i></div>`;
  if (!msgs.length && !state.thinking) html += `<div class="empty">Напиши или скажи что угодно — как в Telegram.</div>`;
  html += `</div>`;
  view.innerHTML = html;
  if (!$(".composer")) {
    const c = document.createElement("div");
    c.className = "composer";
    c.innerHTML = `<div class="reply-bar hidden" id="reply-bar"></div>
      <button class="round ghost" id="attach" aria-label="Прислать файл">${icon("clip")}</button>
      <input type="file" id="file" multiple hidden>
      <textarea id="msg" rows="1" placeholder="Сообщение Арвиксу"></textarea>
      <button class="round send" id="send" aria-label="Голосовое сообщение" data-mode="mic">${icon("mic")}</button>
      <button class="to-bottom hidden" id="to-bottom" aria-label="Вниз, к новым">${icon("chevronDown")}<b id="to-bottom-n"></b></button>`;
    document.body.appendChild(c);
    const ta = $("#msg");
    ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = Math.min(140, ta.scrollHeight) + "px"; composerMode(); });
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !("ontouchstart" in window)) { e.preventDefault(); sendMessage(); }
      else if (e.key === "Escape" && chatUI.reply) { e.preventDefault(); e.stopPropagation(); setReply(null); }
      else if (e.key === "ArrowUp" && (e.ctrlKey || e.metaKey) && !ta.value) {  // Ctrl+↑ — ответить на последнее Арвикса
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
  view.querySelectorAll("[data-btn]").forEach((b) => b.addEventListener("click", async () => {
    haptic(); b.disabled = true;
    try { await api("button", { json: { data: b.dataset.btn } }); state.thinking = "думаю"; renderChat({ bottom: true }); } catch (err) { toast(err.message); }
  }));
  bindChat($("#chat"));
  // Новое от Арвикса, пока читаешь старое, — счётчик на ↓, а не прыжок вниз
  const newest = msgs.reduce((a, m) => Math.max(a, m.id || 0), 0);
  if (!stick && newest > chatUI.lastId) chatUI.unread += msgs.filter((m) => m.id > chatUI.lastId && m.who === "arvix").length;
  chatUI.lastId = Math.max(chatUI.lastId, newest);
  if (stick) { window.scrollTo(0, document.documentElement.scrollHeight); chatUI.stick = true; chatUI.unread = 0; }
  else window.scrollTo(0, keepY);
  chatHeader(); toBottomButton(); pingSoon();
}

function chatHeader() {
  if (state.tab !== "chat") return;
  $("#top-day").textContent = "Арвикс";
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
    <button type="button" class="rb-body" data-goto="${r.id}"><b>В ответ ${r.who === "me" ? "себе" : "Арвиксу"}</b><span>${esc(r.text || "…")}</span></button>
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

/* Что Арвикс видит, как в мессенджере (D52): «в сети» — пульс раз в 30 с, пока приложение на экране;
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
  // Реакции — только на сообщения Арвикса: он их видит и учитывает (D52); ❓ — объяснит проще
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
    else { try { await navigator.clipboard.writeText(m.text); toast("Скопировано"); } catch (_) { toast("Не скопировалось"); } }
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

/* Файлы Арвиксу: фото, PDF, документы, архив репозитория, аудио, видео — до 20 МБ.
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
      <button class="pill" id="n-new">+ Заметка</button></div>`;
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
  const folder = n.path.includes("/") ? n.path.slice(0, n.path.lastIndexOf("/")) : "Хранилище";
  root.innerHTML = `<div class="note-bar"><button id="n-back" class="note-back" title="Esc">${isWide() ? icon("x") + " Закрыть" : icon("back") + " " + esc(folder.split("/").pop())}</button>
      ${isWide() ? `<span class="note-bar-title muted small">${esc(folder)}</span>` : ""}
      <button id="n-edit" class="icon-btn" aria-label="Править" title="Править (E)">${icon("pencil")}</button></div>
    <article class="obs">
      <h1 class="obs-title">${esc(noteName(n.path))}</h1>
      ${doc.props.length ? propsHtml(doc.props) : ""}
      ${doc.html || `<p class="muted">Пустая заметка. ✎ — написать.</p>`}
    </article>`;
  $("#n-back").onclick = closeNote;
  $("#n-edit").onclick = () => { state.noteEdit = true; renderNote(); };
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
  hydrateAssets(root);
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
      ${!w.budget_min ? `<div class="muted small" style="margin-top:6px">Нормы недели нет: распорядок дней не сохранён. Скажи Арвиксу «собери распорядок».</div>` : ""}
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
      html += `<div class="card"><h3>Уроки</h3>${h.lessons.slice().reverse().map((x) => `<div class="row"><span>${x.subject && !String(x.topic || "").toLowerCase().startsWith(String(x.subject).toLowerCase()) ? esc(x.subject) + ": " : ""}${esc(x.topic)}</span>
        <span class="chip ${x.score >= 70 ? "green" : x.score != null ? "yellow" : ""}">${x.score != null ? x.score + "%" : "—"}</span></div>`).join("")}</div>`;
    }
    html += `</div>`;
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

// --- Проекты (D43, D44, D47) -------------------------------------------------------------------------
/* Проект = чат с Арвиксом + папка в Obsidian. Человек говорит, Арвикс заполняет (D47).
 * Окна: список проектов (сгруппирован по целям — это и есть роадмап) · чат проекта · панель
 * «Заметки | План | Учиться». На ноутбуке — рядом, границу можно тянуть, окна прятать; на телефоне —
 * список, а внутри проекта вкладки. Цифры считает код (arvix/projects.py), в 🟥 вкладка без цифр. */
const ddmm = (iso) => (iso ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}` : "");
const LOG_ICON = { update: "✓", decision: "⚖", lesson: "💡", blocker: "⛔", release: "🚀", feedback: "💬", idea: "✨" };
const PROJ_LAYOUT_KEY = "arvix_projlayout";
const projLayout = (() => {
  try { return { list: true, side: true, sideW: 400, pane: "chat", tab: "notes", ...JSON.parse(localStorage.getItem(PROJ_LAYOUT_KEY) || "{}") }; }
  catch (_) { return { list: true, side: true, sideW: 400, pane: "chat", tab: "notes" }; }
})();
const saveLayout = () => { try { localStorage.setItem(PROJ_LAYOUT_KEY, JSON.stringify(projLayout)); } catch (_) { /* приватный режим */ } };
const PROJ_ASK = ["С чего начать?", "Разложи на этапы", "Что мне выучить для этого?", "Проверь мой прогресс", "Найди примеры и источники"];

async function loadProjects() {
  state.projects = await api("projects");
  if (state.projects.gentle) { state.project = null; return; }
  if (state.project) {
    try { state.project = await api("project?id=" + encodeURIComponent(state.project.id)); } catch (_) { state.project = null; }
  }
}

function renderProjects() {
  const P = state.projects;
  if (!P) { view.innerHTML = `<div class="empty">Загружаю…</div>`; return; }
  if (P.gentle) { view.innerHTML = `<div class="card note-card">${esc(P.note)}</div>`; return; }
  const keep = captureComposer();
  if (isWide()) {
    const cols = [projLayout.list ? "var(--pl-w)" : "", "minmax(0,1fr)", projLayout.side && state.project ? "6px var(--ps-w)" : ""].filter(Boolean).join(" ");
    view.innerHTML = `<div class="pw" style="grid-template-columns:${cols};--ps-w:${projLayout.sideW}px">
      ${projLayout.list ? `<aside class="pw-list">${projListHtml(P)}</aside>` : ""}
      <section class="pw-main">${state.project ? projHeadHtml() + projChatHtml() : projWelcomeHtml(P)}</section>
      ${projLayout.side && state.project ? `<div class="pw-div" id="pw-div" title="Потяни, чтобы изменить ширину"></div><aside class="pw-side">${projSideHtml()}</aside>` : ""}</div>`;
  } else if (!state.project) {
    view.innerHTML = `<div class="pm-list">${projListHtml(P)}</div>`;
  } else {
    const pane = projLayout.pane;
    view.innerHTML = `<div class="pm">${projHeadHtml()}
      <div class="seg pm-tabs">${[["chat", "Чат"], ["notes", "Заметки"], ["plan", "План"], ["learn", "Учиться"]].map(([k, l]) =>
        `<button type="button" data-ppane="${k}" class="${pane === k ? "on" : ""}">${l}</button>`).join("")}</div>
      ${pane === "chat" ? projChatHtml() : `<div class="pm-pane">${projPaneHtml(pane)}</div>`}</div>`;
  }
  bindProjects();
  restoreComposer(keep);
  const thread = $("#pc-thread"); if (thread) thread.scrollTop = thread.scrollHeight;
  if (thread) thread.querySelectorAll("[data-goto]").forEach((q) => q.onclick = () => gotoMsg(q.dataset.goto));
  if (TG) {
    TG.BackButton.offClick(projectBack);
    if (state.project && !isWide()) { TG.BackButton.show(); TG.BackButton.onClick(projectBack); } else if (!state.note) TG.BackButton.hide();
  }
}

/* Перерисовка не должна терять набранный текст и фокус. */
function captureComposer() {
  const ta = $("#pc-text");
  return ta ? { value: ta.value, focus: document.activeElement === ta, pos: ta.selectionStart } : null;
}
function restoreComposer(keep) {
  const ta = $("#pc-text");
  if (!ta || !keep) return;
  ta.value = keep.value;
  if (keep.focus) { ta.focus(); try { ta.setSelectionRange(keep.pos, keep.pos); } catch (_) { /* нет */ } }
}

// --- список: группы по целям = роадмап ---------------------------------------------------------
function projListHtml(P) {
  let html = `<button class="btn primary pl-new" data-pact="new">${icon("plus")} Новый проект</button>`;
  if (P.load_issue) html += `<div class="pl-warn">⚠️ ${esc(P.load_issue)}</div>`;
  if (P.ideas > P.ideas_max) html += `<div class="pl-warn">Неначатых проектов ${P.ideas}. Пройдись по ним: что не нужно — ✕, что нужно — открой и «В работу». Новые Арвикс не предложит, пока их больше ${P.ideas_max}.</div>`;
  if (!P.count) html += `<p class="muted small pl-hint">Напиши, что хочешь сделать, — Арвикс сам разложит проект, заведёт папку в Obsidian и будет вести его с тобой.</p>`;
  for (const g of P.groups) {
    html += `<div class="pl-group"><div class="pl-ghead"><span>${g.goal ? (g.goal.kind === "main" ? "★ " : "") + esc(g.goal.title) : "Без цели"}</span></div>
      ${g.projects.map(projItemHtml).join("")}</div>`;
  }
  const idle = P.idle_goals || [];
  if (idle.length) {
    html += `<details class="pl-group pl-idle"><summary class="pl-ghead"><span>Цели без проектов · ${idle.length}</span></summary>
      <p class="muted small pl-hint">Не каждой цели нужен проект: экзамену — учёба, телу — привычка. ✨ — Арвикс предложит один следующий проект или скажет, что он не нужен.</p>
      ${idle.map((g) => `<div class="pl-goal"><span class="grow">${g.kind === "main" ? "★ " : ""}${esc(g.title)}</span>
        <button class="link small" data-proadmap="${esc(g.id)}" title="Арвикс предложит один проект к этой цели">✨</button></div>`).join("")}</details>`;
  }
  if (P.closed.length) html += `<details class="pl-group"><summary class="pl-ghead"><span>Завершённые · ${P.closed.length}</span></summary>${P.closed.map(projItemHtml).join("")}</details>`;
  return html;
}

function projItemHtml(p) {
  const on = state.project && state.project.id === p.id;
  const later = p.group === "later";
  const sub = p.group === "closed" ? p.status_ru : later ? (p.status === "idea" ? "не начат" : "на паузе") + (p.by === "arvix" ? " · предложил Арвикс" : "")
    : p.idle_days >= 7 ? `<span class="warn">${p.idle_days} дн без движения</span>` : p.next ? "→ " + esc(p.next.title) : "этапов нет";
  return `<div class="pl-item${on ? " on" : ""} ${p.group}" data-proj="${esc(p.id)}" role="button" tabindex="0">
    <span class="pl-dot"></span><div class="grow"><div class="pl-title">${esc(p.title)}</div><div class="pl-sub">${sub}</div></div>
    ${later ? `<button class="icon-btn sm pl-drop" data-pdrop="${esc(p.id)}" title="Не нужен — убрать из списка" aria-label="Не нужен">✕</button>` : ""}</div>`;
}

function projWelcomeHtml(P) {
  return `<div class="pw-welcome"><h2>Что хочешь сделать?</h2>
    <p class="muted">Опиши, как другу: что, зачем, к какому сроку. Арвикс заведёт проект, разложит на этапы, скажет, что выучить, и создаст папку в Obsidian.</p>
    <textarea id="pn-text" rows="4" placeholder="Например: хочу сделать бота, который напоминает классу про домашку. Хочу научиться Python и чтобы им пользовались хотя бы 10 человек. К Новому году."></textarea>
    ${(P.goals || []).length ? `<select id="pn-goal" class="input"><option value="">Цель — пусть решит Арвикс</option>${P.goals.map((g) => `<option value="${esc(g.id)}">${esc(g.title)}</option>`).join("")}</select>` : ""}
    <button class="btn primary" id="pn-go">${icon("send")} Начать проект</button></div>`;
}

// --- проект: шапка и чат ---------------------------------------------------------------------------
function projHeadHtml() {
  const p = state.project;
  const chips = [`<span class="chip ${p.status === "active" ? "accent" : p.group === "closed" ? "green" : ""}">${esc(p.status_ru)}</span>`];
  if (p.goal_title) chips.push(`<span class="chip">→ ${esc(p.goal_title)}</span>`);
  if (p.deadline) chips.push(`<span class="chip">до ${ddmm(p.deadline)}</span>`);
  if (p.status === "active" && p.idle_days >= 7) chips.push(`<span class="chip yellow">${p.idle_days} дн без движения</span>`);
  if (p.milestones_total) chips.push(`<span class="chip">этапы ${p.milestones_done}/${p.milestones_total}</span>`);
  return `<div class="ph">${isWide() ? "" : `<button class="icon-btn sm" data-pact="back" aria-label="К списку">${icon("back")}</button>`}
    <div class="grow ph-text"><div class="ph-title">${esc(p.title)}</div><div class="meta">${chips.join("")}</div></div>
    <div class="ph-acts">${p.group !== "closed" ? `<button class="pill primary small-pill" data-pact="block">${icon("play")} Блок</button>` : ""}
      <a class="pill small-pill" href="${obsidianUrl(p.main_note)}" title="Открыть папку проекта в Obsidian">${icon("notes")}${isWide() ? " Obsidian" : ""}</a>
      ${isWide() ? `<button class="icon-btn sm" data-layout="list" title="Список проектов">◧</button><button class="icon-btn sm" data-layout="side" title="Заметки, план, учиться">◨</button>` : ""}
      <button class="icon-btn sm" data-pact="menu" aria-label="Ещё">${icon("more")}</button></div></div>`;
}

function obsidianUrl(path) {
  const vault = (state.projects && state.projects.vault) || (state.study && state.study.vault) || "";
  return `obsidian://open?vault=${encodeURIComponent(vault)}&file=${encodeURIComponent(String(path || "").replace(/\.md$/, ""))}`;
}

function projChatHtml() {
  const p = state.project, msgs = p.messages || [];
  const thinking = state.thinking && (!msgs.length || msgs[msgs.length - 1].who === "me");
  return `<div class="pc"><div class="pc-thread" id="pc-thread">
      ${msgs.length ? msgs.map((m) => `<div class="msg ${m.who === "me" ? "me" : ""}" data-pid="${m.id}">${quoteHtml(m.reply_to)}<div class="mtext">${linkify(esc(m.text))}</div></div>`).join("")
        : `<div class="pc-empty muted small">Здесь разговор только про «${esc(p.title)}». Арвикс видит этапы, заметки папки, время и присланные файлы — и сам всё записывает.</div>`}
      ${thinking ? `<div class="msg typing">Арвикс думает…</div>` : ""}</div>
    ${msgs.length < 3 ? `<div class="aw-chips">${PROJ_ASK.map((q) => `<button class="chip" data-ask="${esc(q)}">${esc(q)}</button>`).join("")}</div>` : ""}
    <div class="pc-compose"><button class="icon-btn" id="pc-file" aria-label="Прислать файл: код, скриншот, PDF">${icon("clip")}</button>
      <textarea id="pc-text" rows="1" placeholder="Сообщение Арвиксу о проекте"></textarea>
      <button class="icon-btn go" id="pc-send" aria-label="Отправить">${icon("send")}</button>
      <input type="file" id="pc-input" multiple hidden></div></div>`;
}

// --- панель: заметки · план · учиться -----------------------------------------------------------------
function projSideHtml() {
  const tab = projLayout.tab;
  return `<div class="seg ps-tabs">${[["notes", "Заметки"], ["plan", "План"], ["learn", "Учиться"]].map(([k, l]) =>
    `<button type="button" data-ptab="${k}" class="${tab === k ? "on" : ""}">${l}</button>`).join("")}</div>
    <div class="ps-body">${projPaneHtml(tab)}</div>`;
}

function projPaneHtml(kind) {
  if (kind === "notes") return projNotesHtml();
  if (kind === "plan") return projPlanHtml();
  return projLearnHtml();
}

function projNotesHtml() {
  const p = state.project, n = state.projNote;
  if (n && n.path) {
    return `<div class="pn-bar"><button class="link small" data-pnote-close>${icon("back")} Заметки</button>
        <b class="grow">${esc(noteName(n.path))}</b>
        ${n.edit ? `<button class="pill small-pill primary" data-pnote-save>Сохранить</button><button class="pill small-pill" data-pnote-cancel>Отмена</button>`
          : `<button class="pill small-pill" data-pnote-edit>${icon("pencil")}</button><a class="pill small-pill" href="${obsidianUrl(n.path)}">Obsidian</a>`}</div>
      ${n.edit ? `<textarea id="pn-edit" class="pn-edit">${esc(n.text)}</textarea>` : (() => {
        const doc = obsidian(n.text);
        return `<div class="obs pn-view">${doc.props.length ? propsHtml(doc.props) : ""}${doc.html || `<p class="muted">Пустая заметка — ✎, чтобы написать.</p>`}</div>`;
      })()}`;
  }
  const files = p.files || [];
  return `<div class="pn-head"><span class="muted small">${esc(p.folder)}</span><button class="link small" data-pnote-new>+ заметка</button></div>
    ${files.length ? files.map((f) => `<div class="pn-file${f.main ? " main" : ""}" ${f.note ? `data-pnote="${esc(f.path)}"` : `data-pfile="${esc(f.path)}"`} role="button" tabindex="0">
      <span class="pn-ico">${f.main ? "★" : f.note ? "📝" : "📎"}</span><div class="grow"><div>${esc(f.name)}</div>
      <div class="muted small">${f.sub ? esc(f.sub) + " · " : ""}${new Date(f.modified * 1000).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}</div></div></div>`).join("")
      : `<div class="muted small">Папка пустая. Попроси Арвикса: «заведи заметку с планом» — или пришли файл в чат.</div>`}`;
}

function projPlanHtml() {
  const p = state.project;
  let html = "";
  if (p.issues.length) html += `<div class="pp-sec warn-card"><b>Арвикс видит</b>${p.issues.map((x) => `<div class="small">⚠️ ${esc(x)}</div>`).join("")}</div>`;
  if (p.expectation) html += `<div class="pp-sec"><div class="muted small">Результат</div><div>${esc(p.expectation)}</div></div>`;
  html += `<div class="pp-sec"><div class="pp-h"><b>Этапы ${p.milestones_done}/${p.milestones_total}</b><button class="link small" data-pact="milestone">+ этап</button></div>
    ${p.milestones.length ? p.milestones.map((m) => `<div class="ms ${m.status}"><button class="ms-check" data-ms="${esc(m.id)}" aria-label="Отметить">${m.status === "done" ? icon("check") : ""}</button>
      <div class="ms-body"><div class="ms-title">${esc(m.title)}</div><div class="muted small">готово, когда: ${esc(m.dod)}${m.due ? ` · до ${ddmm(m.due)}` : ""}</div></div></div>`).join("")
      : `<div class="muted small">Этапов нет — попроси в чате «разложи на этапы».</div>`}</div>`;
  const open = p.tasks.filter((t) => t.open);
  html += `<div class="pp-sec"><div class="pp-h"><b>Блоки</b><button class="link small" data-pact="block">+ блок</button></div>
    ${open.length ? open.map((t) => `<div class="row small"><span>${ddmm(t.date)} ${esc(t.start || "")} · ${esc(t.title)}</span><span>${hm(t.duration_min)}</span></div>`).join("")
      : `<div class="muted small">Впереди блоков нет.</div>`}
    <div class="muted small" style="margin-top:6px">Неделя ${hm(p.week_min)}${p.weekly_min ? " из " + hm(p.weekly_min) : ""} · всего ${hm(p.minutes)}${p.forecast ? " · прогноз финиша " + ddmm(p.forecast) : ""}</div></div>`;
  html += `<div class="pp-sec"><div class="pp-h"><b>Журнал</b><button class="link small" data-pact="log">+ запись</button></div>
    ${p.log.length ? p.log.slice(0, 12).map((x) => `<div class="log-row"><span class="log-ico">${LOG_ICON[x.kind] || "•"}</span><div class="grow small">${esc(x.text)}<div class="muted">${ddmm(x.date)}</div></div></div>`).join("")
      : `<div class="muted small">Отчёты по блокам проекта попадают сюда сами.</div>`}</div>`;
  if (p.resources.length) {
    html += `<div class="pp-sec"><b>Источники и примеры</b>${p.resources.map((r) => `<div class="small res-row"><div class="grow">${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a>` : esc(r.title)}
      <span class="muted">${r.by === "arvix" ? " · проверь" : ""}${r.note ? " · " + esc(r.note) : ""}</span></div><button class="icon-btn sm" data-rdel="${esc(r.id)}" aria-label="Убрать">${icon("x")}</button></div>`).join("")}</div>`;
  }
  return html;
}

function projLearnHtml() {
  const items = state.project.learn || [];
  const todo = items.filter((x) => x.status === "todo"), done = items.filter((x) => x.status === "done");
  return `<div class="pp-h"><b>Что выучить для проекта</b><button class="link small" data-plearn-add>+ тема</button></div>
    ${todo.length ? todo.map((x) => `<div class="lr"><button class="ms-check" data-plearn-done="${esc(x.id)}" aria-label="Выучено"></button>
      <div class="grow"><div class="ms-title">${esc(x.topic)} <button class="chip ${x.kind === "practice" ? "accent" : ""}" data-plearn-kind="${esc(x.id)}" title="Теория ↔ практика">${x.kind === "practice" ? "практика" : "теория"}</button></div>${x.why ? `<div class="muted small">${esc(x.why)}</div>` : ""}
        ${(x.sources || []).length ? `<div class="small">${x.sources.map((s) => /^https?:/.test(s) ? `<a href="${esc(s)}" target="_blank" rel="noopener">${esc(s)}</a>` : esc(s)).join(" · ")}</div>` : ""}
        ${x.task_status && x.task_status !== "done" ? `<button class="pill small-pill" data-plearn-open="${esc(x.task_id)}">${icon("study")} Блок ${ddmm(x.task_date)} — в «Обучение»</button>` : `<button class="pill small-pill" data-plearn-start="${esc(x.id)}">${icon("play")} Учить сейчас</button>`}</div></div>`).join("")
      : `<div class="muted small">Тем нет. Спроси в чате: «что мне выучить для этого?» — Арвикс добавит сам.</div>`}
    ${done.length ? `<details style="margin-top:8px"><summary class="muted small">Выучено · ${done.length}</summary>${done.map((x) => `<div class="small">✓ ${esc(x.topic)}</div>`).join("")}</details>` : ""}
    <p class="muted small" style="margin-top:12px">«Учить сейчас» ставит учебный блок и открывает сессию в «Обучении»: план по минутам, окна (тест, доска, схема, видео), таймер и проверка. Теория — понять, практика — сделать руками.</p>
    <button class="pill small-pill" data-plearn-tab>${icon("study")} Все темы — в «Обучении»</button>`;
}

// --- действия ----------------------------------------------------------------------------------
function projectBack() {
  state.project = null; state.projNote = null;
  if (TG) { TG.BackButton.offClick(projectBack); TG.BackButton.hide(); }
  renderProjects(); window.scrollTo(0, 0);
}

async function openProject(id) {
  try {
    state.project = await api("project?id=" + encodeURIComponent(id));
    state.projNote = null;
    renderProjects(); if (!isWide()) window.scrollTo(0, 0);
  } catch (err) { toast(err.message); }
}

async function projectOp(op, body, msg) {
  const r = await api(`projects/${state.project.id}/${op}`, { json: body });
  state.project = r.project; notify("success");
  if (msg) toast(typeof msg === "function" ? msg(r) : msg);
  state.projects = await api("projects");
  renderProjects();
  return r;
}

async function projectSend(text) {
  text = String(text || "").trim();
  if (!text) return;
  const p = state.project;
  p.messages = [...(p.messages || []), { who: "me", text, at: new Date().toISOString() }];
  state.thinking = "думаю";
  renderProjects();
  try { await api(`projects/${p.id}/chat`, { json: { text } }); } catch (err) { toast(err.message); }
}

async function projectFiles(files) {
  const p = state.project;
  for (const f of files) {
    if (f.size > MAX_FILE) { toast(`«${f.name}» больше 20 МБ`); continue; }
    const caption = ($("#pc-text") && $("#pc-text").value.trim()) || "";
    try {
      await api(`projects/${p.id}/upload`, { body: f, headers: { "Content-Type": f.type || "application/octet-stream",
        "X-File-Name": encodeURIComponent(f.name), "X-Caption": encodeURIComponent(caption) } });
      if ($("#pc-text")) $("#pc-text").value = "";
      p.messages = [...(p.messages || []), { who: "me", text: "📎 " + f.name, at: new Date().toISOString() }];
      state.thinking = "смотрю файл"; renderProjects();
    } catch (err) { toast(err.message); }
  }
}

async function openProjNote(path) {
  try { const n = await api("note?path=" + encodeURIComponent(path)); state.projNote = { path: n.path, text: n.text, sha: n.sha, edit: false }; renderProjects(); }
  catch (err) { toast(err.message); }
}

async function openProjFile(path) {
  try {
    const res = await fetch("/api/file?path=" + encodeURIComponent(path), { headers: authHeaders() });
    if (!res.ok) throw new Error("Файл не открылся");
    window.open(URL.createObjectURL(await res.blob()), "_blank");
  } catch (err) { toast(err.message); }
}

function bindProjects() {
  const on = (sel, fn) => view.querySelectorAll(sel).forEach((el) => el.addEventListener("click", (e) => { haptic("soft"); fn(el, e); }));
  view.querySelectorAll("[data-proj]").forEach((el) => {
    el.addEventListener("click", () => { haptic(); openProject(el.dataset.proj); });
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") openProject(el.dataset.proj); });
  });
  on("[data-ppane]", (el) => { projLayout.pane = el.dataset.ppane; saveLayout(); renderProjects(); });
  on("[data-ptab]", (el) => { projLayout.tab = el.dataset.ptab; saveLayout(); renderProjects(); });
  on("[data-layout]", (el) => { projLayout[el.dataset.layout] = !projLayout[el.dataset.layout]; saveLayout(); renderProjects(); });
  on("[data-ask]", (el) => projectSend(el.dataset.ask));
  on("[data-proadmap]", async (el) => {
    try { await api("projects/roadmap", { json: { goal: el.dataset.proadmap } }); toast("Арвикс думает над целью — ответ придёт в чат: один проект или «проект не нужен»"); }
    catch (err) { toast(err.message); }
  });
  view.querySelectorAll("[data-pdrop]").forEach((el) => el.addEventListener("click", async (e) => {
    e.stopPropagation();  // кнопка внутри строки проекта: не открывать его
    haptic("soft");
    const id = el.dataset.pdrop;
    try {
      await api(`projects/${id}/status`, { json: { status: "dropped", reason: "Не нужен — убран из списка кнопкой ✕" } });
      if (state.project && state.project.id === id) state.project = null;
      state.projects = await api("projects"); notify("success"); toast("Убран. Вернуть — «Завершённые» → проект → «Вернуть в работу»"); renderProjects();
    } catch (err) { toast(err.message); }
  }));
  on("[data-pnote]", (el) => openProjNote(el.dataset.pnote));
  on("[data-pfile]", (el) => openProjFile(el.dataset.pfile));
  on("[data-pnote-close]", () => { state.projNote = null; renderProjects(); });
  on("[data-pnote-edit]", () => { state.projNote.edit = true; renderProjects(); setTimeout(() => $("#pn-edit") && $("#pn-edit").focus(), 30); });
  on("[data-pnote-cancel]", () => { state.projNote.edit = false; renderProjects(); });
  on("[data-pnote-save]", async () => {
    const n = state.projNote, text = $("#pn-edit").value;
    try { const r = await api("note", { json: { path: n.path, text, sha: n.sha } }); state.projNote = { path: r.path, text: r.text, sha: r.sha, edit: false }; toast("Сохранено в Obsidian"); renderProjects(); }
    catch (err) { if (err.status === 409) { toast("Заметку изменили — открыл свежую"); openProjNote(n.path); } else toast(err.message); }
  });
  on("[data-pnote-new]", async () => {
    const name = (prompt("Название заметки", "") || "").trim(); if (!name) return;
    try { const r = await api("note/new", { json: { dir: state.project.folder, name } }); await loadProjects(); state.projNote = { path: r.path, text: r.text, sha: r.sha, edit: true }; renderProjects(); }
    catch (err) { toast(err.message); }
  });
  on("[data-ms]", async (el) => {
    const m = state.project.milestones.find((x) => x.id === el.dataset.ms); if (!m) return;
    if (m.status !== "done" && !confirm(`Этап «${m.title}» пройден?\nКритерий: ${m.dod}`)) return;
    try { await projectOp("milestone", { milestone: m.id, status: m.status === "done" ? "open" : "done" }, m.status === "done" ? "Этап снова в работе" : "✓ Этап пройден"); }
    catch (err) { toast(err.message); }
  });
  on("[data-rdel]", async (el) => {
    if (!confirm("Убрать из проекта?")) return;
    try { await projectOp("resource", { resource: el.dataset.rdel, status: "removed" }, "Убрал"); } catch (err) { toast(err.message); }
  });
  on("[data-plearn-add]", async () => {
    const topic = (prompt("Что выучить? Например: asyncio, SQL JOIN, композиция кадра", "") || "").trim(); if (!topic) return;
    try { await projectOp("learn", { topic }, "+ тема"); } catch (err) { toast(err.message); }
  });
  on("[data-plearn-done]", async (el) => { try { await projectOp("learn", { item: el.dataset.plearnDone, status: "done" }, "✓ Выучено"); } catch (err) { toast(err.message); } });
  on("[data-plearn-start]", (el) => openStudySession({ item: el.dataset.plearnStart }));  // тема проекта → сессия в «Обучении» (D55)
  on("[data-plearn-open]", (el) => openStudySession({ task: el.dataset.plearnOpen }));
  on("[data-plearn-tab]", () => { studyUI.open = false; studyUI.task = null; setTab("study"); });
  on("[data-plearn-kind]", async (el) => {
    const x = (state.project.learn || []).find((i) => i.id === el.dataset.plearnKind); if (!x) return;
    try { await projectOp("learn", { item: x.id, kind: x.kind === "practice" ? "theory" : "practice" }); } catch (err) { toast(err.message); }
  });
  view.querySelectorAll("[data-pact]").forEach((el) => el.addEventListener("click", async () => {
    haptic();
    const act = el.dataset.pact;
    try {
      if (act === "new") openNewProjectSheet();
      else if (act === "back") projectBack();
      else if (act === "block") openBlockSheet();
      else if (act === "milestone") openMilestoneSheet();
      else if (act === "log") openLogSheet();
      else if (act === "menu") openProjectMenu();
    } catch (err) { toast(err.message); }
  }));
  if ($("#pn-go")) $("#pn-go").onclick = () => createProject($("#pn-text").value, $("#pn-goal") ? $("#pn-goal").value : "");
  const ta = $("#pc-text");
  if (ta) {
    const grow = () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 180) + "px"; };
    ta.addEventListener("input", grow); grow();
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && isWide()) { e.preventDefault(); const t = ta.value; ta.value = ""; projectSend(t); } });
    $("#pc-send").onclick = () => { const t = ta.value; ta.value = ""; projectSend(t); };
    $("#pc-file").onclick = () => $("#pc-input").click();
    $("#pc-input").onchange = (e) => { projectFiles([...e.target.files]); e.target.value = ""; };
  }
  // [[ссылки]] в заметке проекта: заметка из той же папки откроется тут же, остальные — поиском во вкладке «Заметки»
  view.querySelectorAll(".pn-view [data-wiki]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    const name = a.dataset.wiki.split("|")[0].split("#")[0].trim();
    const hit = (state.project.files || []).find((f) => f.note && (f.name === name || f.path.replace(/\.md$/, "").endsWith(name)));
    if (hit) openProjNote(hit.path); else { setTab("notes"); toast("Ищи «" + name + "» во вкладке «Заметки»"); }
  }));
  const pv = view.querySelector(".pn-view"); if (pv) hydrateAssets(pv);
  const div = $("#pw-div");
  if (div) div.addEventListener("pointerdown", (e) => {
    e.preventDefault(); div.setPointerCapture(e.pointerId);
    const grid = div.parentElement, right = grid.getBoundingClientRect().right;
    const move = (ev) => { projLayout.sideW = Math.round(Math.max(300, Math.min(right - ev.clientX, grid.clientWidth * 0.62))); grid.style.setProperty("--ps-w", projLayout.sideW + "px"); };
    const up = () => { div.removeEventListener("pointermove", move); div.removeEventListener("pointerup", up); saveLayout(); };
    div.addEventListener("pointermove", move); div.addEventListener("pointerup", up);
  });
}

async function createProject(text, goal) {
  text = String(text || "").trim();
  if (text.length < 3) { toast("Пара слов — что хочешь сделать"); return; }
  try {
    const r = await api("projects/new", { json: { text, goal: goal || null } });
    closeSheet(); notify("success");
    state.projects = await api("projects");
    state.project = await api("project?id=" + encodeURIComponent(r.project.id));
    state.thinking = "думаю"; projLayout.pane = "chat"; projLayout.tab = "plan"; saveLayout();
    renderProjects();
    toast(r.project.status === "active" ? "Арвикс заполняет проект…" : "В работе уже 3 проекта — этот пока отложен. Арвикс всё равно его разложит.");
  } catch (err) { toast(err.message); }
}

function openNewProjectSheet() {
  const P = state.projects;
  openSheet(`<h2>Новый проект</h2>
    <div class="field"><textarea id="ns-text" rows="5" placeholder="Что хочешь сделать и зачем? К какому сроку? Например: хочу снять серию роликов про подготовку к ОГЭ, чтобы научиться монтажу и найти единомышленников. До февраля."></textarea></div>
    ${(P.goals || []).length ? `<div class="field"><select id="ns-goal" class="input"><option value="">Цель — пусть решит Арвикс</option>${P.goals.map((g) => `<option value="${esc(g.id)}">${esc(g.title)}</option>`).join("")}</select></div>` : ""}
    <button class="btn primary" id="ns-go">${icon("send")} Начать</button>
    <p class="muted small">Дальше Арвикс сам: название, результат, этапы, что выучить, папка в Obsidian. Поправишь словами в чате проекта.</p>`, () => {
    setTimeout(() => $("#ns-text").focus(), 50);
    $("#ns-go").onclick = () => createProject($("#ns-text").value, $("#ns-goal") ? $("#ns-goal").value : "");
  });
}

function openProjectMenu() {
  const p = state.project, P = state.projects;
  openSheet(`<h2>${esc(p.title)}</h2>
    <div class="field"><label>Название</label><input id="pm-title" value="${esc(p.title)}"></div>
    <div class="field"><label>Результат — что будет в конце</label><textarea id="pm-exp" rows="2">${esc(p.expectation)}</textarea></div>
    <div class="field" style="display:flex;gap:8px"><div style="flex:1"><label>Срок</label><input id="pm-deadline" type="date" value="${esc(p.deadline || "")}"></div>
      <div style="flex:1"><label>Часов в неделю</label><input id="pm-weekly" type="number" min="0" max="40" step="0.5" value="${p.weekly_min ? p.weekly_min / 60 : ""}"></div></div>
    ${(P.goals || []).length ? `<div class="field"><label>Цель</label><select id="pm-goal" class="input"><option value="">— без цели —</option>${P.goals.map((g) => `<option value="${esc(g.id)}" ${p.goal_id === g.id ? "selected" : ""}>${esc(g.title)}</option>`).join("")}</select></div>` : ""}
    <button class="btn primary" id="pm-save">Сохранить</button>
    <div class="sheet-actions" style="margin-top:12px">
      ${p.status === "active" ? `<button class="btn" data-pst="paused">⏸ Отложить</button>` : p.group !== "closed" ? `<button class="btn" data-pst="active">▶ В работу</button>` : `<button class="btn" data-pst="active">↺ Вернуть в работу</button>`}
      ${p.group !== "closed" ? `<button class="btn" data-pst="done">✓ Завершить…</button>` : ""}
      ${p.goal_id ? `<div style="display:flex;gap:8px"><button class="btn" data-pmove="-1">↑ Раньше в роадмапе</button><button class="btn" data-pmove="1">↓ Позже</button></div>` : ""}
    </div>`, (root) => {
    $("#pm-save").onclick = async () => {
      const body = { title: $("#pm-title").value.trim(), expectation: $("#pm-exp").value.trim(), deadline: $("#pm-deadline").value || null,
        weekly_min: $("#pm-weekly").value === "" ? null : Math.round(+$("#pm-weekly").value * 60) };
      if ($("#pm-goal")) body.goal_id = $("#pm-goal").value;
      try { await projectOp("save", body, "Сохранил"); closeSheet(); } catch (err) { toast(err.message); }
    };
    root.querySelectorAll("[data-pst]").forEach((b) => b.addEventListener("click", async () => {
      const status = b.dataset.pst;
      let reason = "";
      if (status === "done") {
        reason = (prompt("Итог: что получилось, что нет и почему? (попадёт в заметку проекта)", "") || "").trim();
        if (!reason) return;
        if (!confirm("Результат достигнут?\nОК — да, «Отмена» — закрыть без результата")) {
          try { await projectOp("status", { status: "dropped", reason }, "Проект закрыт — итог записан"); closeSheet(); } catch (err) { toast(err.message); }
          return;
        }
      }
      try { await projectOp("status", { status, reason }, status === "active" ? "В работе" : status === "paused" ? "Отложен" : "Завершён 🎉"); closeSheet(); }
      catch (err) { toast(err.message); }
    }));
    root.querySelectorAll("[data-pmove]").forEach((b) => b.addEventListener("click", async () => {
      try { await projectOp("move", { step: +b.dataset.pmove }, "Порядок изменён"); } catch (err) { toast(err.message); }
    }));
  });
}

function openMilestoneSheet() {
  openSheet(`<h2>Новый этап</h2><p class="muted small">${esc(state.project.title)} · проще — попросить Арвикса в чате</p>
    <div class="field"><input id="ms-title" placeholder="Что сделать"></div>
    <div class="field"><label>Готово, когда…</label><textarea id="ms-dod" rows="2" placeholder="Проверяемо: ссылка, число, отзыв"></textarea></div>
    <button class="btn primary" id="ms-save">Добавить</button>`, () => {
    setTimeout(() => $("#ms-title").focus(), 50);
    $("#ms-save").onclick = async () => {
      try { await projectOp("milestone", { title: $("#ms-title").value.trim(), dod: $("#ms-dod").value.trim() }, "+ этап"); closeSheet(); }
      catch (err) { toast(err.message); }
    };
  });
}

function openBlockSheet() {
  const p = state.project, form = { minutes: "60", day: "today" };
  openSheet(`<h2>Блок в план</h2><p class="muted small">${esc(p.title)}${p.next ? " → " + esc(p.next.title) : ""}</p>
    <div class="field"><label>Сколько</label>${seg("minutes", ["30", "45", "60", "90", "120"], "60", (v) => hm(+v))}</div>
    <div class="field"><label>Когда</label><div style="display:flex;gap:8px">${seg("day", ["today", "tomorrow"], "today", (v) => (v === "today" ? "сегодня" : "завтра"))}
      <input id="bk-start" type="time" style="flex:1"></div></div>
    <button class="btn primary" id="bk-save">${icon("play")} Поставить</button>
    <p class="muted small">Время пустое — первое свободное окно. За 5 минут придёт напоминание, отчёт по блоку сам ляжет в журнал проекта.</p>`, (root) => {
    bindSeg(root, form);
    $("#bk-save").onclick = async () => {
      try {
        await projectOp("block", { minutes: +form.minutes, date: form.day, start: $("#bk-start").value || null },
          (r) => `+ ${r.task.title} · ${r.task.start}` + (r.warnings && r.warnings.length ? "\n⚠️ " + r.warnings.join("\n⚠️ ") : ""));
        closeSheet(); state.data = await api("state");
      } catch (err) { toast(err.message); }
    };
  });
}

function openLogSheet() {
  const kinds = state.projects.log_kinds, form = { kind: "update" };
  openSheet(`<h2>Запись в журнал</h2><p class="muted small">${esc(state.project.title)} · попадёт в «Журнал» в Obsidian</p>
    <div class="field">${seg("kind", Object.keys(kinds), "update", (v) => LOG_ICON[v] + " " + kinds[v])}</div>
    <div class="field"><textarea id="lg-text" rows="3" placeholder="Что сделал, что решил, чему научился, что мешает"></textarea></div>
    <button class="btn primary" id="lg-save">Записать</button>`, (root) => {
    bindSeg(root, form);
    setTimeout(() => $("#lg-text").focus(), 50);
    $("#lg-save").onclick = async () => {
      try { await projectOp("log", { kind: form.kind, text: $("#lg-text").value.trim() }, "Записал"); closeSheet(); }
      catch (err) { toast(err.message); }
    };
  });
}

// --- Обучение (D55, D60) -----------------------------------------------------------------------------
/* Учебная сессия = учебный блок + его урок, разложенный по этапам (D60): диагностика → разбор → практика →
 * работа над ошибками → проверка. На экране — один этап: что делать сейчас, его окна и «Дальше». Уровень по
 * диагностике, проверку задач и сбор ошибок считает код; Арвикс наполняет этапы и видит сессию (блок <study>).
 * Очередь тем — общая с «Проектами». Повторения тем по интервалам — карточка «Повторение» в обзоре. */
const STUDY_LAYOUT_KEY = "arvix_studylayout";
const studyLayout = (() => {
  try { return { pane: "desk", ...JSON.parse(localStorage.getItem(STUDY_LAYOUT_KEY) || "{}") }; } catch (_) { return { pane: "desk" }; }
})();
const saveStudyLayout = () => { try { localStorage.setItem(STUDY_LAYOUT_KEY, JSON.stringify(studyLayout)); } catch (_) { /* приватный режим */ } };
const studyUI = { open: false, task: null, quiz: {}, notes: {}, twin: {}, deskKey: "", auto: false, view: null, review: false, rq: {}, busy: "", lastStage: "", peek: false };
const KIND_RU = { theory: "теория", practice: "практика" };
const STAGE_ICON = { diag: "1", learn: "2", practice: "3", fix: "4", check: "5" };

async function loadStudy() {
  state.study = await api("study" + (studyUI.task ? "?task=" + encodeURIComponent(studyUI.task) : ""));
  const s = state.study.session;
  // Вход во вкладку при идущем уроке — сразу на рабочий стол. Только при входе: ← должен оставаться ←.
  if (studyUI.auto && !state.study.gentle && s && s.live) studyUI.open = true;
  studyUI.auto = false;
  // Стол держится за свою задачу: после проверки урок уходит из памяти бота, а итог должен остаться на экране
  if (studyUI.open && s && !studyUI.task) studyUI.task = s.task.id;
}

/* Перерисовка по живому потоку не должна перезагружать видео и сбивать ответы теста: если на рабочем
 * столе ничего не поменялось (поменялся только чат), обновляется только лента чата. */
function deskKey(s) {
  if (!s) return "";
  const { messages, ...rest } = s;
  return JSON.stringify(rest) + "|" + (studyUI.view || "");
}

function renderStudy(opts = {}) {
  const S = state.study;
  if (!S) { view.innerHTML = `<div class="empty">Загружаю…</div>`; return; }
  if (S.gentle) { view.innerHTML = `<div class="card note-card">${esc(S.note)}</div>`; return; }
  if (studyUI.review) { renderReview(); return; }
  const s = S.session;
  if (!(studyUI.open && s)) { studyUI.deskKey = ""; view.innerHTML = studyOverviewHtml(S); bindStudy(); return; }
  const key = deskKey(s);
  if (opts.live && key === studyUI.deskKey && $("#sc-thread")) { drawStudyThread(); return; }
  const keep = captureStudyComposer();
  const deskEl = $(".sw-desk"), deskTop = deskEl ? deskEl.scrollTop : 0;  // правка заметки или ответ теста не уводят стол наверх
  const sameStage = studyUI.lastStage === `${s.task.id}:${shownStage(s)}`;  // другой этап — стол сверху
  studyUI.lastStage = `${s.task.id}:${shownStage(s)}`;
  studyUI.deskKey = key;
  const chat = s.live || (s.messages || []).length > 0;  // закрытая сессия — история: стол и её нить, только чтение
  const pane = !chat ? "desk" : isWide() ? "both" : studyLayout.pane;
  view.innerHTML = `<div class="sw${isWide() && chat ? " wide" : ""}">
    <section class="sw-desk">${studyHeadHtml(s)}
      ${isWide() || !chat ? "" : `<div class="seg pm-tabs">${[["desk", "Стол"], ["chat", "Чат с Арвиксом"]].map(([k, l]) =>
        `<button type="button" data-spane="${k}" class="${pane === k ? "on" : ""}">${l}</button>`).join("")}</div>`}
      ${pane !== "chat" ? stepperHtml(s) + `<div class="sw-stage">${stageHtml(s)}</div>` : ""}</section>
    ${pane !== "desk" ? `<aside class="sw-chat">${studyChatHtml(s)}</aside>` : ""}</div>`;
  bindStudy();
  restoreStudyComposer(keep);
  if (sameStage && deskTop && $(".sw-desk")) $(".sw-desk").scrollTop = deskTop;
  const stp = $(".stp"), on = $(".stp-i.on");  // на телефоне полоса этапов шире экрана: текущий этап — в середину
  if (stp && on && stp.scrollWidth > stp.clientWidth) stp.scrollLeft = on.offsetLeft - (stp.clientWidth - on.clientWidth) / 2;
  drawStudyThread();
  tickStudy();
}

const shownStage = (s) => (s.live ? s.stage : studyUI.view || s.stage);

// --- обзор: повторение · сегодня · очередь · пройденное ----------------------------------------
function studyOverviewHtml(S) {
  let html = `<div class="so">`;
  const s = S.session;
  if (s && s.live) {
    const st = s.stages.find((x) => x.id === s.stage);
    html += `<div class="card so-live" data-sresume role="button" tabindex="0"><h3>Сессия ${s.started ? "идёт" : "готова"}</h3>
      <div class="so-row"><div class="grow"><b>${esc(s.topic)}</b><div class="muted small">${esc(s.task.title)} · ${hm(s.task.duration_min)} · этап ${STAGE_ICON[s.stage]}/5 — ${esc(st ? st.name : "")}</div></div>
      <button class="pill primary">${icon("chevron")} Открыть</button></div></div>`;
  }
  html += reviewCardHtml(S.review);
  html += `<div class="section-title first"><span>Сегодня</span><span>${S.blocks.length ? S.blocks.length + " учебн." : ""}</span></div>`;
  html += S.blocks.length ? S.blocks.map((t) => `<div class="task ${esc(t.status)}"><div class="time"><b>${esc(t.start || "—")}</b>${esc(t.end || "")}</div>
      <div class="body"><div class="title">${esc(t.title)}</div><div class="meta"><span class="chip">${hm(t.duration_min)}</span>
        ${t.score != null ? `<span class="chip ${t.score >= 70 ? "green" : "yellow"}">проверка ${t.score}%</span>` : t.status === "done" ? `<span class="chip green">✓</span>` : ""}
        ${t.live ? `<span class="chip accent">сессия</span>` : ""}</div></div>
      <div class="acts"><button class="pill small-pill${t.open ? " primary" : ""}" data-sopen="${esc(t.id)}">${t.open ? (t.lesson ? "Открыть" : "Начать сессию") : "Посмотреть"}</button></div></div>`).join("")
    : `<div class="muted small so-hint">Учебных блоков сегодня нет. Возьми тему из очереди — Арвикс поставит блок в свободное окно и подготовит сессию.</div>`;
  const todo = S.queue.filter((x) => x.status === "todo"), done = S.queue.filter((x) => x.status === "done");
  html += `<div class="section-title"><span>Что выучить</span><button class="link small" data-slearn-add>+ тема</button></div>`;
  if (!todo.length) html += `<div class="muted small so-hint">Очередь пустая. Темы приходят из проектов («что мне выучить для этого?») или добавь сам.</div>`;
  const groups = new Map();
  for (const x of todo) { const g = x.project || x.goal || "Без проекта"; if (!groups.has(g)) groups.set(g, []); groups.get(g).push(x); }
  for (const [g, items] of groups) {
    html += `<div class="pl-ghead">${esc(g)}</div>` + items.map((x) => `<div class="card so-item">
      <div class="grow"><div class="so-top"><b>${esc(x.topic)}</b><button class="chip ${x.kind === "practice" ? "accent" : ""}" data-skind="${esc(x.id)}" title="Теория ↔ практика">${esc(x.kind_ru)}</button></div>
        ${x.why ? `<div class="muted small">${esc(x.why)}</div>` : ""}
        ${(x.sources || []).length ? `<div class="small">${x.sources.map((src) => /^https?:/.test(src) ? `<a href="${esc(src)}" target="_blank" rel="noopener">${esc(src)}</a>` : esc(src)).join(" · ")}</div>` : ""}
        <div class="pills">${x.task_status && x.task_status !== "done" && x.task_id ? `<button class="pill small-pill primary" data-sopen="${esc(x.task_id)}">${icon("play")} Блок ${ddmm(x.task_date)} — открыть</button>`
          : `<button class="pill small-pill primary" data-sitem="${esc(x.id)}">${icon("play")} Учить сейчас</button>`}
          <button class="pill small-pill" data-sdone="${esc(x.id)}">${icon("check")} Уже знаю</button></div></div></div>`).join("");
  }
  if (done.length) html += `<details class="card"><summary class="muted small">Выучено · ${done.length}</summary>${done.map((x) => `<div class="small">✓ ${esc(x.topic)}${x.project ? ` <span class="muted">· ${esc(x.project)}</span>` : ""}</div>`).join("")}</details>`;
  if (S.history.length) {
    html += `<div class="section-title"><span>Пройдено</span><span>${S.subjects.map((x) => `${esc(x.subject)} ${x.lessons}${x.avg != null ? " · " + x.avg + "%" : ""}`).join(" · ")}</span></div>`;
    html += S.history.map((x) => `<div class="card so-hist" data-shist="${esc(x.task_id)}" role="button" tabindex="0"><div class="so-row"><div class="grow">
        <b>${esc(x.topic)}</b><div class="muted small">${ddmm(x.date)} · ${esc(x.subject)}${x.panels ? ` · окон ${x.panels}` : ""}</div></div>
        <span class="chip ${x.score >= 70 ? "green" : x.score != null ? "yellow" : ""}">${x.score != null ? x.score + "%" : x.checked ? "без оценки" : "без проверки"}</span></div>
      ${x.gaps.length ? `<div class="small so-gaps">Пробелы: ${x.gaps.map(esc).join("; ")}</div>` : ""}</div>`).join("");
  }
  const R = S.review || {};
  const all = [...(R.due || []), ...(R.upcoming || [])];
  if (all.length) {
    html += `<details class="card so-revlist"><summary class="muted small">Темы на повторении · ${all.length}${R.done ? ` · закреплено ${R.done}` : ""}</summary>
      ${all.map((r) => `<div class="so-row small"><div class="grow">${esc(r.topic)} <span class="muted">· шаг ${Math.min(r.step + 1, r.steps)}/${r.steps} · ${r.due ? dueText(r.due) : ""}</span></div>
        <button class="icon-btn sm" data-srevdrop="${esc(r.id)}" aria-label="Убрать тему из повторений">${icon("x")}</button></div>`).join("")}</details>`;
  }
  return html + `</div>`;
}

function dueText(iso) {
  const today = state.data && state.data.date ? state.data.date : new Date().toISOString().slice(0, 10);
  const n = Math.round((new Date(iso) - new Date(today)) / 86400000);
  return n <= 0 ? "сегодня" : n === 1 ? "завтра" : `через ${n} дн. (${ddmm(iso)})`;
}

function reviewCardHtml(R) {
  if (!R) return "";
  const q = R.quiz;
  if (q && q.done) {
    return `<div class="card so-rev done"><h3>${icon("checks")} Повторение сделано</h3>
      ${q.by_review.map((r) => `<div class="small">${esc(r.topic)} — <b>${r.pct}%</b> · ${r.status === "done" ? "тема закреплена" : "дальше " + dueText(r.due)}</div>`).join("")}
      ${R.due.length ? `<button class="pill small-pill primary" data-srev>Ещё ${R.due.length} ${R.due.length === 1 ? "тема" : "темы"}</button>` : ""}
      <button class="pill small-pill" data-srevopen>Разбор ответов</button></div>`;
  }
  if (!R.due.length && !q) return "";
  const n = q ? new Set(q.items.map((x) => x.review)).size : Math.min(R.due.length, R.per_quiz);
  const names = q ? [...new Set(q.items.map((x) => x.topic))] : R.due.slice(0, R.per_quiz).map((r) => r.topic);
  return `<div class="card so-rev"><h3>🔁 Повторение · ${n} ${n === 1 ? "тема" : "темы"} · ≈${Math.max(3, n * 3)} мин</h3>
    <div class="muted small">Вспомнить сейчас — помнить к экзамену: тема возвращается через 1, 3, 7, 16 и 35 дней, задачи с новыми числами.</div>
    <div class="so-revtopics">${names.map((t) => `<span class="chip">${esc(t)}</span>`).join("")}${R.due.length > R.per_quiz && !q ? `<span class="muted small">и ещё ${R.due.length - R.per_quiz}</span>` : ""}</div>
    <button class="pill primary" data-srev ${studyUI.busy === "review" ? "disabled" : ""}>${studyUI.busy === "review" ? "Арвикс собирает задачи…" : q ? "Продолжить" : `${icon("play")} Начать`}</button></div>`;
}

// --- рабочий стол: шапка, этапы, этап ----------------------------------------------------------
function studyHeadHtml(s) {
  const chips = [`<span class="chip">${hm(s.task.duration_min)}</span>`];
  if (s.item) chips.push(`<span class="chip ${s.item.kind === "practice" ? "accent" : ""}">${KIND_RU[s.item.kind] || ""}</span>`);
  if (s.project) chips.push(`<span class="chip">→ ${esc(s.project.title)}</span>`);
  if (s.roadmap_node) chips.push(`<span class="chip">${esc(s.roadmap_node)}</span>`);
  if (s.result) chips.push(`<span class="chip ${s.result.score >= 70 ? "green" : "yellow"}">проверка ${s.result.score != null ? s.result.score + "%" : "—"}</span>`);
  let act = "";
  if (s.live && s.focus) act = `<div class="sw-timer" id="sw-timer" data-until="${esc(s.focus.until)}" data-paused="${esc(s.focus.paused_at || "")}"><b id="sw-left">--:--</b>
      ${s.focus.paused_at ? `<button class="icon-btn sm go" data-sfocus="resume" aria-label="Дальше">${icon("play")}</button>` : `<button class="icon-btn sm" data-sfocus="pause" aria-label="Пауза">${icon("pause")}</button>`}</div>`;
  else if (s.live && s.task.open && !s.started) act = `<button class="pill primary small-pill" data-sgo title="Таймер на весь блок; он пойдёт и сам, когда ответишь на задачи">${icon("play")} Начать · ${hm(s.task.duration_min)}</button>`;
  return `<div class="ph"><button class="icon-btn sm" data-sback aria-label="К разделу">${icon("back")}</button>
    <div class="grow ph-text"><div class="ph-title">${esc(s.topic)}</div><div class="muted small">${esc(s.task.title)}</div><div class="meta">${chips.join("")}</div></div>
    <div class="ph-acts">${act}</div></div>`;
}

function stepperHtml(s) {
  const cur = shownStage(s);
  const elapsed = s.started ? (Date.now() - new Date(s.started).getTime()) / 60000 : -1;
  return `<nav class="stp" aria-label="Этапы сессии">${s.stages.map((st, i) => {
    const timer = s.started && st.from != null && elapsed >= st.from && elapsed < st.to;
    const badge = st.id === "fix" && st.errors ? `<span class="stp-b">${st.errors}</span>` : "";
    return `<button type="button" class="stp-i${st.id === cur ? " on" : ""}${st.done ? " done" : ""}" data-sstage="${st.id}" aria-current="${st.id === cur ? "step" : "false"}">
      <span class="stp-n">${st.done ? icon("check") : i + 1}</span><span class="stp-t">${esc(st.short || st.name)}${badge}</span>
      ${st.from != null ? `<span class="stp-m">${timer ? "⏱ " : ""}${st.from}–${st.to}</span>` : ""}</button>`;
  }).join("")}</nav>`;
}

function stageHtml(s) {
  const cur = shownStage(s);
  const st = s.stages.find((x) => x.id === cur) || s.stages[0];
  const i = s.stages.indexOf(st);
  let html = "";
  if (!s.prepared && s.live === false && s.task.open) {  // голова собирает этапы — минуту-две; пустых этапов не показываем
    return `<div class="sp sg"><div class="sg-h"><b>Арвикс готовит сессию</b><span class="muted small">1–3 мин</span></div>
      <div class="sg-goal">Смотрит роадмап, твои заметки и прошлые ошибки, подбирает задачи диагностики и практики, разбор и видео.</div>
      <div class="sg-step">Пока ждёшь — возьми тетрадь и с пустого листа выпиши всё, что помнишь по теме. Это и есть разминка перед диагностикой.</div></div>`;
  }
  html += `<div class="sp sg"><div class="sg-h"><b>${i + 1} · ${esc(st.name)}</b>${st.from != null ? `<span class="muted small">${st.from}–${st.to} мин</span>` : ""}</div>
    <div class="sg-goal">${esc(st.goal)}</div>
    ${st.steps.map((x) => `<div class="sg-step">${esc(x.step)}${x.tool ? ` <span class="muted">· ${esc(x.tool)}</span>` : ""}</div>`).join("")}
    ${s.fallback && cur === "diag" ? `<div class="muted small">Голова была недоступна — этапы общие, задачи бери из учебника и банка ФИПИ.</div>` : ""}</div>`;
  const mine = s.panels.filter((p) => p.stage === cur);
  if (cur === "diag") {
    html += mine.map((p) => panelHtml(p, s)).join("");
    if (!mine.some((p) => p.type === "quiz")) html += `<div class="sp muted small">Задач диагностики нет — вспомни тему на бумаге с пустого листа и отметь, где споткнулся.</div>`;
    if (s.route) html += routeHtml(s.route);
  } else if (cur === "learn" && s.live && !studyUI.peek && s.panels.some((p) => p.stage === "diag" && p.type === "quiz" && !p.done)) {
    // Разбор строится по ошибкам диагностики: подсмотреть его до задач — сломать диагностику самому себе
    html += `<div class="sp"><div>Разбор откроется после диагностики — он строится по твоим ошибкам, лишнего читать не придётся.</div>
      <div class="pills"><button class="pill small-pill primary" data-sstage="diag">К диагностике</button><button class="pill small-pill" data-speek>Открыть разбор всё равно</button></div></div>`;
  } else if (cur === "learn") {
    if (s.route) html += routeHtml(s.route);
    const weak = new Set((s.route && s.route.weak) || []);
    const texts = mine.filter((p) => p.type === "text");
    const known = s.route ? texts.filter((p) => p.skill && !weak.has(p.skill)) : [];
    html += texts.filter((p) => !known.includes(p)).map((p) => panelHtml(p, s)).join("");
    html += mine.filter((p) => p.type !== "text").map((p) => panelHtml(p, s)).join("");
    if (known.length) html += `<details class="sp sp-known"><summary><b>Это ты уже умеешь</b> <span class="muted small">· ${known.map((p) => esc(p.skill)).join(", ")} — открыть разбор</span></summary>${known.map((p) => panelHtml(p, s)).join("")}</details>`;
    const notePath = s.note || "";
    if (notePath && !s.panels.some((p) => p.type === "note" && p.path === notePath)) html += panelHtml({ id: "lesson-note", type: "note", title: "Заметка своими словами", path: notePath, by: "arvix", fixed: true }, s);
    if (s.sources.length) html += panelHtml({ id: "lesson-sources", type: "sources", title: "Источники", list: s.sources, fixed: true }, s);
    if (s.task.open) html += `<div class="sp sp-add"><div class="muted small">Нужно ещё — спроси в чате: пример, чертёж, схему, другое видео. Свою ссылку на видео можно добавить и самому.</div>
      <div class="pills"><button class="pill small-pill" data-sadd="video">+ Видео по ссылке</button></div></div>`;
  } else if (cur === "practice") {
    html += mine.map((p) => panelHtml(p, s)).join("");
    if (!mine.some((p) => p.type === "quiz")) html += `<div class="sp muted small">Задач в приложении нет — решай по плану этапа выше. Нужны задачи здесь — попроси в чате: «дай 5 задач».</div>`;
  } else if (cur === "fix") {
    html += fixHtml(s);
    html += mine.map((p) => panelHtml(p, s)).join("");
  } else if (cur === "check") {
    html += checkHtml(s);
    html += mine.map((p) => panelHtml(p, s)).join("");
  }
  html += nextHtml(s, cur);
  return html;
}

function routeHtml(r) {
  return `<div class="sp sg-route lv-${esc(r.level)}"><div class="sp-h"><b>${esc(r.label)} · ${r.right} из ${r.total}</b><span class="chip">${r.pct}%</span></div>
    <div class="small">${esc(r.advice)}</div>
    ${r.strong.length ? `<div class="small muted">Умеешь: ${r.strong.map(esc).join(", ")}</div>` : ""}</div>`;
}

function nextHtml(s, cur) {
  if (!s.live) return "";
  const order = s.stages.map((x) => x.id), i = order.indexOf(cur);
  if (i >= order.length - 1) return "";
  let target = order[i + 1], extra = "";
  if (cur === "diag" && s.route && s.route.next === "practice") {
    target = "practice";
    extra = `<button class="pill small-pill" data-sstage="learn">Всё равно разбор</button>`;
  }
  const name = s.stages.find((x) => x.id === target).name;
  const errs = target === "fix" ? s.errors.filter((e) => !e.closed).length : 0;
  return `<div class="sg-next">${extra}<button class="btn primary" data-sstage="${target}">Дальше: ${esc(name)}${errs ? ` (${errs})` : ""} ${icon("chevron")}</button></div>`;
}

// --- работа над ошибками: причина, решение, похожая задача — проверяет код ----------------------
function fixHtml(s) {
  const errs = s.errors || [];
  const open = s.panels.filter((p) => p.type === "quiz" && !p.done && (p.stage === "diag" || p.stage === "practice"));
  let html = "";
  if (open.length) html += `<div class="sp small muted">Не отвечены: ${open.map((p) => esc(p.title)).join(", ")} — их ошибки появятся здесь после ответа.</div>`;
  if (!errs.length) return html + `<div class="sp"><b>Ошибок нет.</b> <span class="muted small">Иди к проверке — или попроси в чате задачи посложнее.</span></div>`;
  const left = errs.filter((e) => !e.closed).length;
  html += `<div class="sp small"><b>${errs.length - left} из ${errs.length} закрыто.</b> <span class="muted">Незакрытые уйдут в повторение темы — Арвикс вернёт их через день.</span></div>`;
  return html + errs.map((e) => {
    const kinds = Object.entries(s.error_kinds).map(([k, label]) => `<button type="button" class="chip${e.kind === k ? " accent" : ""}" data-sfixkind="${k}" data-key="${esc(e.key)}"${s.live ? "" : " disabled"}>${esc(label)}</button>`).join("");
    let twin = "";
    if (e.twin && !e.twin.done) {
      const v = studyUI.twin[e.key];
      const input = e.twin.options ? `<div class="sq-opts">${e.twin.options.map((o, j) => `<button type="button" class="sq-opt${v === j ? " on" : ""}" data-stwin="${esc(e.key)}" data-j="${j}">${esc(o)}</button>`).join("")}</div>`
        : `<input class="sq-in" data-stwinin="${esc(e.key)}" value="${esc(v ?? "")}" placeholder="Ответ" autocomplete="off">`;
      twin = `<div class="fx-twin"><div class="small"><b>Похожая задача — реши сам:</b></div><div>${esc(e.twin.q)}</div>${input}
        ${s.live ? `<button class="pill small-pill primary" data-stwinok="${esc(e.key)}">Проверить</button>` : ""}</div>`;
    } else if (e.twin) {
      twin = `<div class="fx-twin ${e.twin.ok ? "ok" : "bad"}"><div class="small"><b>${e.twin.ok ? "✓ Похожую решил" : "✗ Похожая — тоже ошибка"}</b></div><div class="small">${esc(e.twin.q)}</div>
        <div class="small">Твой ответ: ${esc(e.twin.given)}${e.twin.ok ? "" : ` · верно: <b>${esc(e.twin.right)}</b>`}</div>${e.twin.why ? `<div class="small muted">${esc(e.twin.why)}</div>` : ""}</div>`;
    }
    const tail = e.closed ? "" : s.live ? `<div class="pills">${!e.twin || e.twin.done ? `<button class="pill small-pill" data-sask="Дай ещё похожую задачу на: ${esc(e.q.slice(0, 120))}">Ещё похожую — в чате</button>` : ""}
        <button class="pill small-pill" data-sfixdone="${esc(e.key)}">Разобрался</button></div>` : "";
    return `<div class="sp fx${e.closed ? " closed" : ""}"><div class="fx-h"><span class="chip">${e.stage === "diag" ? "диагностика" : e.stage === "practice" ? "практика" : "тест"}</span>
        ${e.skill ? `<span class="chip">${esc(e.skill)}</span>` : ""}<span class="grow"></span>${e.closed ? `<span class="chip green">${e.self ? "разобрался" : "закрыта"}</span>` : ""}</div>
      <div class="fx-q">${esc(e.q)}</div>
      <div class="small"><span class="fx-bad">${e.unknown ? "Не знал" : "Твой ответ: " + esc(e.given)}</span> · верно: <b class="fx-good">${esc(e.right)}</b></div>
      ${e.why ? `<div class="small fx-why">${esc(e.why)}</div>` : ""}
      ${e.closed && !e.kind ? "" : `<div class="fx-kinds"><span class="muted small">Почему:</span>${kinds}</div>`}
      ${twin}${tail}</div>`;
  }).join("");
}

// --- проверка: вопросы конца блока, ответ и есть отчёт ------------------------------------------
function checkHtml(s) {
  if (s.result) {
    return `<div class="sp"><div class="sp-h"><b>Итог проверки</b><span class="chip ${s.result.score >= 70 ? "green" : "yellow"}">${s.result.score != null ? s.result.score + "%" : "без оценки"}</span></div>
      ${(s.result.gaps || []).length ? `<div class="small"><b>Пробелы — в карточки Anki и журнал ошибок:</b><ul>${s.result.gaps.map((g) => `<li>${esc(g)}</li>`).join("")}</ul></div>` : ""}
      ${s.result.next_step ? `<div class="small"><b>Следующий блок:</b> ${esc(s.result.next_step)}</div>` : ""}
      ${s.review ? `<div class="small"><b>Повторение темы:</b> ${s.review.status === "done" ? "закреплена" : dueText(s.review.due)} — 2 задачи в «Обучении».</div>` : ""}</div>`;
  }
  if (s.check.length) {
    return `<div class="sp sp-check"><div class="sp-h"><b>Проверка — ${s.check.length} вопроса</b></div>
      <ol class="small">${s.check.map((q) => `<li>${esc(q)}</li>`).join("")}</ol>
      <textarea id="sk-text" rows="4" placeholder="Ответь одним сообщением, по номерам. Не знаешь — так и напиши: это тоже ответ."></textarea>
      <button class="btn primary" data-skheck>${icon("send")} Отправить ответы</button>
      <div class="muted small">Ответ и есть отчёт: Арвикс оценит по эталонам, закроет блок и поставит повторение темы.</div></div>`;
  }
  if (!s.live || !s.task.open) return `<div class="sp muted small">Проверки у этой сессии не было.</div>`;
  const left = (s.errors || []).filter((e) => !e.closed).length;
  return `<div class="sp"><div class="small">Вопросы проверки придут сюда. Ответишь — блок закрыт: ${s.focus ? "таймер остановится, прошедшие минуты запишутся." : "время блока засчитается."}</div>
    ${left ? `<div class="small muted">Незакрытых ошибок: ${left} — они уйдут в повторение темы.</div>` : ""}
    <button class="btn primary" data-scheck>${icon("check")} Начать проверку</button></div>`;
}

function panelHtml(p, s) {
  const by = p.by === "me" ? `<span class="chip">ты</span>` : "";
  const live = s && s.live;
  // Задачи этапа не скрываются: их ответы — уровень и ошибки сессии; скрыть можно объяснение, видео, чертёж
  const close = p.fixed || !live || p.type === "quiz" ? "" : `<button class="icon-btn sm" data-shide="${esc(p.id)}" aria-label="Скрыть окно">${icon("x")}</button>`;
  return `<div class="sp sp-${esc(p.type)}" data-panel="${esc(p.id)}"><div class="sp-h"><b>${esc(p.title)}</b><span class="grow"></span>${by}${close}</div>${panelBody(p, live)}</div>`;
}

function panelBody(p, live) {
  if (p.type === "quiz") return quizHtml(p, live);
  if (p.type === "board") return boardSvg(p);
  if (p.type === "diagram") return diagramSvg(p);
  if (p.type === "text") return `<div class="obs">${obsidian(p.text).html}</div>`;
  if (p.type === "sources") return `<ol class="small sp-src">${p.list.map((x) => `<li>${/^https?:\/\//.test(x) ? `<a href="${esc(x)}" target="_blank" rel="noopener">${esc(x)}</a>` : esc(x)}</li>`).join("")}</ol>`;
  if (p.type === "video") return videoBody(p);
  if (p.type === "note") return noteBody(p);
  return "";
}

/* Видео: ролики нашёл код (RuTube и YouTube) — список, плеер у выбранного; ссылку человека — плеером или ссылкой. */
function videoBody(p) {
  const list = p.results || [];
  const pick = studyUI.quiz["v:" + p.id] ?? 0;
  const cur = list[pick] || (p.embed ? { embed: p.embed, url: p.url, title: p.title } : null);
  let body = "";
  if (cur && cur.embed) body += `<div class="sp-player"><iframe src="${esc(cur.embed)}" title="${esc(cur.title || p.title)}" loading="lazy" allow="encrypted-media; picture-in-picture; fullscreen" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe></div>`;
  else if (p.url) body += `<a class="pill small-pill" href="${esc(p.url)}" target="_blank" rel="noopener">Открыть видео</a> <span class="muted small">${esc(p.url)}</span>`;
  if (list.length) {
    body += `<div class="vd-list">${list.map((v, j) => `<button type="button" class="vd${j === pick ? " on" : ""}" data-svid="${esc(p.id)}" data-j="${j}">
      <span class="vd-site ${esc(v.site)}">${v.site === "rutube" ? "RuTube" : v.site === "youtube" ? "YouTube" : esc(v.site)}</span>
      <span class="vd-t">${esc(v.title)}</span><span class="muted small">${esc(v.channel)}${v.minutes ? " · " + v.minutes + " мин" : ""}</span></button>`).join("")}</div>
      ${cur && cur.url ? `<a class="small muted" href="${esc(cur.url)}" target="_blank" rel="noopener">Открыть на ${cur.site === "rutube" ? "RuTube" : "YouTube"} ↗</a>` : ""}`;
  } else if (!p.url && p.search) {
    body += `<a class="pill small-pill" href="${esc(p.search)}" target="_blank" rel="noopener">Найти: «${esc(p.query)}»</a><div class="muted small">Поиск сейчас не ответил — открой ссылку или пришли в чат свою, Арвикс поставит видео сюда.</div>`;
  }
  return body + (p.ask ? `<div class="small sp-ask">После просмотра: <b>${esc(p.ask)}</b></div>` : "");
}

// --- тест: варианты и короткий ответ проверяет код, открытые — Арвикс на проверке блока ------------
function quizHtml(p, live = true) {
  const sel = studyUI.quiz[p.id] || (studyUI.quiz[p.id] = {});
  const qs = p.questions.map((q, i) => {
    if (p.done) {
      const mark = q.open ? "•" : q.ok ? "✓" : "✗";
      let opts;
      if (q.open) opts = `<div class="small">Твой ответ: ${esc(q.given_text || "—")}</div><div class="small muted">Эталон: ${esc(q.a || "")}</div>`;
      else if (q.options) opts = `<div class="sq-opts">${q.options.map((o, j) => `<span class="sq-opt${j === q.answer ? " right" : ""}${j === q.given && j !== q.answer ? " wrong" : ""}">${esc(o)}</span>`).join("")}</div>`
        + (q.unknown ? `<div class="small muted">Отметил «не знаю»</div>` : "");
      else opts = `<div class="small">${q.unknown ? "Не знал" : `Твой ответ: <span class="${q.ok ? "fx-good" : "fx-bad"}">${esc(q.given_text)}</span>`}${q.ok ? "" : ` · верно: <b class="fx-good">${esc(q.right)}</b>`}</div>`;
      return `<div class="sq ${q.open ? "" : q.ok ? "ok" : "bad"}"><div><b>${mark}</b> ${esc(q.q)}</div>${opts}${q.why ? `<div class="small muted sq-why">${esc(q.why)}</div>` : ""}</div>`;
    }
    const unk = sel[i] === "?";
    let body;
    if (q.open) body = `<textarea class="sq-text" data-sq="${esc(p.id)}" data-i="${i}" rows="2" placeholder="Своими словами"${unk ? " disabled" : ""}>${esc(unk ? "" : sel[i] || "")}</textarea>`;
    else if (q.options) body = `<div class="sq-opts">${q.options.map((o, j) => `<button type="button" class="sq-opt${sel[i] === j ? " on" : ""}" data-sq="${esc(p.id)}" data-i="${i}" data-j="${j}">${esc(o)}</button>`).join("")}</div>`;
    else body = `<input class="sq-in" data-sq="${esc(p.id)}" data-i="${i}" value="${esc(unk ? "" : sel[i] ?? "")}" placeholder="Ответ — число или слово" autocomplete="off" enterkeyhint="next"${unk ? " disabled" : ""}>`;
    const meta = [q.skill ? esc(q.skill) : "", q.level ? ["", "простая", "средняя", "сложная"][q.level] : ""].filter(Boolean).join(" · ");
    return `<div class="sq${unk ? " unk" : ""}"><div>${i + 1}. ${esc(q.q)}${meta ? ` <span class="muted small">· ${meta}</span>` : ""}</div>${body}
      <button type="button" class="chip sq-unk${unk ? " accent" : ""}" data-sunk="${esc(p.id)}" data-i="${i}">Не знаю</button></div>`;
  }).join("");
  if (p.done) return qs + `<div class="small">${p.score_pct != null ? `<b>${p.score_pct}%</b> — проверено кодом. ` : ""}${p.questions.some((q) => q.open) ? "Открытые Арвикс учтёт на проверке блока. " : ""}${p.questions.some((q) => q.ok === false) ? "Ошибки — в «Работе над ошибками»." : ""}</div>`;
  return qs + (live ? `<button class="btn primary" data-squiz="${esc(p.id)}">Проверить</button>` : `<div class="muted small">Тест не решён.</div>`);
}

// --- доска: формулы разбирает свой парсер (без eval), рисует SVG ---------------------------------
const FN = { sin: Math.sin, cos: Math.cos, tan: Math.tan, sqrt: Math.sqrt, abs: Math.abs, log: Math.log10, ln: Math.log, exp: Math.exp,
  asin: Math.asin, acos: Math.acos, atan: Math.atan };
function parseExpr(src) {
  const toks = String(src).replace(/,/g, ".").match(/\d+\.?\d*|\.\d+|[a-z_]+|[+\-*/^()]/gi) || [];
  let i = 0;
  const peek = () => toks[i], next = () => toks[i++];
  const primary = () => {
    const t = next();
    if (t === undefined) throw new Error("конец формулы");
    if (/^[\d.]/.test(t)) { const v = parseFloat(t); return () => v; }
    if (t === "(") { const e = expr(); if (next() !== ")") throw new Error("нет )"); return e; }
    const w = t.toLowerCase();
    if (w === "x") return (x) => x;
    if (w === "pi") return () => Math.PI;
    if (w === "e") return () => Math.E;
    if (FN[w]) { if (next() !== "(") throw new Error("нет ( после " + w); const a = expr(); if (next() !== ")") throw new Error("нет )"); const f = FN[w]; return (x) => f(a(x)); }
    throw new Error("непонятно: " + t);
  };
  const unary = () => { if (peek() === "-") { next(); const u = unary(); return (x) => -u(x); } if (peek() === "+") { next(); return unary(); } return power(); };
  const power = () => { const b = primary(); if (peek() === "^") { next(); const ex = unary(); return (x) => Math.pow(b(x), ex(x)); } return b; };
  const term = () => {
    let a = unary();
    for (;;) {
      const t = peek();
      if (t === "*" || t === "/") { next(); const b = unary(), l = a; a = t === "*" ? (x) => l(x) * b(x) : (x) => l(x) / b(x); }
      else if (t !== undefined && (/^[\d.a-z(]/i.test(t))) { const b = power(), l = a; a = (x) => l(x) * b(x); }  // 2x, 3sin(x), (x+1)(x-1)
      else return a;
    }
  };
  const expr = () => {
    let a = term();
    while (peek() === "+" || peek() === "-") { const op = next(), b = term(), l = a; a = op === "+" ? (x) => l(x) + b(x) : (x) => l(x) - b(x); }
    return a;
  };
  const f = expr();
  if (i < toks.length) throw new Error("лишнее: " + toks[i]);
  return f;
}

const BOARD_COLORS = ["var(--accent)", "var(--accent-2)", "var(--warn)", "var(--bad)", "#d65db1"];
function boardSvg(p) {
  // Масштаб по осям один и тот же: окружность — круг, квадрат — квадрат (геометрия). Высота — по пропорции
  // окна доски; слишком высокая или низкая — окно расширяется по другой оси, а не сплющивает чертёж.
  let [x0, x1, y0, y1] = p.view;
  const W = 480;
  let H = (W * (y1 - y0)) / (x1 - x0);
  if (H > 420) { H = 420; const span = ((y1 - y0) * W) / H, cx = (x0 + x1) / 2; x0 = cx - span / 2; x1 = cx + span / 2; }
  if (H < 220) { H = 220; const span = ((x1 - x0) * H) / W, cy = (y0 + y1) / 2; y0 = cy - span / 2; y1 = cy + span / 2; }
  H = Math.round(H);
  const sx = (x) => ((x - x0) / (x1 - x0)) * W, sy = (y) => H - ((y - y0) / (y1 - y0)) * H;
  const num = (v) => (+v).toFixed(1);
  let g = "";
  const step = (span) => { const raw = span / 10, p10 = Math.pow(10, Math.floor(Math.log10(raw))); return [1, 2, 5, 10].map((m) => m * p10).find((s) => s >= raw); };
  const dx = step(x1 - x0), dy = step(y1 - y0);
  for (let x = Math.ceil(x0 / dx) * dx; x <= x1; x += dx) g += `<line x1="${num(sx(x))}" x2="${num(sx(x))}" y1="0" y2="${H}" class="bd-grid"/>` + (Math.abs(x) > 1e-9 && y0 <= 0 && y1 >= 0 ? `<text x="${num(sx(x))}" y="${num(Math.min(H - 3, sy(0) + 13))}" class="bd-tick" text-anchor="middle">${+x.toFixed(6)}</text>` : "");
  for (let y = Math.ceil(y0 / dy) * dy; y <= y1; y += dy) g += `<line y1="${num(sy(y))}" y2="${num(sy(y))}" x1="0" x2="${W}" class="bd-grid"/>` + (Math.abs(y) > 1e-9 && x0 <= 0 && x1 >= 0 ? `<text x="${num(Math.max(3, sx(0) - 4))}" y="${num(sy(y) + 4)}" class="bd-tick" text-anchor="end">${+y.toFixed(6)}</text>` : "");
  if (y0 <= 0 && y1 >= 0) g += `<line x1="0" x2="${W}" y1="${num(sy(0))}" y2="${num(sy(0))}" class="bd-axis"/>`;
  if (x0 <= 0 && x1 >= 0) g += `<line y1="0" y2="${H}" x1="${num(sx(0))}" x2="${num(sx(0))}" class="bd-axis"/>`;
  let c = 0, errors = [];
  for (const it of p.items) {
    const color = BOARD_COLORS[c % BOARD_COLORS.length];
    if (it.kind === "fn") {
      c++;
      let f;
      try { f = parseExpr(it.expr); } catch (err) { errors.push(`${it.expr}: ${err.message}`); continue; }
      let d = "", pen = false;
      for (let k = 0; k <= 400; k++) {
        const x = x0 + ((x1 - x0) * k) / 400, y = f(x);
        if (!isFinite(y) || y < y0 - (y1 - y0) * 2 || y > y1 + (y1 - y0) * 2) { pen = false; continue; }
        d += `${pen ? "L" : "M"}${num(sx(x))} ${num(sy(y))}`; pen = true;
      }
      g += `<path d="${d}" class="bd-fn" stroke="${color}"/>`;
      if (it.label) g += `<text x="${W - 6}" y="${14 + 16 * (c - 1)}" class="bd-label" text-anchor="end" fill="${color}">${esc(it.label)}</text>`;
    } else if (it.kind === "point") {
      g += `<circle cx="${num(sx(it.x))}" cy="${num(sy(it.y))}" r="4" class="bd-pt"/>` + (it.label ? `<text x="${num(sx(it.x) + 6)}" y="${num(sy(it.y) - 6)}" class="bd-label">${esc(it.label)}</text>` : "");
    } else if (it.kind === "label") {
      g += `<text x="${num(sx(it.x))}" y="${num(sy(it.y))}" class="bd-label">${esc(it.label)}</text>`;
    } else if (it.kind === "segment") {
      g += `<line x1="${num(sx(it.x))}" y1="${num(sy(it.y))}" x2="${num(sx(it.x2))}" y2="${num(sy(it.y2))}" class="bd-shape"/>` + (it.label ? `<text x="${num((sx(it.x) + sx(it.x2)) / 2 + 4)}" y="${num((sy(it.y) + sy(it.y2)) / 2 - 4)}" class="bd-label">${esc(it.label)}</text>` : "");
    } else if (it.kind === "circle") {
      g += `<ellipse cx="${num(sx(it.x))}" cy="${num(sy(it.y))}" rx="${num((it.r / (x1 - x0)) * W)}" ry="${num((it.r / (y1 - y0)) * H)}" class="bd-shape"/>` + (it.label ? `<text x="${num(sx(it.x) + 4)}" y="${num(sy(it.y) - 4)}" class="bd-label">${esc(it.label)}</text>` : "");
    } else if (it.kind === "polygon") {
      g += `<polygon points="${it.points.map(([x, y]) => `${num(sx(x))},${num(sy(y))}`).join(" ")}" class="bd-shape bd-fill"/>` + (it.label ? `<text x="${num(sx(it.points[0][0]) + 4)}" y="${num(sy(it.points[0][1]) - 4)}" class="bd-label">${esc(it.label)}</text>` : "");
    }
  }
  return `<svg class="board" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(p.title)}">${g}</svg>` +
    (errors.length ? `<div class="small warn">Не нарисовал: ${errors.map(esc).join("; ")}</div>` : "");
}

/* Схема: слои по стрелкам от корней (узлы без входящих), в слое — по порядку; длинное имя — в две строки. */
function diagramSvg(p) {
  const incoming = new Map(p.nodes.map((n) => [n.id, 0]));
  p.edges.forEach((e) => incoming.set(e.to, (incoming.get(e.to) || 0) + 1));
  const layer = new Map();
  const queue = p.nodes.filter((n) => !incoming.get(n.id)).map((n) => n.id);
  if (!queue.length) queue.push(p.nodes[0].id);
  queue.forEach((id) => layer.set(id, 0));
  for (let k = 0; k < queue.length; k++) {
    const id = queue[k];
    for (const e of p.edges) if (e.from === id && !layer.has(e.to)) { layer.set(e.to, layer.get(id) + 1); queue.push(e.to); }
  }
  p.nodes.forEach((n) => { if (!layer.has(n.id)) layer.set(n.id, 0); });
  const rows = [];
  p.nodes.forEach((n) => { const l = layer.get(n.id); (rows[l] = rows[l] || []).push(n); });
  const BW = 132, BH = 42, GX = 16, GY = 46;
  const W = Math.max(...rows.map((r) => r.length)) * (BW + GX) + GX, H = rows.length * (BH + GY) + GY - 20;
  const pos = new Map();
  rows.forEach((r, li) => { const off = (W - r.length * (BW + GX) + GX) / 2; r.forEach((n, k) => pos.set(n.id, { x: off + k * (BW + GX), y: 14 + li * (BH + GY) })); });
  const split = (s) => { if (s.length <= 18) return [s]; const cut = s.lastIndexOf(" ", 18); const a = cut > 6 ? s.slice(0, cut) : s.slice(0, 18); const b = s.slice(a.length).trim(); return [a, b.length > 18 ? b.slice(0, 17) + "…" : b]; };
  let g = `<defs><marker id="dg-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="dg-head"/></marker></defs>`;
  for (const e of p.edges) {
    const a = pos.get(e.from), b = pos.get(e.to);
    const up = b.y <= a.y;
    const x1 = a.x + BW / 2, y1 = up ? a.y : a.y + BH, x2 = b.x + BW / 2, y2 = up ? b.y + BH : b.y;
    g += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" class="dg-edge" marker-end="url(#dg-arrow)"/>`;
    if (e.label) g += `<text x="${(x1 + x2) / 2 + 4}" y="${(y1 + y2) / 2}" class="bd-tick">${esc(e.label)}</text>`;
  }
  for (const n of p.nodes) {
    const { x, y } = pos.get(n.id), lines = split(n.label);
    g += `<rect x="${x}" y="${y}" width="${BW}" height="${BH}" rx="10" class="dg-node"/>` +
      lines.map((l, k) => `<text x="${x + BW / 2}" y="${y + BH / 2 + 5 + (k - (lines.length - 1) / 2) * 15}" text-anchor="middle" class="dg-text">${esc(l)}</text>`).join("");
  }
  return `<div class="dg-wrap"><svg class="diagram" viewBox="0 0 ${W} ${H}" width="${W}" role="img" aria-label="${esc(p.title)}">${g}</svg></div>`;
}

// --- заметка урока: пишет человек, Арвикс читает ---------------------------------------------
/* Заметка свёрнута до строки: полный текст — по «Открыть» или «Писать». Иначе каркас Concept.md со свойствами
 * занимал весь стол и закрывал то, что нужно делать сейчас. */
function noteBody(p) {
  const n = studyUI.notes[p.path];
  if (!n) {
    loadStudyNote(p.path);
    return `<div class="muted small">Открываю ${esc(p.path)}…</div>`;
  }
  if (n.missing) return `<div class="muted small">Заметки ${esc(p.path)} нет в хранилище.</div>`;
  const at = `data-snote="${esc(n.path)}"`;
  const bar = n.edit ? `<button class="pill small-pill primary" data-snote-save ${at}>Сохранить</button><button class="pill small-pill" data-snote-cancel ${at}>Отмена</button>`
    : `<button class="pill small-pill primary" data-snote-edit ${at}>${icon("pencil")} Писать</button>${n.open ? `<button class="pill small-pill" data-snote-fold ${at}>Свернуть</button>` : `<button class="pill small-pill" data-snote-open ${at}>Открыть</button>`}<a class="pill small-pill" href="${obsidianUrl(n.path)}">Obsidian</a>`;
  let body = "";
  if (n.edit) body = `<textarea class="pn-edit sn-edit" ${at}>${esc(n.text)}</textarea>`;
  else if (n.open) { const doc = obsidian(n.text); body = `<div class="obs pn-view">${doc.props.length ? propsHtml(doc.props) : ""}${doc.html || `<p class="muted">Пусто — «Писать».</p>`}</div>`; }
  else {
    const s = state.study && state.study.session;
    const own = s && s.note === n.path ? s.note_own : null;  // сколько написал сам — считает сервер, без каркаса шаблона
    body = !own ? `<div class="small muted">Открой, чтобы прочитать заметку.</div>`
      : own.words ? `<div class="small">Своими словами — ${own.words} сл.: ${esc(own.preview)}</div>`
      : `<div class="small muted">Пока пусто. Закрой разбор и запиши суть, пример и ловушку — без подглядывания: так запоминается.</div>`;
  }
  return `<div class="sn-bar"><span class="muted small sn-file">${esc(n.path.split("/").pop())}</span><span class="sn-acts">${bar}</span></div>${body}`;
}

const notesLoading = new Set();
async function loadStudyNote(path) {
  if (notesLoading.has(path)) return;
  notesLoading.add(path);
  try { const n = await api("note?path=" + encodeURIComponent(path)); studyUI.notes[path] = { path: n.path, text: n.text, sha: n.sha, edit: false, open: false }; }
  catch (_) { studyUI.notes[path] = { path, missing: true }; }
  notesLoading.delete(path);
  if (state.tab === "study" && !studyEditing()) { studyUI.deskKey = ""; renderStudy(); }
}
const studyEditing = () => Object.values(studyUI.notes).some((n) => n.edit);

// --- чат урока: своя нить сессии (D56), с фото решения и голосом (D60) ----------------------------
function studyChatHtml(s) {
  const can = s.live;
  return `<div class="pc sc"><div class="pc-thread" id="sc-thread"></div>
    ${can ? `<div class="aw-chips">${s.asks.map((q) => `<button class="chip" data-sask="${esc(q)}">${esc(q)}</button>`).join("")}</div>
    <div class="pc-compose"><button class="icon-btn" id="sc-file" aria-label="Прислать фото решения, скриншот или файл">${icon("clip")}</button>
      <input type="file" id="sc-files" multiple hidden>
      <textarea id="sc-text" rows="1" placeholder="Спроси Арвикса — он видит этот стол"></textarea>
      <button class="icon-btn go" id="sc-send" data-mode="mic" aria-label="Голосовое сообщение">${icon("mic")}</button></div>`
      : `<div class="muted small">Сессия закрыта — переписка сохранена здесь.</div>`}</div>`;
}

function drawStudyThread() {
  const box = $("#sc-thread"), s = state.study && state.study.session;
  if (!box || !s) return;
  const msgs = s.messages || [];
  const thinking = state.thinking && (!msgs.length || msgs[msgs.length - 1].who === "me");
  box.innerHTML = (msgs.length ? msgs.map((m) => `<div class="msg ${m.who === "me" ? "me" : ""}">${quoteHtml(m.reply_to)}<div class="mtext">${linkify(esc(m.text))}</div>
      ${(m.buttons || []).length ? `<div class="btns">${m.buttons.map((row) => row.map(([label, data]) => `<button data-sbtn="${esc(data)}">${esc(label)}</button>`).join("")).join("")}</div>` : ""}</div>`).join("")
    : `<div class="pc-empty muted small">Застрял — спроси текстом или голосом. Решил в тетради — сфоткай и пришли (📎): Арвикс найдёт, где ошибка. Он объяснит у доски, нарисует чертёж, даст похожую задачу — окна появятся на этапе.</div>`)
    + (thinking ? `<div class="msg typing">${/слуша/.test(state.thinking) ? "Арвикс слушает…" : /файл/.test(state.thinking) ? "Арвикс смотрит файл…" : "Арвикс думает…"}</div>` : "");
  box.scrollTop = box.scrollHeight;
  box.querySelectorAll("[data-sbtn]").forEach((b) => b.addEventListener("click", async () => {
    haptic(); try { await api("button", { json: { data: b.dataset.sbtn } }); } catch (err) { toast(err.message); }
  }));
}

function studyMine(text) {
  const s = state.study.session;
  s.messages = [...(s.messages || []), { who: "me", text, at: new Date().toISOString() }];
}

async function studySend(text) {
  text = String(text || "").trim();
  if (!text) return;
  const s = state.study.session;
  studyMine(text);
  state.thinking = "думаю";
  drawStudyThread();
  try { await api(`study/${s.task.id}/message`, { json: { text } }); } catch (err) { toast(err.message); }
}

async function studyFiles(files) {
  const s = state.study.session, ta = $("#sc-text");
  let caption = ta ? ta.value.trim() : "";
  for (const file of files) {
    if (file.size > MAX_FILE) { toast(`«${file.name}» больше 20 МБ — сожми или раздели`); continue; }
    studyMine("📎 " + file.name + (caption ? " — " + caption : ""));
    state.thinking = "смотрю файл"; drawStudyThread();
    try {
      const res = await fetch(`/api/study/${s.task.id}/upload`, { method: "POST", body: file, headers: { ...authHeaders(), "Content-Type": file.type || "application/octet-stream",
        "X-File-Name": encodeURIComponent(file.name), "X-Caption": encodeURIComponent(caption) } });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "Ошибка " + res.status);
      haptic();
    } catch (err) { toast(err.message); }
    caption = "";
  }
  if (ta) { ta.value = ""; ta.style.height = "auto"; studyComposerMode(); }
}

/* Голосовое в нить урока: как в чате — пустое поле = микрофон, есть текст = отправить, идёт запись = стоп. */
let studyRec = null, studyChunks = [], studyRecStart = 0;
function studyComposerMode() {
  const b = $("#sc-send"), ta = $("#sc-text"); if (!b || !ta) return;
  const recording = studyRec && studyRec.state === "recording";
  const mode = recording ? "rec" : ta.value.trim() ? "send" : "mic";
  if (b.dataset.mode === mode) return;
  b.dataset.mode = mode;
  b.innerHTML = icon(mode === "rec" ? "stop" : mode);
  b.classList.toggle("rec", recording);
  b.setAttribute("aria-label", { rec: "Остановить запись", send: "Отправить", mic: "Голосовое сообщение" }[mode]);
}

async function studyRecord() {
  if (studyRec && studyRec.state === "recording") { studyRec.stop(); return; }
  const s = state.study.session;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const type = ["audio/ogg;codecs=opus", "audio/webm;codecs=opus", "audio/mp4"].find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
    const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    studyRec = rec; studyChunks = []; studyRecStart = Date.now();
    rec.ondataavailable = (e) => e.data.size && studyChunks.push(e.data);
    rec.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      studyComposerMode();
      if (Date.now() - studyRecStart < 700) { toast("Слишком коротко"); return; }
      const blob = new Blob(studyChunks, { type: rec.mimeType || "audio/webm" });
      studyMine("🎙 голосовое…");
      state.thinking = "слушаю"; drawStudyThread();
      try { await api(`study/${s.task.id}/voice`, { body: blob, headers: { "Content-Type": blob.type.split(";")[0] } }); } catch (err) { toast(err.message); }
    };
    rec.start(); haptic("medium");
    studyComposerMode();
  } catch (err) { toast("Нет доступа к микрофону: " + err.message); }
}

function captureStudyComposer() {
  const ta = $("#sc-text"), sk = $("#sk-text");
  return { value: ta ? ta.value : "", focus: ta && document.activeElement === ta, check: sk ? sk.value : "", checkFocus: sk && document.activeElement === sk,
    input: document.activeElement && document.activeElement.matches && document.activeElement.matches("input.sq-in")
      ? { sq: document.activeElement.dataset.sq, i: document.activeElement.dataset.i, twin: document.activeElement.dataset.stwinin } : null };
}
function restoreStudyComposer(keep) {
  const ta = $("#sc-text"), sk = $("#sk-text");
  if (ta && keep.value) { ta.value = keep.value; studyComposerMode(); }
  if (ta && keep.focus) ta.focus();
  if (sk && keep.check) sk.value = keep.check;
  if (sk && keep.checkFocus) sk.focus();
  if (keep.input) {  // поле ответа, в котором печатал, — снова под курсором после перерисовки
    const sel = keep.input.twin ? `input[data-stwinin="${CSS.escape(keep.input.twin)}"]` : `input.sq-in[data-sq="${CSS.escape(keep.input.sq || "")}"][data-i="${keep.input.i}"]`;
    const el = view.querySelector(sel); if (el) { el.focus(); const v = el.value; el.value = ""; el.value = v; }
  }
}

let studyTimer;
function tickStudy() {
  clearInterval(studyTimer);
  const el = $("#sw-timer");
  if (!el) return;
  const draw = () => {
    const left = el.dataset.paused ? new Date(el.dataset.until) - new Date(el.dataset.paused) : new Date(el.dataset.until) - Date.now();
    const sec = Math.max(0, Math.round(left / 1000));
    const out = $("#sw-left"); if (out) out.textContent = `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
  };
  draw();
  if (!el.dataset.paused) studyTimer = setInterval(() => { if (!document.body.contains(el)) { clearInterval(studyTimer); return; } draw(); }, 1000);
}

// --- повторение тем: отдельный экран ---------------------------------------------------------------
function renderReview() {
  const R = state.study.review || {}, q = R.quiz;
  let html = `<div class="so"><div class="ph"><button class="icon-btn sm" data-srevback aria-label="К разделу">${icon("back")}</button>
    <div class="grow ph-text"><div class="ph-title">Повторение</div><div class="muted small">Вспомни метод, а не ответ: числа новые. Не знаешь — «Не знаю».</div></div></div>`;
  if (!q) {
    html += `<div class="card"><div class="muted">${studyUI.busy === "review" ? "Арвикс собирает задачи по темам…" : "Повторения на сегодня нет."}</div></div></div>`;
    view.innerHTML = html; bindStudy(); return;
  }
  const sel = studyUI.rq;
  html += `<div class="sp">${q.items.map((it, i) => {
    const head = `<div class="muted small">${esc(it.topic)}</div><div>${i + 1}. ${esc(it.q)}</div>`;
    if (q.done) {
      const right = it.options ? `<div class="sq-opts">${it.options.map((o, j) => `<span class="sq-opt${j === it.answer ? " right" : ""}${j === it.given && j !== it.answer ? " wrong" : ""}">${esc(o)}</span>`).join("")}</div>`
        : `<div class="small">${it.given === "?" ? "Не знал" : `Твой ответ: <span class="${it.ok ? "fx-good" : "fx-bad"}">${esc(it.given_text)}</span>`}${it.ok ? "" : ` · верно: <b class="fx-good">${esc(it.right)}</b>`}</div>`;
      return `<div class="sq ${it.ok ? "ok" : "bad"}">${head.replace("<div>", `<div><b>${it.ok ? "✓" : "✗"}</b> `)}${right}${it.why ? `<div class="small muted sq-why">${esc(it.why)}</div>` : ""}</div>`;
    }
    const unk = sel[i] === "?";
    const body = it.options ? `<div class="sq-opts">${it.options.map((o, j) => `<button type="button" class="sq-opt${sel[i] === j ? " on" : ""}" data-rq="${i}" data-j="${j}">${esc(o)}</button>`).join("")}</div>`
      : `<input class="sq-in" data-rqin="${i}" value="${esc(unk ? "" : sel[i] ?? "")}" placeholder="Ответ — число или слово" autocomplete="off"${unk ? " disabled" : ""}>`;
    return `<div class="sq${unk ? " unk" : ""}">${head}${body}<button type="button" class="chip sq-unk${unk ? " accent" : ""}" data-rqunk="${i}">Не знаю</button></div>`;
  }).join("")}
    ${q.done ? "" : `<button class="btn primary" data-rqok>Проверить</button>`}</div>`;
  if (q.done) {
    html += `<div class="sp"><b>Дальше по темам</b>${q.by_review.map((r) => `<div class="small">${esc(r.topic)} — <b>${r.pct}%</b> · ${r.status === "done" ? "закреплена, больше не повторяем" : r.pct >= 80 ? "интервал растёт: " + dueText(r.due) : r.pct < 50 ? "с начала: " + dueText(r.due) : "тот же интервал: " + dueText(r.due)}</div>`).join("")}
      <div class="muted small">Ошибся — разбери решение выше; спросить «почему» можно в общем чате.</div></div>`;
  }
  view.innerHTML = html + `</div>`;
  bindStudy();
}

async function startReview() {
  if (studyUI.busy) return;
  studyUI.busy = "review"; studyUI.rq = {}; renderStudy();
  try { const r = await api("study/review", { json: {} }); state.study.review = r.review; studyUI.review = true; }
  catch (err) { toast(err.message); }
  studyUI.busy = ""; renderStudy(); window.scrollTo(0, 0);
}

// --- действия ----------------------------------------------------------------------------------
async function openStudySession(body) {
  try {
    const r = await api("study/open", { json: body });
    studyUI.open = true; studyUI.task = r.task_id; studyUI.notes = {}; studyUI.deskKey = ""; studyUI.view = null; studyUI.review = false; studyUI.peek = false;
    if (r.queued) { state.thinking = "готовлю урок"; toast("Арвикс готовит сессию: задачи, разбор, видео — минуту-две"); }
    if (state.tab !== "study") { setTab("study"); return; }
    await loadStudy(); renderStudy();
  } catch (err) { toast(err.message); }
}

async function studyOp(op, body, msg) {
  const s = state.study.session;
  const r = await api(`study/${s.task.id}/${op}`, { json: body });
  if (r.session) state.study.session = r.session;
  notify("success");
  if (msg) toast(typeof msg === "function" ? msg(r) : msg);
  studyUI.deskKey = ""; renderStudy();
  return r;
}

async function goStage(stage) {
  const s = state.study.session;
  if (!s.live) { studyUI.view = stage; studyUI.deskKey = ""; renderStudy(); }
  else if (stage !== s.stage) { try { await studyOp("stage", { stage }); } catch (err) { toast(err.message); return; } }
  const desk = $(".sw-desk"); if (desk) desk.scrollTop = 0;
  window.scrollTo(0, 0);
}

function openStudyLearnSheet() {
  const S = state.study, form = { kind: "theory" };
  openSheet(`<h2>Что выучить</h2>
    <div class="field"><input id="sl-topic" placeholder="Например: тригонометрия, asyncio, задание 15 ОГЭ"></div>
    <div class="field"><label>Вид</label>${seg("kind", ["theory", "practice"], "theory", (v) => KIND_RU[v])}</div>
    <div class="field"><textarea id="sl-why" rows="2" placeholder="Зачем — по желанию: экзамен, проект, интерес"></textarea></div>
    ${S.projects.length ? `<div class="field"><select id="sl-proj" class="input"><option value="">Без проекта</option>${S.projects.map((p) => `<option value="${esc(p.id)}">${esc(p.title)}</option>`).join("")}</select></div>` : ""}
    <button class="btn primary" id="sl-save">Добавить</button>
    <p class="muted small">Теория — понять и объяснить своими словами. Практика — сделать руками: задачи, код, упражнение. Тема проекта видна и в проекте.</p>`, (root) => {
    bindSeg(root, form);
    setTimeout(() => $("#sl-topic").focus(), 50);
    $("#sl-save").onclick = async () => {
      const topic = $("#sl-topic").value.trim();
      if (!topic) { toast("Какая тема?"); return; }
      try { const r = await api("study/learn", { json: { topic, kind: form.kind, why: $("#sl-why").value.trim(), project: $("#sl-proj") ? $("#sl-proj").value : "" } });
        state.study = r.study; closeSheet(); notify("success"); toast("+ тема"); renderStudy(); }
      catch (err) { toast(err.message); }
    };
  });
}

function bindStudy() {
  const on = (sel, fn) => view.querySelectorAll(sel).forEach((el) => el.addEventListener("click", (e) => { haptic("soft"); fn(el, e); }));
  on("[data-sresume]", () => { studyUI.open = true; studyUI.task = null; studyUI.view = null; renderStudy(); window.scrollTo(0, 0); });
  on("[data-sopen]", (el) => openStudySession({ task: el.dataset.sopen }));
  on("[data-sitem]", (el) => openStudySession({ item: el.dataset.sitem }));
  on("[data-shist]", async (el) => { studyUI.task = el.dataset.shist; studyUI.open = true; studyUI.notes = {}; studyUI.view = null; await loadStudy(); renderStudy(); window.scrollTo(0, 0); });
  on("[data-slearn-add]", () => openStudyLearnSheet());
  on("[data-srev]", () => startReview());
  on("[data-srevopen]", () => { studyUI.review = true; renderStudy(); window.scrollTo(0, 0); });
  on("[data-srevback]", async () => { studyUI.review = false; await loadStudy(); renderStudy(); window.scrollTo(0, 0); });
  on("[data-srevdrop]", async (el) => {
    if (!confirm("Убрать тему из повторений? Вернуть её можно новой сессией по теме.")) return;
    try { const r = await api("study/review/drop", { json: { review: el.dataset.srevdrop } }); state.study.review = r.review; renderStudy(); } catch (err) { toast(err.message); }
  });
  on("[data-sdone]", async (el) => {
    try { const r = await api("study/learn", { json: { item: el.dataset.sdone, status: "done" } }); state.study = r.study; toast("✓ Отмечено — в проекте тоже"); renderStudy(); }
    catch (err) { toast(err.message); }
  });
  on("[data-skind]", async (el) => {
    const x = state.study.queue.find((q) => q.id === el.dataset.skind); if (!x) return;
    try { const r = await api("study/learn", { json: { item: x.id, kind: x.kind === "practice" ? "theory" : "practice" } }); state.study = r.study; renderStudy(); }
    catch (err) { toast(err.message); }
  });
  on("[data-sback]", async () => { studyUI.open = false; studyUI.task = null; studyUI.notes = {}; studyUI.view = null; await loadStudy(); renderStudy(); window.scrollTo(0, 0); });
  on("[data-spane]", (el) => { studyLayout.pane = el.dataset.spane; saveStudyLayout(); studyUI.deskKey = ""; renderStudy(); });
  on("[data-sstage]", (el) => goStage(el.dataset.sstage));
  on("[data-speek]", () => { studyUI.peek = true; studyUI.deskKey = ""; renderStudy(); });
  on("[data-sgo]", async () => {
    try { await api("lesson/" + state.study.session.task.id, { json: {} }); toast("Пошло. Телефон — экраном вниз."); } catch (err) { toast(err.message); }
  });
  on("[data-scheck]", async (el) => {
    const s = state.study.session, left = (s.errors || []).filter((e) => !e.closed).length;
    if (!confirm(`Закончить блок и ответить на вопросы проверки?${left ? `\nНезакрытых ошибок: ${left} — они уйдут в повторение.` : ""}`)) return;
    el.disabled = true;
    try { await studyOp("check", {}); } catch (err) { el.disabled = false; toast(err.message); }
  });
  on("[data-sfocus]", async (el) => { try { await api("focus/" + el.dataset.sfocus, { json: {} }); } catch (err) { toast(err.message); } });
  on("[data-skheck]", async () => {
    const t = $("#sk-text").value.trim();
    if (!t) { toast("Ответь хотя бы «не знаю» — это тоже ответ"); return; }
    $("#sk-text").value = "";
    if (!isWide()) { studyLayout.pane = "chat"; saveStudyLayout(); }
    await studySend(t);
    studyUI.deskKey = ""; renderStudy();
  });
  on("[data-sask]", (el) => { if (!isWide()) { studyLayout.pane = "chat"; saveStudyLayout(); studyUI.deskKey = ""; renderStudy(); } studySend(el.dataset.sask); });
  on("[data-shide]", async (el) => { try { await studyOp("hide", { panel: el.dataset.shide }); } catch (err) { toast(err.message); } });
  on("[data-sadd]", async () => {
    const url = (prompt("Ссылка на видео (YouTube, RuTube, Vimeo — встроится; другое — ссылкой)", "") || "").trim(); if (!url) return;
    try { await studyOp("panel", { panel: { type: "video", url, title: "Видео", stage: "learn" } }, "Видео на столе"); } catch (err) { toast(err.message); }
  });
  on("[data-svid]", (el) => { studyUI.quiz["v:" + el.dataset.svid] = +el.dataset.j; studyUI.deskKey = ""; renderStudy(); });
  // тест: выбор, короткий ответ, «не знаю»
  view.querySelectorAll("button[data-sq]").forEach((b) => b.addEventListener("click", () => {
    haptic("soft");
    const sel = studyUI.quiz[b.dataset.sq] || (studyUI.quiz[b.dataset.sq] = {});
    sel[+b.dataset.i] = +b.dataset.j;
    b.parentElement.querySelectorAll(".sq-opt").forEach((o) => o.classList.toggle("on", o === b));
    const unk = b.closest(".sq").querySelector(".sq-unk"); if (unk) unk.classList.remove("accent");
    b.closest(".sq").classList.remove("unk");
  }));
  view.querySelectorAll("textarea[data-sq], input[data-sq]").forEach((t) => t.addEventListener("input", () => {
    (studyUI.quiz[t.dataset.sq] || (studyUI.quiz[t.dataset.sq] = {}))[+t.dataset.i] = t.value;
  }));
  view.querySelectorAll("input[data-sq]").forEach((t) => t.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const all = [...view.querySelectorAll(`input.sq-in[data-sq="${CSS.escape(t.dataset.sq)}"]:not([disabled])`)];
    const next = all[all.indexOf(t) + 1];
    if (next) next.focus(); else { const btn = view.querySelector(`[data-squiz="${CSS.escape(t.dataset.sq)}"]`); if (btn) btn.focus(); }
  }));
  on("[data-sunk]", (el) => {
    const sel = studyUI.quiz[el.dataset.sunk] || (studyUI.quiz[el.dataset.sunk] = {});
    const i = +el.dataset.i;
    sel[i] = sel[i] === "?" ? null : "?";
    studyUI.deskKey = ""; renderStudy();
  });
  on("[data-squiz]", async (el) => {
    const p = state.study.session.panels.find((x) => x.id === el.dataset.squiz); if (!p) return;
    const sel = studyUI.quiz[p.id] || {};
    const answers = p.questions.map((q, i) => (sel[i] === "?" ? "?" : q.options ? sel[i] ?? null : String(sel[i] ?? "").trim()));
    const empty = answers.filter((a, i) => (p.questions[i].options ? a == null : a === "")).length;
    if (empty && !confirm(`Без ответа: ${empty}. Проверить так? Пустой ответ — ошибка; честнее отметить «Не знаю».`)) return;
    el.disabled = true; el.textContent = "Проверяю…";  // проверка — код, но очередь может быть занята головой
    try {
      await studyOp("answer", { panel: p.id, answers }, (r) => r.score_pct != null ? `${r.score_pct}% — решения под задачами` : "Записал — оценит на проверке");
      delete studyUI.quiz[p.id];
    } catch (err) { el.disabled = false; el.textContent = "Проверить"; toast(err.message); }
  });
  // работа над ошибками
  on("[data-sfixkind]", async (el) => { try { await studyOp("fix", { key: el.dataset.key, kind: el.dataset.sfixkind }); } catch (err) { toast(err.message); } });
  on("[data-sfixdone]", async (el) => { try { await studyOp("fix", { key: el.dataset.sfixdone, done: true }, "Закрыто — тема всё равно вернётся в повторении"); } catch (err) { toast(err.message); } });
  on("[data-stwin]", (el) => { studyUI.twin[el.dataset.stwin] = +el.dataset.j; el.parentElement.querySelectorAll(".sq-opt").forEach((o) => o.classList.toggle("on", o === el)); });
  view.querySelectorAll("input[data-stwinin]").forEach((t) => {
    t.addEventListener("input", () => { studyUI.twin[t.dataset.stwinin] = t.value; });
    t.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); const b = view.querySelector(`[data-stwinok="${CSS.escape(t.dataset.stwinin)}"]`); if (b) b.click(); } });
  });
  on("[data-stwinok]", async (el) => {
    const key = el.dataset.stwinok, v = studyUI.twin[key];
    if (v == null || String(v).trim() === "") { toast("Сначала ответ"); return; }
    el.disabled = true;
    try { const r = await studyOp("fix", { key, twin: v }, (r) => r.fixed.twin.ok ? "✓ Верно — ошибка закрыта" : "✗ Неверно — посмотри решение"); delete studyUI.twin[key]; return r; }
    catch (err) { el.disabled = false; toast(err.message); }
  });
  // заметка
  const noteOf = (el) => studyUI.notes[el.dataset.snote];
  on("[data-snote-edit]", (el) => { noteOf(el).edit = true; studyUI.deskKey = ""; renderStudy();
    setTimeout(() => { const t = view.querySelector(`textarea.sn-edit[data-snote="${CSS.escape(el.dataset.snote)}"]`); if (t) t.focus(); }, 30); });
  on("[data-snote-open]", (el) => { noteOf(el).open = true; studyUI.deskKey = ""; renderStudy(); });
  on("[data-snote-fold]", (el) => { noteOf(el).open = false; studyUI.deskKey = ""; renderStudy(); });
  on("[data-snote-cancel]", (el) => { noteOf(el).edit = false; studyUI.deskKey = ""; renderStudy(); });
  on("[data-snote-save]", async (el) => {
    const n = noteOf(el), box = view.querySelector(`textarea.sn-edit[data-snote="${CSS.escape(n.path)}"]`);
    try { const r = await api("note", { json: { path: n.path, text: box.value, sha: n.sha } });
      studyUI.notes[n.path] = { path: r.path, text: r.text, sha: r.sha, edit: false, open: false }; toast("Сохранено — Арвикс видит"); studyUI.deskKey = ""; renderStudy(); }
    catch (err) { if (err.status === 409) { toast("Заметку изменили — открыл свежую"); delete studyUI.notes[n.path]; loadStudyNote(n.path); } else toast(err.message); }
  });
  // повторение
  view.querySelectorAll("button[data-rq]").forEach((b) => b.addEventListener("click", () => {
    haptic("soft"); studyUI.rq[+b.dataset.rq] = +b.dataset.j;
    b.parentElement.querySelectorAll(".sq-opt").forEach((o) => o.classList.toggle("on", o === b));
  }));
  view.querySelectorAll("input[data-rqin]").forEach((t) => t.addEventListener("input", () => { studyUI.rq[+t.dataset.rqin] = t.value; }));
  on("[data-rqunk]", (el) => { const i = +el.dataset.rqunk; studyUI.rq[i] = studyUI.rq[i] === "?" ? null : "?"; renderStudy(); });
  on("[data-rqok]", async (el) => {
    const q = state.study.review.quiz;
    const answers = q.items.map((it, i) => (studyUI.rq[i] === "?" ? "?" : it.options ? studyUI.rq[i] ?? null : String(studyUI.rq[i] ?? "").trim()));
    const empty = answers.filter((a) => a == null || a === "").length;
    if (empty && !confirm(`Без ответа: ${empty}. Проверить так?`)) return;
    el.disabled = true; el.textContent = "Проверяю…";
    try { const r = await api("study/review/answer", { json: { answers } }); state.study.review = r.review; studyUI.rq = {}; notify("success"); renderStudy(); window.scrollTo(0, 0); }
    catch (err) { el.disabled = false; el.textContent = "Проверить"; toast(err.message); }
  });
  view.querySelectorAll(".sp-text .obs, .sp-note .obs").forEach((el) => hydrateAssets(el));
  view.querySelectorAll("[data-sresume], [data-shist]").forEach((el) => el.addEventListener("keydown", (e) => { if (e.key === "Enter") el.click(); }));
  const ta = $("#sc-text");
  if (ta) {
    const grow = () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 160) + "px"; studyComposerMode(); };
    ta.addEventListener("input", grow); grow();
    const send = () => { const t = ta.value; ta.value = ""; grow(); studySend(t); };
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && isWide()) { e.preventDefault(); send(); } });
    $("#sc-send").onclick = () => ($("#sc-send").dataset.mode === "send" ? send() : studyRecord());
    $("#sc-file").onclick = () => $("#sc-files").click();
    $("#sc-files").onchange = (e) => { studyFiles([...e.target.files]); e.target.value = ""; };
  }
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
        if (state.tab === "projects") {
          await loadProjects();
          if (!(state.projNote && state.projNote.edit)) renderProjects();  // правку заметки не сбиваем
        }
        if (state.tab === "study") {
          await loadStudy();
          if (!studyEditing()) renderStudy({ live: true });  // видео и ответы теста не сбиваем: стол без изменений — только чат
        }
      }
    } catch (err) { if (err.auth) renderLogin(); }
  }, 250);
}

// --- клавиатура (ноутбук) ----------------------------------------------------------------------
/* Ctrl/Alt+1…6 — вкладки, Alt+N — новая задача, / — поиск или поле сообщения, E — править заметку
 * (клавиши — по e.code, чтобы работали и на русской раскладке),
 * Ctrl+S — сохранить, Esc — закрыть окно, заметку или разговор. На телефоне клавиатуры нет — ничего не мешает. */
const TABS = ["today", "chat", "notes", "projects", "study", "progress"];
document.addEventListener("keydown", (e) => {
  const typing = e.target instanceof Element && !!e.target.closest("input, textarea, select, [contenteditable]");
  if ((e.ctrlKey || e.metaKey) && e.code === "KeyS" && $("#e-text")) { e.preventDefault(); saveEditor(); return; }
  if (e.key === "Escape") {
    if (!$("#sheet").classList.contains("hidden")) { closeSheet(); return; }
    if (state.tab === "notes" && state.note) { e.preventDefault(); noteBack(); return; }
    if (state.tab === "projects" && state.projNote) { e.preventDefault(); state.projNote = null; renderProjects(); return; }
    if (state.tab === "projects" && state.project && !isWide()) { e.preventDefault(); projectBack(); return; }
    if (state.tab === "study" && studyUI.open && !typing) { e.preventDefault(); const b = view.querySelector("[data-sback]"); if (b) b.click(); return; }
    if (typing) e.target.blur();
    return;
  }
  if ((e.altKey || e.ctrlKey) && !e.shiftKey && /^Digit[1-6]$/.test(e.code)) {
    e.preventDefault();
    const tab = TABS[+e.code.slice(5) - 1];
    if (tab !== state.tab && !(state.noteEdit && !confirmLeaveEditor())) setTab(tab);
    return;
  }
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.code === "KeyB" && isWide()) { e.preventDefault(); toggleSide(); return; }
  if (e.altKey && e.code === "KeyN") { e.preventDefault(); if (state.data && !state.data.gentle) openAddSheet(); return; }
  if (typing || e.ctrlKey || e.metaKey || e.altKey || !$("#sheet").classList.contains("hidden")) return;
  if (e.key === "/" || e.code === "Slash") {  // физическая клавиша: на русской раскладке она даёт «.»
    const box = state.tab === "notes" ? $("#n-q") : state.tab === "chat" ? $("#msg") : state.tab === "study" ? $("#sc-text") : null;
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
