// Online-only service worker (Phase 1 PWA shell).
// - Makes the app installable and shows a bilingual page when there is no connection.
// - Caches only the app's static files. API responses are never cached, so no
//   personal data is stored on the device (FR-D16). Offline work arrives in Phase 4.
const VERSION = "v1";
const SHELL_CACHE = `sces-shell-${VERSION}`;
const ASSET_CACHE = "sces-assets";
const SHELL = ["/offline.html", "/offline.css", "/offline.js", "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("sces-shell-") && k !== SHELL_CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) {
    return; // straight to the network
  }
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match("/offline.html")));
    return;
  }
  if (url.pathname.startsWith("/assets/")) {
    // Built assets have content hashes in their names, so a cached copy never goes stale.
    event.respondWith(
      caches.open(ASSET_CACHE).then(async (cache) => {
        const cached = await cache.match(request);
        if (cached) return cached;
        const response = await fetch(request);
        if (response.ok) cache.put(request, response.clone());
        return response;
      }),
    );
  }
});
