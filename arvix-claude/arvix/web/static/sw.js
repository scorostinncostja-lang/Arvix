/* Оболочка приложения в кэше — открывается мгновенно и без сети; данные (/api) — всегда из сети.
 * «Поделиться → Arvix» (share_target в манифесте): файлы кладутся в кэш SHARE, страница
 * забирает их и отправляет с ключом — у service worker ключа нет и не должно быть. */
const CACHE = "arvix-v19";  // Вкладка «Обучение».
const SHARE = "arvix-share";
const SHELL = ["/", "/index.html", "/app.css", "/app.js", "/manifest.webmanifest", "/icon.svg", "/icon-192.png", "/icon-512.png", "/icon-maskable-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE && k !== SHARE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

async function receiveShare(request) {
  const form = await request.formData();
  const cache = await caches.open(SHARE);
  const stamp = Date.now();
  let i = 0;
  for (const file of form.getAll("files")) {
    if (!(file instanceof File)) continue;
    await cache.put(`/share/${stamp}/${i++}`, new Response(file, { headers: {
      "Content-Type": file.type || "application/octet-stream", "X-File-Name": encodeURIComponent(file.name || "файл") } }));
  }
  const text = [form.get("title"), form.get("text"), form.get("url")].filter(Boolean).join("\n").trim();
  if (text) await cache.put(`/share/${stamp}/text`, new Response(text));
  return Response.redirect("/?tab=chat&shared=1", 303);
}

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method === "POST" && url.origin === location.origin && url.pathname === "/share") {
    e.respondWith(receiveShare(e.request));
    return;
  }
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // Сначала сеть (свежая версия после выкатки), без сети — кэш.
  e.respondWith(
    fetch(e.request).then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(e.request, copy));
      return res;
    }).catch(() => caches.match(e.request).then((hit) => hit || caches.match("/index.html")))
  );
});
