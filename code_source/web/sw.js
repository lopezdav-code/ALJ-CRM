const CACHE_NAME = "alj-escalade-v2";
const ASSETS_TO_CACHE = [
  "/competitions",
  "/annuaire/competitions.html",
  "/annuaire/index.html",
  "/annuaire/logo.png",
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

// Interception des requêtes : Network first pour les APIs, Cache first pour les assets
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // 1. Les requêtes d'API, OAuth ou POST vont directement sur le réseau
  if (
    event.request.method !== "GET" ||
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/webhooks/") ||
    url.hostname.includes("googleapis.com") ||
    url.hostname.includes("accounts.google.com")
  ) {
    return;
  }

  // 2. Stratégie Cache-First avec repli Réseau pour les ressources PWA
  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }
      return fetch(event.request).then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200) {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseToCache);
          });
        }
        return networkResponse;
      }).catch(() => {
        // En cas de panne totale réseau
        return caches.match("/competitions");
      });
    })
  );
});
