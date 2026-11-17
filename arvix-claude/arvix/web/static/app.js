/* Арвикс — приложение: Mini App в Telegram, PWA на телефоне. Без сборки и зависимостей.
 * Данные — только через /api (arvix/web/server.py). Живые обновления — поток /api/stream. */
"use strict";

const TG = window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData ? window.Telegram.WebApp : null;
const $ = (sel, root = document) => root.querySelector(sel);
const view = $("#view");
const TOKEN_KEY = "arvix_token";
const state = { tab: "today", data: null, messages: [], history: null, notesDir: "", note: null, thinking: "", seen: 0, version: "" };

// --- вход --------------------------------------------------------------------------------------
(function pairFromHash() {
  const m = location.hash.match(/[#&]t=([\w-]+)/);
  if (m) {
    try { localStorage.setItem(TOKEN_KEY, m[1]); } catch (_) { /* приватный режим */ }
    history.replaceState(null, "", location.pathname);
  }
})();

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
  if (!res.ok) throw new Error(data.error || "Ошибка " + res.status);
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
const MODE_CLASS = { green: "green", normal: "green", yellow: "yellow", red: "red", pressure: "yellow" };

// --- каркас ------------------------------------------------------------------------------------
function setTab(tab) {
  state.tab = tab;
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
  $("#top-sub").textContent = d.gentle ? "Мягкий день" : s ? `${s.done} из ${s.total} · серия ${s.streak} дн` : "";
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
    fab.className = "fab"; fab.textContent = "+"; fab.setAttribute("aria-label", "Новая задача");
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
    const hpLow = s.hp < 40 ? " low" : "";
    html += `<div class="stats">
      <div class="stat"><b>${s.done}/${s.total}</b><span>задач</span><div class="bar"><i style="width:${s.total ? (100 * s.done / s.total) : 0}%"></i></div></div>
      <div class="stat"><b>${s.hp}</b><span>HP</span><div class="bar hp${hpLow}"><i style="width:${s.hp}%"></i></div></div>
      <div class="stat"><b>ур. ${s.level}</b><span>${s.xp_into}/${s.xp_need} XP</span><div class="bar"><i style="width:${100 * s.xp_into / Math.max(1, s.xp_need)}%"></i></div></div>
      <div class="stat"><b>${hm(s.deep_min)}</b><span>глубокая из ${hm(s.deep_target)}</span><div class="bar deep"><i style="width:${Math.min(100, 100 * s.deep_min / Math.max(1, s.deep_target))}%"></i></div></div>
    </div>`;
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
  tickFocus();
}

function focusCard(d) {
  const f = d.focus;
  if (f) {
    return `<div class="card focus" id="focus-card" data-until="${esc(f.until)}" data-start="${esc(f.started)}">
      <div class="ring" id="focus-ring"><div id="focus-left">--:--</div></div>
      <div class="focus-body"><div class="muted small">Фокус · ${f.minutes} мин · до ${esc(f.until.slice(11, 16))}</div>
        <div class="focus-title">${esc(f.title || "глубокая работа")}</div>
        <div class="pills"><button class="pill danger" data-act="focus-stop">⏹ Стоп</button></div></div></div>`;
  }
  if (d.gentle) return "";
  const open = (d.tasks || []).filter((t) => t.open);
  const target = open.find((t) => t.status === "active") || open[0];
  return `<div class="card"><h3>Фокус</h3>
    <div class="muted small">${target ? "на «" + esc(target.title) + "»" : "глубокая работа"} — телефон экраном вниз</div>
    <div class="pills">${[25, 45, 60, 90].map((m) => `<button class="pill${m === 25 ? " primary" : ""}" data-act="focus" data-min="${m}" data-task="${target ? target.id : ""}">${m} мин</button>`).join("")}</div></div>`;
}

function busyRow(b) {
  return `<div class="task busy"><div class="time"><b>${esc(b.start)}</b>${esc(b.end)}</div>
    <div class="body"><div class="title muted">${esc(b.title)}</div><div class="meta"><span class="chip">занято</span></div></div></div>`;
}

function taskRow(t, debt = false) {
  const chips = [`<span class="chip">${esc(t.sphere_ru)}</span>`, `<span class="chip">${hm(t.duration_min)}</span>`];
  if (t.deep_work) chips.push(`<span class="chip accent">глубокая</span>`);
  if (t.importance >= 4) chips.push(`<span class="chip yellow">★${t.importance}</span>`);
  if (t.status === "done") chips.push(`<span class="chip green">✓ ${t.done_pct < 100 ? t.done_pct + "% · " : ""}+${t.xp} XP</span>`);
  if (t.status === "failed") chips.push(`<span class="chip red">не сделано</span>`);
  if (t.focus_min) chips.push(`<span class="chip">🎯 ${hm(t.focus_min)}</span>`);
  let acts = "";
  if (t.status === "planned") acts = `<button class="icon-btn go" data-act="start" data-id="${t.id}" aria-label="Начать">▶</button>`;
  if (t.open || debt) acts += `<button class="icon-btn ok" data-act="done" data-id="${t.id}" aria-label="Сделано">✓</button>
    <button class="icon-btn" data-act="more" data-id="${t.id}" aria-label="Ещё">⋯</button>`;
  return `<div class="task ${esc(t.status)}${debt ? " debt" : ""}"><div class="time"><b>${esc(t.start || "—")}</b>${esc(t.end || "")}</div>
    <div class="body"><div class="title">${esc(t.title)}</div><div class="meta">${chips.join("")}</div></div>
    <div class="acts">${acts}</div></div>`;
}

function findTask(id) {
  const d = state.data || {};
  return [...(d.tasks || []), ...(d.debts || []), ...(d.tomorrow || [])].find((t) => t.id === id);
}

function bindToday() {
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
        notify("success"); toast(`✓ +${r.xp} XP` + (r.warnings && r.warnings.length ? "\n" + r.warnings.join("\n") : ""));
      } else if (act === "more") { openTaskSheet(findTask(id)); return; }
      else if (act === "focus") { await api("focus", { json: { minutes: +el.dataset.min, task: el.dataset.task || null } }); toast("Фокус пошёл. Таймер есть и в Telegram."); }
      else if (act === "focus-stop") { await api("focus/stop", { json: {} }); }
      await load("today");
    } catch (err) { notify("error"); toast(err.message); }
  }));
}

