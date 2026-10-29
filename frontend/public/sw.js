// Service worker (FR-PW1, FR-PW3).
// - Makes the app installable, and opens it without a connection: pages are fetched from the
//   network first, and the last good copy of the app is used when there is none.
// - Caches only the app's static files. API responses are never cached here: the app keeps the
//   user's offline data itself, in IndexedDB, and sign-out wipes both (FR-PW12).
const VERSION = "v4";
const SHELL_CACHE = `sces-shell-${VERSION}`;
const ASSET_CACHE = "sces-assets";
const APP = "/index.html";
const SHELL = ["/", "/offline.html", "/offline.css", "/offline.js", "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png"];

// The first visit loads the app before this worker controls the page, so its built files never
// pass through here: read them from the page itself and cache them now, or the app would not
// open offline after a first visit.
async function cacheBuiltAssets() {
  const html = await (await fetch("/", { cache: "no-store" })).text();
  const assets = [...new Set(html.match(/\/assets\/[^"'\s>]+/g) || [])];
  const cache = await caches.open(ASSET_CACHE);
  await cache.addAll(assets);
  await (await caches.open(SHELL_CACHE)).put(APP, new Response(html, { headers: { "Content-Type": "text/html" } }));
}

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL)).then(cacheBuiltAssets));
  self.skipWaiting();
});

// Sign-out deletes every cache (FR-PW12). The app's own files hold nothing of the user's, so
// they are put back, and the sign-in screen still opens without a connection.
self.addEventListener("message", (event) => {
  if (event.data?.type === "recache") {
    event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL)).then(cacheBuiltAssets).catch(() => undefined));
  }
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
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            void caches.open(SHELL_CACHE).then((cache) => cache.put(APP, copy));
          }
          return response;
        })
        .catch(
          async () =>
            (await caches.match(APP, { ignoreVary: true })) ||
            (await caches.match("/", { ignoreVary: true })) ||
            caches.match("/offline.html", { ignoreVary: true }),
        ),
    );
    return;
  }
  if (url.pathname.startsWith("/assets/")) {
    // Built assets have content hashes in their names, so a cached copy never goes stale.
    event.respondWith(
      caches.open(ASSET_CACHE).then(async (cache) => {
        // ignoreVary: the copy cached at install was fetched with other headers than the page's.
        const cached = await cache.match(request, { ignoreVary: true });
        if (cached) return cached;
        const response = await fetch(request);
        if (response.ok) cache.put(request, response.clone());
        return response;
      }),
    );
  }
});

// Web Push (FR-N3): the server sends only the notice's one-line text and where it leads (FR-N7).
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = {};
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "SCES", {
      body: data.body || "",
      tag: data.tag,
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      data: { url: typeof data.url === "string" && data.url.startsWith("/") ? data.url : "/notifications" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || "/notifications", self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const open = windows.find((w) => w.url.startsWith(self.location.origin));
      if (open) return open.focus().then(() => open.navigate(target));
      return self.clients.openWindow(target);
    }),
  );
});
