// Shared helpers for the browser tests: authenticator codes, checks, and signing in.
const crypto = require("crypto");
const path = require("path");

function base32(s) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const c of s.replace(/\s|=/g, "").toUpperCase()) bits += alphabet.indexOf(c).toString(2).padStart(5, "0");
  const bytes = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}

function totp(secret) {
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const h = crypto.createHmac("sha1", base32(secret)).update(buf).digest();
  const o = h[h.length - 1] & 15;
  return ((h.readUInt32BE(o) & 0x7fffffff) % 1e6).toString().padStart(6, "0");
}

function check(condition, message) {
  if (!condition) throw new Error(`check failed: ${message}`);
  console.log(`ok - ${message}`);
}

// Waits up to 10 seconds for the element, since screens refresh after each action.
async function visible(locator, message) {
  await locator.first().waitFor({ timeout: 10000 });
  console.log(`ok - ${message}`);
}

// Selects the first option whose text matches, once the screen's data has arrived.
async function choose(select, pattern) {
  let options = [];
  let found;
  for (let i = 0; i < 40 && !found; i++) {
    if (i) await new Promise((r) => setTimeout(r, 250));
    options = await select.locator("option").evaluateAll((els) => els.map((o) => ({ value: o.value, text: o.textContent })));
    found = options.find((o) => pattern.test(o.text));
  }
  if (!found) throw new Error(`no option matching ${pattern} in ${JSON.stringify(options)}`);
  await select.selectOption(found.value);
}

// D/MM/YYYY for a day offset from today, in Kuwait time.
function kuwaitDate(offsetDays) {
  const d = new Date(Date.now() + 3 * 3600 * 1000 + offsetDays * 86400 * 1000);
  return `${d.getUTCDate()}/${String(d.getUTCMonth() + 1).padStart(2, "0")}/${d.getUTCFullYear()}`;
}

/** A browser session per user, with page errors and CSP violations collected in `problems`. */
function session(browser, base, seed, out) {
  const problems = [];
  const pages = [];
  const usedSteps = {};
  let shot = 0;
  async function signIn(key, viewport = { width: 1280, height: 900 }) {
    // E2E_IGNORE_HTTPS=1 accepts a self-signed certificate, for example Caddy's for localhost.
    const context = await browser.newContext({ viewport, acceptDownloads: true, ignoreHTTPSErrors: process.env.E2E_IGNORE_HTTPS === "1" });
    const page = await context.newPage();
    pages.push(page);
    page.on("pageerror", (e) => problems.push(`${key}: page error ${e.message}`));
    page.on("console", (m) => /Content Security Policy|Refused to/.test(m.text()) && problems.push(`${key}: CSP ${m.text()}`));
    page.on("dialog", (d) => d.accept());
    const user = seed.users[key];
    // A code works once (replay protection), so a second sign-in waits for the next one.
    if (usedSteps[key] === Math.floor(Date.now() / 30000)) await page.waitForTimeout(30000 - (Date.now() % 30000) + 500);
    usedSteps[key] = Math.floor(Date.now() / 30000);
    await page.goto(`${base}/login`);
    await page.getByLabel("Email").fill(user.email);
    await page.getByLabel("Password").fill(seed.password);
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByLabel("Code").fill(totp(user.secret));
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.getByText(`Welcome, ${user.name}`).waitFor();
    return page;
  }
  const snap = (page, name) => page.screenshot({ path: path.join(out, `${String(++shot).padStart(2, "0")}-${name}.png`), fullPage: true });
  const failureShots = async () => {
    for (const [i, p] of pages.entries()) await p.screenshot({ path: path.join(out, `failure-${i}.png`), fullPage: true }).catch(() => {});
  };
  return { signIn, snap, problems, failureShots };
}

const nav = (page, name) => page.getByRole("navigation").getByRole("link", { name, exact: true }).click();

module.exports = { totp, check, visible, choose, kuwaitDate, session, nav };
