const CACHE_NAME = "smart-speaker-web-v1";
const STATIC_ASSETS = [
  "/",
  "/register",
  "/static/css/style.css",
  "/static/js/app.js",
  "/static/js/pages/AuthPage.js",
  "/static/js/pages/DashboardPage.js",
  "/static/js/components/alarms.js",
  "/static/js/components/lists.js",
  "/static/js/components/media.js",
  "/static/js/components/profile.js",
  "/static/js/components/timers.js",
  "/static/js/services/api.js",
  "/static/js/services/utils.js",
  "/static/image/logo.png",
  "/static/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key)),
      ),
    ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;

  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/api/")) {
    event.respondWith(fetch(event.request));
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request)
        .then((response) => {
          if (
            response &&
            response.ok &&
            event.request.destination &&
            ["document", "style", "script", "image"].includes(
              event.request.destination,
            )
          ) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
          }
          return response;
        })
        .catch(() => caches.match("/"));
    }),
  );
});
