// PWA shell check (FR-PW1, FR-PW3): manifest, service worker, the app opening offline, and no API caching.
// Usage: node e2e/pwa.cjs https://sces.example.org   (E2E_IGNORE_HTTPS=1 for a self-signed certificate)
const { chromium } = require("playwright");

(async () => {
  const base = process.argv[2];
  // Service workers need a trusted certificate, so a self-signed one is accepted at the browser level too.
  const browser = await chromium.launch(process.env.E2E_IGNORE_HTTPS === "1" ? { args: ["--ignore-certificate-errors"] } : {});
  const context = await browser.newContext({ ignoreHTTPSErrors: process.env.E2E_IGNORE_HTTPS === "1" });
  const page = await context.newPage();
  page.on("console", (m) => /Content Security Policy|Refused to/.test(m.text()) && console.log("CSP VIOLATION", m.text()));
  await page.goto(`${base}/login`);
  const manifest = await page.evaluate(async () => {
    const href = document.querySelector('link[rel="manifest"]').href;
    const response = await fetch(href);
    return { status: response.status, body: await response.json() };
  });
  console.log("manifest:", manifest.status, manifest.body.name, manifest.body.icons.length, "icons");
  const scope = await page.evaluate(async () => (await navigator.serviceWorker.ready).scope);
  console.log("service worker active for", scope);
  await page.reload();
  const cached = await page.evaluate(async () => {
    const names = await caches.keys();
    const urls = [];
    for (const name of names) for (const r of await (await caches.open(name)).keys()) urls.push(new URL(r.url).pathname);
    return urls;
  });
  console.log("cached:", cached.sort().join(" "));
  console.log("api responses cached:", cached.some((u) => u.startsWith("/api/")));
  await context.setOffline(true);
  await page.goto(`${base}/schools`).catch(() => undefined);
  // The app itself opens offline (its sign-in screen here, as nobody is signed in).
  console.log("app opens offline:", await page.getByRole("heading", { name: "Sign in" }).isVisible());
  // A browser that never loaded the app gets the bilingual offline page instead.
  const fresh = await browser.newContext({ ignoreHTTPSErrors: process.env.E2E_IGNORE_HTTPS === "1" });
  const other = await fresh.newPage();
  await fresh.setOffline(true);
  await other.goto(`${base}/`).catch(() => undefined);
  await other.waitForLoadState().catch(() => undefined);
  // Chromium's own error page may still be loading, so ask only whether the app is there.
  const appThere = await other.getByRole("heading", { name: "Sign in" }).count().catch(() => 0);
  console.log("never-visited browser offline: no app, as expected:", appThere === 0);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
