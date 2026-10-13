// Doit correspondre à <meta name="alj-web-version"> de competitions.html, index.html et bureau/*.html
const CACHE_NAME = "alj-escalade-v21";
const ASSETS_TO_CACHE = [
  "/competitions",
  "/index",
  "/annuaire/competitions.html",
  "/annuaire/index.html",
  "/annuaire/logo.png",
  "/bureau/",
  "/bureau/adherents",
  "/bureau/communications",
  "/bureau/competitions",
  "/bureau/planning",
  "/bureau/outils",
  "/bureau/parametres",
  "/static-web/alj.css",
  "/static-web/alj-core.js",
  "/static-web/alj-shell.js",
  "/static-web/alj-vue.js",
  "/static-web/alj-members.js",
  "/static-web/alj-filters.js",
  "/static-web/alj-firebase.js",
  "/manifest.webmanifest",
  "https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js",
  "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth-compat.js",
  "https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore-compat.js"
];

// Installation : mise en cache des ressources statiques
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE).catch((err) => {
        console.warn("⚠️ [SW] Pré-mise en cache partielle :", err);
      });
    })
  );
  self.skipWaiting();
});

// Activation : nettoyage des anciens caches
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

// Request interception:
// - same-origin pages and assets: network first, cache as offline fallback, so a
//   deploy reaches clients without depending on a CACHE_NAME bump (a stale shared
//   module missing a newly imported export breaks the whole page);
// - cross-origin versioned assets (Firebase SDK): cache first, their content never changes.
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // 1. API, OAuth and non-GET requests go straight to the network
  if (
    event.request.method !== "GET" ||
    url.pathname === "/runtime-config.js" ||   // runtime configuration: never cached
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/webhooks/") ||
    url.hostname.includes("googleapis.com") ||
    url.hostname.includes("accounts.google.com")
  ) {
    return;
  }

  const putInCache = (networkResponse) => {
    if (networkResponse && networkResponse.status === 200) {
      const responseToCache = networkResponse.clone();
      caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseToCache));
    }
    return networkResponse;
  };

  // 2. Same origin: network first, cache fallback when offline
  if (url.origin === self.location.origin) {
    event.respondWith(
      fetch(event.request)
        .then(putInCache)
        .catch(() =>
          caches.match(event.request).then((cachedResponse) => cachedResponse || caches.match("/competitions"))
        )
    );
    return;
  }

  // 3. Cross origin: cache first, network fallback
  event.respondWith(
    caches.match(event.request).then((cachedResponse) => cachedResponse || fetch(event.request).then(putInCache))
  );
});
