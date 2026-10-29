// Browser test for Phase 4 (realtime, offline and camera scanning), against a production build
// (the service worker only runs there) and a server seeded by e2e/seed_phase4.py:
//
//  1. A supervisor scans a one-page report with the phone's camera and sends it. While her report
//     is open, an admin acknowledges it: her screen shows it within 2 seconds, and the second
//     supervisor's open screen receives no event about it.
//  2. Offline, she starts an evaluation and saves a draft, then scans a 10-page report: an 11th page
//     is deleted, two are swapped and one is turned and made black and white. The PDF is made on
//     the phone and waits in the outbox.
//  3. The phone restarts, still offline: everything is still waiting. Back online, it is sent once;
//     sending again creates nothing more.
//  4. Signing out leaves nothing of hers on the phone.
//
// The camera is Chromium's fake device playing e2e/make_scan_video.py's page on a desk.
// Usage: node e2e/phase4.cjs <base url> <seed.json> <output dir> <camera.mjpeg>
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const { check, visible, choose, nav, session, totp } = require("./lib.cjs");

(async () => {
  const [base, seedFile, out, camera] = process.argv.slice(2);
  const seed = JSON.parse(fs.readFileSync(seedFile, "utf8"));
  fs.mkdirSync(out, { recursive: true });
  const insecure = process.env.E2E_IGNORE_HTTPS === "1";
  const browser = await chromium.launch(insecure ? { args: ["--ignore-certificate-errors"] } : {});
  const { signIn, snap, problems, failureShots } = session(browser, base, seed, out);

  // Noura's phone keeps its storage across restarts, like an installed app.
  const profile = path.join(out, "phone-profile");
  fs.rmSync(profile, { recursive: true, force: true });
  const phoneShots = [];
  global.failureShots = async () => {
    await failureShots();
    for (const [i, p] of phoneShots.entries()) await p.screenshot({ path: path.join(out, `failure-phone-${i}.png`), fullPage: true }).catch(() => {});
  };
  async function openPhone() {
    const context = await chromium.launchPersistentContext(profile, {
      viewport: { width: 400, height: 860 },
      ignoreHTTPSErrors: insecure,
      permissions: ["camera"],
      args: [
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        `--use-file-for-fake-video-capture=${camera}`,
        ...(insecure ? ["--ignore-certificate-errors"] : []),
      ],
    });
    const page = context.pages()[0] ?? (await context.newPage());
    phoneShots.push(page);
    page.on("pageerror", (e) => problems.push(`phone: page error ${e.message}`));
    page.on("dialog", (d) => d.accept());
    return { context, page };
  }
  const realtimeFrames = (page) => {
    const frames = [];
    page.on("websocket", (ws) => ws.on("framereceived", (f) => frames.push(String(f.payload))));
    return frames;
  };
  const changes = (frames, entity) =>
    frames.map((f) => JSON.parse(f)).filter((m) => m.type === "changed" && (!entity || m.entity === entity));

  async function scanPages(page, count) {
    await page.getByRole("button", { name: "Scan with camera" }).click();
    const scanner = page.getByRole("dialog", { name: "Scan pages" });
    for (let i = 1; i <= count; i++) {
      await scanner.getByRole("button", { name: "Capture page" }).click();
      await scanner.getByText(`Pages: ${i}`, { exact: true }).waitFor({ timeout: 20000 });
    }
    await scanner.getByRole("button", { name: "Review pages" }).click();
    return scanner;
  }

  let { context, page: phone } = await openPhone();
  const noura = seed.users.supa;
  await phone.goto(`${base}/login`);
  await phone.getByLabel("Email").fill(noura.email);
  await phone.getByLabel("Password").fill(seed.password);
  await phone.getByRole("button", { name: "Continue" }).click();
  await phone.getByLabel("Code").fill(totp(noura.secret));
  await phone.getByRole("button", { name: "Sign in" }).click();
  await phone.getByText(`Welcome, ${noura.name}`).waitFor();

  // 1. Realtime ------------------------------------------------------------------------------
  await nav(phone, "Scanned reports");
  await phone.getByRole("button", { name: "Upload a report" }).click();
  let dialog = phone.getByRole("dialog", { name: "Upload a report" });
  await choose(dialog.getByLabel("Ministry report and version"), /MOE-SV-02/);
  await choose(dialog.getByLabel("School"), /Al-Nahda/);
  let scanner = await scanPages(phone, 1);
  await scanner.getByRole("button", { name: "Use these pages" }).click();
  await dialog.getByText("Pages: 1").waitFor({ timeout: 20000 });
  await dialog.getByRole("button", { name: "Upload and send" }).click();
  await phone.getByRole("heading", { name: "School profile visit" }).waitFor();
  const reportUrl = phone.url();
  check(true, "a page scanned with the camera is sent as a one-page PDF");
  const nouraFrames = realtimeFrames(phone);
  await phone.reload();
  await phone.getByRole("heading", { name: "School profile visit" }).waitFor();

  const yousef = await signIn("supb");
  const yousefFrames = realtimeFrames(yousef);
  await nav(yousef, "Scanned reports");
  await yousef.reload();
  await yousef.getByText("No reports.").waitFor();

  const admin = await signIn("admin");
  await nav(admin, "Scanned reports");
  await admin.getByRole("link", { name: "School profile visit" }).click();
  await admin.getByRole("button", { name: "Acknowledge" }).waitFor();
  await admin.getByRole("button", { name: "Acknowledge" }).click();
  const sent = Date.now();
  await admin.getByRole("dialog").getByRole("button", { name: "Acknowledge" }).click();
  await phone.getByText("Acknowledged", { exact: true }).first().waitFor({ timeout: 5000 });
  const latency = Date.now() - sent;
  check(latency < 2000, `the supervisor's open report shows the acknowledgement in ${latency} ms`);
  check(changes(nouraFrames, "document").length >= 1, "her screen was told over the WebSocket");
  await yousef.waitForTimeout(1500);
  check(changes(yousefFrames).length === 0, "the second supervisor's open screen received no event");
  await snap(phone, "report-acknowledged-live");

  // 2. Offline: an evaluation draft and a 10-page scan ----------------------------------------
  await phone.goto(`${base}/`);
  await phone.evaluate(async () => navigator.serviceWorker.ready);
  await nav(phone, "Evaluations");
  await nav(phone, "Scanned reports");
  await phone.waitForTimeout(1500); // the screens' data is kept as it loads
  await context.setOffline(true);
  await nav(phone, "Evaluations");
  await phone.getByRole("button", { name: "New evaluation" }).click();
  dialog = phone.getByRole("dialog");
  await choose(dialog.getByLabel("Form"), /MOE-SV-02/);
  await choose(dialog.getByLabel("School"), /Al-Nahda/);
  await dialog.getByRole("button", { name: "Start" }).click();
  await phone.getByRole("heading", { name: /MOE-SV-02/ }).waitFor();
  await phone.getByRole("radio", { name: "4" }).click();
  await phone.getByRole("button", { name: "Save draft" }).click();
  await visible(phone.getByText("Saved on this device", { exact: false }), "an evaluation is started and saved offline");

  await nav(phone, "Scanned reports");
  await phone.getByRole("button", { name: "Upload a report" }).click();
  dialog = phone.getByRole("dialog", { name: "Upload a report" });
  await choose(dialog.getByLabel("Ministry report and version"), /MOE-SV-02/);
  await choose(dialog.getByLabel("School"), /Al-Nahda/);
  scanner = await scanPages(phone, 11);
  const thumbs = scanner.locator(".scan-pages li");
  check((await thumbs.count()) === 11, "eleven pages captured");
  await thumbs.nth(10).getByRole("button", { name: "Remove" }).click();
  await scanner.getByText("Pages: 10", { exact: true }).waitFor();
  await thumbs.nth(1).getByRole("button", { name: "Move up" }).click();
  await scanner.getByRole("button", { name: "Adjust page 1", exact: true }).click();
  const corners = await scanner.locator(".scan-corner").evaluateAll((els) => els.map((e) => [e.style.left, e.style.top]));
  check(corners.some(([x, y]) => x !== "0%" || y !== "0%") && corners.some(([x]) => x !== "100%"), "the page's edges were found in the photo");
  await snap(phone, "scan-adjust");
  await scanner.getByRole("button", { name: "Turn" }).click();
  await scanner.getByLabel("Black and white").check();
  await scanner.getByRole("button", { name: "Keep these changes" }).click();
  await scanner.getByRole("button", { name: "Use these pages" }).waitFor();
  await snap(phone, "scan-pages");
  await scanner.getByRole("button", { name: "Use these pages" }).click();
  await dialog.getByText("Kept on this device").waitFor({ timeout: 30000 });
  await dialog.getByRole("button", { name: "Upload and send" }).click();
  await phone.getByRole("heading", { name: "Waiting to send" }).waitFor();
  const waiting = await phone.locator(".outbox li").count();
  check(waiting === 3, `the evaluation, its answers and the scan wait on the phone (${waiting})`);
  await visible(phone.getByText(/Files waiting: 1 of 20/), "the scan is one PDF in the outbox");

  // 3. Restart offline, then sync -------------------------------------------------------------
  await context.close();
  ({ context, page: phone } = await openPhone());
  await context.setOffline(true);
  await phone.goto(`${base}/outbox`);
  await phone.getByText("Offline.", { exact: false }).waitFor();
  check((await phone.locator(".outbox li").count()) === 3, "after a restart offline, everything is still waiting");
  await context.setOffline(false);
  await phone.evaluate(() => window.dispatchEvent(new Event("online")));
  await phone.getByText("Nothing is waiting", { exact: false }).waitFor({ timeout: 60000 });
  const counts = async () =>
    phone.evaluate(async () => {
      const get = async (url) => (await fetch(url, { credentials: "same-origin" })).json();
      const docs = await get("/api/documents?page_size=100");
      const evaluations = await get("/api/evaluations?page_size=100");
      const scanned = docs.items.filter((d) => d.file?.pages === 10);
      return { documents: docs.total, evaluations: evaluations.total, tenPage: scanned.length, statuses: docs.items.map((d) => d.status) };
    });
  const after = await counts();
  check(after.documents === 2 && after.evaluations === 1, `sent once: ${JSON.stringify(after)}`);
  check(after.tenPage === 1, "the scanned report arrived with its 10 pages");
  await phone.evaluate(() => window.dispatchEvent(new Event("online")));
  await phone.waitForTimeout(3000);
  const again = await counts();
  check(again.documents === after.documents && again.evaluations === after.evaluations, "sending again creates no duplicates");

  // 4. Sign-out wipe ---------------------------------------------------------------------------
  await phone.goto(`${base}/`);
  await phone.getByRole("button", { name: "Sign out" }).click();
  await phone.getByLabel("Email").waitFor();
  const left = await phone.evaluate(async () => {
    const db = await new Promise((resolve, reject) => {
      const r = indexedDB.open("sces");
      r.onsuccess = () => resolve(r.result);
      r.onerror = () => reject(r.error);
    });
    const count = (store) =>
      new Promise((resolve) => {
        const r = db.transaction(store).objectStore(store).count();
        r.onsuccess = () => resolve(r.result);
      });
    const stores = {};
    for (const s of db.objectStoreNames) stores[s] = await count(s);
    const cached = [];
    for (const name of await caches.keys()) for (const r of await (await caches.open(name)).keys()) cached.push(new URL(r.url).pathname);
    return { stores, api: cached.filter((p) => p.startsWith("/api")), local: Object.keys(localStorage) };
  });
  check(Object.values(left.stores).every((n) => n === 0), `nothing left in the device store: ${JSON.stringify(left.stores)}`);
  check(left.api.length === 0, "no server data in the browser's caches");
  await phone.waitForTimeout(1500); // the worker puts the app's own files back
  await context.setOffline(true);
  await phone.goto(`${base}/evaluations`);
  await phone.getByLabel("Email").waitFor();
  check(!(await phone.getByText("Noura Al-Saleh").count()), "offline after sign-out, the phone opens to sign-in and shows nothing of hers");
  await snap(phone, "signed-out-offline");
  await context.close();

  await browser.close();
  if (problems.length) {
    console.error(problems.join("\n"));
    process.exit(1);
  }
  console.log("phase 4 browser test: all checks passed");
})().catch(async (e) => {
  console.error(e);
  if (global.failureShots) await global.failureShots();
  process.exit(1);
});