let focusTimer;
function tickFocus() {
  clearInterval(focusTimer);
  const card = $("#focus-card");
  if (!card) return;
  const until = new Date(card.dataset.until).getTime(), start = new Date(card.dataset.start).getTime();
  const step = () => {
    const left = Math.max(0, until - Date.now());
    const m = Math.floor(left / 60000), s = Math.floor((left % 60000) / 1000);
    const el = $("#focus-left"); if (!el) return clearInterval(focusTimer);
    el.textContent = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    $("#focus-ring").style.setProperty("--p", String(1 - left / Math.max(1, until - start)));
    if (!left) { clearInterval(focusTimer); notify("success"); setTimeout(() => load("today"), 1500); }
  };
  step(); focusTimer = setInterval(step, 1000);
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
          toast(op === "fail" ? `${r.hp} HP${r.debt ? " · в долг" : ""}` : "Отменено");
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
        notify("success"); closeSheet(); toast(`✓ ${form.pct}% · +${r.xp} XP`); load("today");
      } catch (err) { toast(err.message); }
    };
  });
}

function openReportSheet(t) {
  openSheet(`<h2>Отчёт</h2><p class="muted small">${esc(t.title)}</p>
    <div class="field"><textarea id="r-report" rows="4" placeholder="Что сделано: цифры, темы, результат"></textarea></div>
    <button class="btn primary" id="r-save">Сделано</button>`, () => {
    setTimeout(() => $("#r-report").focus(), 50);
    $("#r-save").onclick = async () => {
      const report = $("#r-report").value.trim();
      if (!report) { toast("Пара слов о сделанном"); return; }
      try {
        const r = await api(`tasks/${t.id}/done`, { json: { report } });
        notify("success"); closeSheet(); toast(`✓ +${r.xp} XP`); load("today");
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
    c.innerHTML = `<button class="round" id="mic" aria-label="Голосовое">🎙</button>
      <textarea id="msg" rows="1" placeholder="Сообщение Арвиксу"></textarea>
      <button class="round send" id="send" aria-label="Отправить">↑</button>`;
    document.body.appendChild(c);
    const ta = $("#msg");
    ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = Math.min(140, ta.scrollHeight) + "px"; });
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !("ontouchstart" in window)) { e.preventDefault(); sendMessage(); } });
    $("#send").onclick = sendMessage;
    $("#mic").onclick = toggleRecord;
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

async function sendMessage() {
  const ta = $("#msg");
  const text = ta.value.trim();
  if (!text) return;
  ta.value = ""; ta.style.height = "auto"; haptic();
  state.messages.push({ id: 0, at: new Date().toISOString(), who: "me", text, channel: "web", buttons: [] });
  state.thinking = "думаю"; renderChat();
  try { await api("message", { json: { text } }); } catch (err) { toast(err.message); }
}

