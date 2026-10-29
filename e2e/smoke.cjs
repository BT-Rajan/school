// Browser smoke test for Phase 1 (section 19, "Browser end-to-end").
// Accepts a District Admin invitation with an authenticator app, saves recovery codes,
// creates a cluster and a school, switches to Arabic mid-form (input must survive),
// signs out, and signs back in. Screenshots go to the output folder.
//
// Usage, against a freshly bootstrapped server with one admin invitation:
//   npm install --no-save playwright && npx playwright install chromium
//   node e2e/smoke.cjs "<invitation link>" ./e2e-output
const { chromium } = require("playwright");
const crypto = require("crypto");

function base32(s) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const c of s.replace(/\s|=/g, "").toUpperCase()) bits += alphabet.indexOf(c).toString(2).padStart(5, "0");
  const bytes = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}
function totp(secret, offset = 0) {
  const counter = Math.floor(Date.now() / 30000) + offset;
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64BE(BigInt(counter));
  const h = crypto.createHmac("sha1", base32(secret)).update(buf).digest();
  const o = h[h.length - 1] & 15;
  const code = ((h.readUInt32BE(o) & 0x7fffffff) % 1e6).toString().padStart(6, "0");
  return code;
}

(async () => {
  const [inviteUrl, out] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 860 } });
  page.on("pageerror", (e) => console.log("PAGE ERROR", e.message));
  await page.goto(inviteUrl);
  await page.getByLabel("Password", { exact: true }).fill("a long district admin passphrase");
  await page.getByLabel("Confirm new password").fill("a long district admin passphrase");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByText("Set up your authenticator app").waitFor();
  const secret = (await page.locator(".secret").innerText()).replace(/\s/g, "");
  await page.screenshot({ path: `${out}/1-enroll.png` });
  await page.getByLabel("Code").fill(totp(secret));
  await page.getByRole("button", { name: "Confirm" }).click();
  await page.getByText("Save your recovery codes").waitFor();
  await page.screenshot({ path: `${out}/2-recovery.png` });
  await page.getByRole("button", { name: "I have saved these codes" }).click();
  await page.getByText("Welcome, Mariam Al-Ali").waitFor();
  await page.screenshot({ path: `${out}/3-home.png` });

  await page.getByRole("link", { name: "Clusters" }).click();
  await page.getByRole("button", { name: "New cluster" }).click();
  await page.getByLabel("Cluster ID").fill("C-01");
  await page.getByLabel("Name").fill("Salmiya Cluster");
  await page.getByRole("button", { name: "Save" }).click();
  await page.getByRole("cell", { name: "Salmiya Cluster" }).waitFor();

  await page.getByRole("link", { name: "Schools" }).click();
  await page.getByRole("button", { name: "New school" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Cluster").selectOption({ label: "C-01 · Salmiya Cluster" });
  await page.getByLabel("School ID").fill("S-101");
  await page.getByLabel("School name").fill("مدرسة الأمل الابتدائية");
  await page.getByLabel("Address").fill("Block 4, Salmiya");
  await page.getByLabel("School type").fill("Primary");
  await page.getByLabel("Medium of instruction").fill("Arabic");
  await page.getByLabel("Phone").fill("+96522223333");
  // Switch language mid-form: the typed values stay (FR-I3).
  await dialog.getByRole("button", { name: "Language" }).click();
  await page.getByRole("heading", { name: "مدرسة جديدة" }).waitFor();
  await page.screenshot({ path: `${out}/4-form-arabic.png` });
  const kept = await page.getByLabel("العنوان").inputValue();
  console.log("address kept after switch:", kept);
  await page.getByRole("button", { name: "حفظ" }).click();
  await page.getByRole("cell", { name: "مدرسة الأمل الابتدائية" }).waitFor();
  await page.screenshot({ path: `${out}/5-schools-arabic.png` });
  const dir = await page.evaluate(() => document.documentElement.dir);
  console.log("document dir:", dir);

  await page.getByRole("button", { name: "تسجيل الخروج" }).click();
  await page.getByRole("heading", { name: "تسجيل الدخول" }).waitFor();
  const phone = await browser.newPage({ viewport: { width: 375, height: 760 } });
  await phone.goto(page.url());
  await phone.getByRole("heading").first().waitFor();
  await phone.screenshot({ path: `${out}/6-login-phone.png` });

  // Sign in again with the authenticator; the next time step avoids replay rejection.
  await page.getByLabel("البريد الإلكتروني").fill("admin1@example.org");
  await page.getByLabel("كلمة المرور").fill("a long district admin passphrase");
  await page.getByRole("button", { name: "متابعة" }).click();
  await page.getByText("أدخل الرمز المكوّن من 6 أرقام من تطبيق المصادقة.").waitFor();
  await new Promise((r) => setTimeout(r, 31000 - (Date.now() % 30000) + 500));
  await page.getByLabel("الرمز").fill(totp(secret));
  await page.getByRole("button", { name: "تسجيل الدخول" }).click();
  await page.getByText("مرحبًا، Mariam Al-Ali").waitFor();
  console.log("signed in again in Arabic: ok");
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
