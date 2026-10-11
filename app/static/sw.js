/* Questly service worker — enables PWA installability and offline resilience */
"use strict";

const CACHE_NAME = "questly-v1";

const PRECACHE_URLS = [
  "/static/css/style.css",
  "/static/js/app.js",
  "/static/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-maskable-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/icon-maskable-512.png",
  "/static/icons/icon.svg",
  "/static/icons/apple-touch-icon.png",
  "/static/icons/favicon-32.png"
];

const OFFLINE_HTML = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#7c4dff">
  <title>Offline &middot; Questly</title>
  <link rel="stylesheet" href="/static/css/style.css">
</head>
<body class="gate">
  <div class="blobs" aria-hidden="true"><span></span><span></span><span></span></div>
  <main class="page">
    <section class="empty empty--big">
      <div class="empty__emoji">&#128268;</div>
      <h1>Offline</h1>
      <p>Questly couldn't reach your server. Check your connection and try again.</p>
      <button class="btn btn--primary" onclick="window.location.reload()">Try again</button>
    </section>
  </main>
</body>
</html>`;

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async function (cache) {
      await Promise.all(
        PRECACHE_URLS.map(function (url) {
          return cache.add(url).catch(function (err) {
            console.warn("Precache failed for", url, err);
          });
        })
      );
      return self.skipWaiting();
    })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.map(function (key) {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(function () {
      return self.clients.claim();
    })
  );
});

self.addEventListener("fetch", function (event) {
  // Only handle GET requests; never intercept POST/PUT/DELETE mutations
  if (event.request.method !== "GET") return;

  const url = new URL(event.request.url);

  // HTML page navigation: network-first with offline fallback
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(function () {
        return caches.match(event.request).then(function (cached) {
          return (
            cached ||
            new Response(OFFLINE_HTML, {
              headers: { "Content-Type": "text/html; charset=utf-8" }
            })
          );
        });
      })
    );
    return;
  }

  // Static assets: cache-first with network fallback and background cache update
  if (url.origin === self.location.origin && url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(event.request).then(function (cached) {
        if (cached) {
          // Refresh cache in the background
          fetch(event.request)
            .then(function (response) {
              if (response && response.status === 200) {
                const clone = response.clone();
                caches.open(CACHE_NAME).then(function (cache) {
                  cache.put(event.request, clone);
                });
              }
            })
            .catch(function () {
              /* ignore background fetch failures */
            });
          return cached;
        }

        return fetch(event.request).then(function (response) {
          if (response && response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(function (cache) {
              cache.put(event.request, clone);
            });
          }
          return response;
        });
      })
    );
    return;
  }

  // Other GET requests: network-first with cache fallback
  event.respondWith(
    fetch(event.request).catch(function () {
      return caches.match(event.request);
    })
  );
});