let recorder, chunks = [], recStart = 0;
async function toggleRecord() {
  const mic = $("#mic");
  if (recorder && recorder.state === "recording") { recorder.stop(); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const type = ["audio/ogg;codecs=opus", "audio/webm;codecs=opus", "audio/mp4"].find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
    recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    chunks = []; recStart = Date.now();
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      mic.classList.remove("rec"); mic.textContent = "🎙";
      if (Date.now() - recStart < 700) { toast("Слишком коротко"); return; }
      const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      state.messages.push({ id: 0, at: new Date().toISOString(), who: "me", text: "🎙 голосовое…", channel: "web", buttons: [] });
      state.thinking = "слушаю"; renderChat();
      try { await api("voice", { body: blob, headers: { "Content-Type": blob.type.split(";")[0] } }); } catch (err) { toast(err.message); }
    };
    recorder.start(); haptic("medium");
    mic.classList.add("rec"); mic.textContent = "■";
  } catch (err) { toast("Нет доступа к микрофону: " + err.message); }
}

// --- Заметки -----------------------------------------------------------------------------------
function renderNotes() {
  if (state.note) { renderNote(); return; }
  const list = state.notesList;
  let html = `<div class="search"><input id="n-q" type="search" placeholder="Поиск по заметкам" value="${esc(state.notesQuery || "")}"></div>
    <div class="card"><h3>Мысль в Inbox</h3><div class="field" style="margin:0"><textarea id="n-cap" rows="2" placeholder="Записать и не держать в голове"></textarea></div>
    <button class="pill primary" id="n-save" style="margin-top:8px">Записать</button></div>`;
  if (state.notesResults) {
    html += `<div class="section-title"><span>Найдено</span><button class="small" id="n-clear" style="color:var(--accent)">сбросить</button></div>`;
    html += state.notesResults.length ? state.notesResults.map((r) => `<button class="list-item" data-path="${esc(r.path)}"><span>📄</span>
      <span class="grow"><b>${esc(r.path.split("/").pop().replace(/\.md$/, ""))}</b><br><span class="muted small">${esc(r.snippet)}</span></span></button>`).join("") :
      `<div class="empty">Ничего не нашлось.</div>`;
  } else if (list) {
    const parts = state.notesDir ? state.notesDir.split("/") : [];
    html += `<div class="crumbs"><button data-dir="">Хранилище</button>${parts.map((p, i) => ` / <button data-dir="${esc(parts.slice(0, i + 1).join("/"))}">${esc(p)}</button>`).join("")}</div>`;
    html += list.dirs.map((d) => `<button class="list-item" data-dir="${esc(d.path)}"><span>📁</span><span class="grow">${esc(d.name)}</span><span class="muted">›</span></button>`).join("");
    html += list.files.map((f) => `<button class="list-item" data-path="${esc(f.path)}"><span>📄</span><span class="grow">${esc(f.name)}</span>
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

async function openNote(path) {
  try {
    state.note = await api("note?path=" + encodeURIComponent(path));
    renderNote(); window.scrollTo(0, 0);
    if (TG) { TG.BackButton.show(); TG.BackButton.onClick(closeNote); }
  } catch (err) { toast(err.message); }
}
function closeNote() {
  state.note = null; if (TG) { TG.BackButton.offClick(closeNote); TG.BackButton.hide(); }
  renderNotes();
}

function renderNote() {
  const n = state.note;
  view.innerHTML = `<div class="crumbs"><button id="n-back">‹ Назад</button> <span>${esc(n.path)}</span></div>
    <div class="card md">${markdown(n.text)}</div>`;
  $("#n-back").onclick = closeNote;
  view.querySelectorAll("[data-wiki]").forEach((a) => a.addEventListener("click", async (e) => {
    e.preventDefault();
    try {
      const r = await api("notes/search?q=" + encodeURIComponent(a.dataset.wiki));
      const name = a.dataset.wiki.toLowerCase();
      const hit = r.results.find((x) => x.path.toLowerCase().endsWith("/" + name + ".md") || x.path.toLowerCase() === name + ".md") || r.results[0];
      if (hit) openNote(hit.path); else toast("Заметка не найдена");
    } catch (err) { toast(err.message); }
  }));
}

/* Markdown → HTML. Сначала экранирование, потом разметка: из заметки в страницу не попадёт ни один тег. */
function markdown(src) {
  src = String(src || "").replace(/^---\n[\s\S]*?\n---\n?/, "");
  const blocks = [];
  src = src.replace(/```[^\n]*\n([\s\S]*?)```/g, (_, code) => { blocks.push(`<pre><code>${esc(code)}</code></pre>`); return `\u0000${blocks.length - 1}\u0000`; });
  const inline = (s) => esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/__([^_]+)__/g, "<b>$1</b>")
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<i>$2</i>")
    .replace(/==([^=]+)==/g, "<mark>$1</mark>")
    .replace(/!?\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]/g, (_, name, alias) => `<a href="#" data-wiki="${name.trim()}">${alias || name}</a>`)
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  const out = [];
  let list = null;
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const line of src.split("\n")) {
    let m;
    if ((m = line.match(/^\u0000(\d+)\u0000$/))) { closeList(); out.push(blocks[+m[1]]); }
    else if ((m = line.match(/^(#{1,6})\s+(.*)/))) { closeList(); const l = Math.min(4, m[1].length); out.push(`<h${l}>${inline(m[2])}</h${l}>`); }
    else if ((m = line.match(/^\s*[-*+]\s+\[( |x|X)\]\s+(.*)/))) { if (list !== "ul") { closeList(); out.push("<ul>"); list = "ul"; } out.push(`<li>${m[1].trim() ? "☑" : "☐"} ${inline(m[2])}</li>`); }
    else if ((m = line.match(/^\s*[-*+]\s+(.*)/))) { if (list !== "ul") { closeList(); out.push("<ul>"); list = "ul"; } out.push(`<li>${inline(m[1])}</li>`); }
    else if ((m = line.match(/^\s*\d+[.)]\s+(.*)/))) { if (list !== "ol") { closeList(); out.push("<ol>"); list = "ol"; } out.push(`<li>${inline(m[1])}</li>`); }
    else if ((m = line.match(/^>\s?(.*)/))) { closeList(); out.push(`<blockquote>${inline(m[1].replace(/^\[!\w+\]\s*/, ""))}</blockquote>`); }
    else if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { closeList(); out.push("<hr>"); }
    else if (/^\|.*\|\s*$/.test(line)) {
      if (list !== "table") { closeList(); out.push("<table>"); list = "table"; }
      if (/^\|[\s:|-]+\|\s*$/.test(line)) continue;
      out.push(`<tr>${line.trim().slice(1, -1).split("|").map((c) => `<td>${inline(c.trim())}</td>`).join("")}</tr>`);
    }
    else if (!line.trim()) { closeList(); }
    else { closeList(); out.push(`<p>${inline(line)}</p>`); }
  }
  closeList();
  return out.join("\n");
}

// --- Прогресс ----------------------------------------------------------------------------------
function renderProgress() {
  const h = state.history;
  let html = "";
  if (!h) html = `<div class="empty">Загружаю…</div>`;
  else if (h.gentle) html = `<div class="card note-card">Сегодня без цифр. Прогресс подождёт — восстановление тоже часть плана.</div>`;
  else {
    const w = h.week;
    html += `<div class="card"><h3>Неделя</h3>
      <div class="row"><span>Сделано</span><b>${hm(w.productive_min)} из ${hm(w.budget_min)}</b></div><div class="bar"><i style="width:${Math.min(100, 100 * w.productive_min / Math.max(1, w.budget_min))}%"></i></div>
      <div class="row" style="margin-top:6px"><span>Глубокая работа</span><b>${hm(w.deep_min)} из ${hm(w.deep_budget_min)}</b></div><div class="bar deep"><i style="width:${Math.min(100, 100 * w.deep_min / Math.max(1, w.deep_budget_min))}%"></i></div>
      <div class="pills" style="margin-top:10px">${w.quotas.map((q) => `<span class="chip ${q.done >= q.need ? "green" : ""}">${esc(q.label)} ${q.done}/${q.need}</span>`).join("")}</div></div>`;
    html += chartCard("Выполнение, %", h.days, (d) => d.completion, 100, "var(--accent)");
    html += chartCard("Сон, часы", h.days, (d) => (d.sleep_min == null ? null : d.sleep_min / 60), 10, "var(--accent-2)", 7.5);
    html += chartCard("XP за день", h.days, (d) => d.xp, null, "var(--warn)");
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
    ${TG ? `<button class="btn" id="install">📲 Установить на телефон</button><p class="muted small">Откроется в браузере. Там — меню ⋮ → «Установить приложение»: появится иконка Арвикса, как у обычного приложения.</p>` :
    `<p class="muted small">Установлено как приложение? Меню браузера ⋮ → «Установить приложение» / «На экран Домой».</p>
     <button class="btn danger" id="logout">Отвязать это устройство</button>`}
    <p class="muted small">Версия ${esc((state.data && state.data.app_version) || "")}</p></div>`;
  view.innerHTML = html;
  $("#install") && ($("#install").onclick = async () => {
    try { const r = await api("pair"); if (!r.url) { toast("На сервере не задан адрес приложения"); return; } TG.openLink(r.url); } catch (err) { toast(err.message); }
  });
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

if (!TG && !token()) renderLogin();
else {
  const start = (new URLSearchParams(location.search).get("tab")) || (TG && TG.initDataUnsafe && TG.initDataUnsafe.start_param) || "today";
  setTab(["today", "chat", "notes", "progress"].includes(start) ? start : "today");
  stream();
}
