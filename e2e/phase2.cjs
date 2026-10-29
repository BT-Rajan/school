// Browser test for Phase 2 (section 19, "Browser end-to-end"), against a server seeded by
// e2e/seed_phase2.py. Every step goes through the screens, as each role would use them:
//
//  1. The Form Author builds a ministry report form with a condition, previews it in Arabic at
//     phone width, and sends it for review. The admin returns it with a comment; the author fixes
//     it; the admin publishes it with D/MM/YYYY dates. A teacher report form follows.
//  2. The Cluster Head assigns supervisors to schools on the board.
//  3. Supervisor A fills in a school evaluation, sees a required-answer error, submits, downloads
//     the PDF and amends it with a reason; then a teacher evaluation, with both PDFs.
//  4. Supervisor A uploads a scanned report from a photo and a PDF, in order, and sends it.
//  5. Supervisor B, assigned to the same school, cannot see it, even by its address.
//  6. The admin opens it (watermarked), returns it; A uploads a new version; the admin
//     acknowledges it and shares it with the Cluster Head, who can then read it.
//  7. Notifications, the supervisor dashboard, and the upload dialog at phone width, in Arabic.
//
// Usage, against a fresh database seeded with e2e/seed_phase2.py and with the worker running
// (it scans uploads). The fixtures are any photo saved as page1.png and any one-page page2.pdf:
//   node e2e/phase2.cjs <base url> <seed.json> <fixtures dir> <output dir>
const { chromium } = require("playwright");
const crypto = require("crypto");
const fs = require("fs");
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
// Waits up to 10 seconds for the element, since screens refresh after each action.
async function visible(locator, message) {
  await locator.first().waitFor({ timeout: 10000 });
  console.log(`ok - ${message}`);
}
// Selects the first option whose text matches, for labels that carry counts or codes.
async function choose(select, pattern) {
  // Options arrive with the screen's data, so wait up to 10 seconds for a match.
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
function check(condition, message) {
  if (!condition) throw new Error(`check failed: ${message}`);
  console.log(`ok - ${message}`);
}
// D/MM/YYYY for a day offset from today, in Kuwait time.
function kuwaitDate(offsetDays) {
  const d = new Date(Date.now() + 3 * 3600 * 1000 + offsetDays * 86400 * 1000);
  return `${d.getUTCDate()}/${String(d.getUTCMonth() + 1).padStart(2, "0")}/${d.getUTCFullYear()}`;
}

(async () => {
  const [base, seedFile, fixtures, out] = process.argv.slice(2);
  const seed = JSON.parse(fs.readFileSync(seedFile, "utf8"));
  fs.mkdirSync(out, { recursive: true });
  // With a self-signed certificate the service worker only registers if Chromium trusts it too.
  const browser = await chromium.launch(process.env.E2E_IGNORE_HTTPS === "1" ? { args: ["--ignore-certificate-errors"] } : {});
  const problems = [];
  let shot = 0;
  const pages = [];
  const usedSteps = {};
  process.on("unhandledRejection", () => {});
  global.failureShots = async () => {
    for (const [i, p] of pages.entries()) await p.screenshot({ path: path.join(out, `failure-${i}.png`), fullPage: true }).catch(() => {});
  };

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
    const step = Math.floor(Date.now() / 30000);
    if (usedSteps[key] === step) await page.waitForTimeout(30000 - (Date.now() % 30000) + 500);
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
  const nav = (page, name) => page.getByRole("navigation").getByRole("link", { name, exact: true }).click();

  // 1. Form Author builds the form ----------------------------------------------------------
  const author = await signIn("author");
  await nav(author, "Forms");
  await author.getByRole("button", { name: "New ministry report" }).click();
  await author.getByLabel("Ministry report ID").fill("MOE-SV-01");
  await author.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await author.getByRole("button", { name: "New version" }).click();
  const versionDialog = author.getByRole("dialog");
  await versionDialog.getByLabel("Version ID").fill("2026.1");
  await versionDialog.getByLabel("Report title (English)").fill("School visit report");
  await versionDialog.getByLabel("Report title (العربية)").fill("تقرير زيارة مدرسة");
  await versionDialog.getByRole("button", { name: "Create" }).click();
  await author.getByRole("button", { name: "Add section" }).click();
  const section = author.locator(".builder-section").first();
  await section.getByLabel("Key", { exact: true }).fill("visit");
  await section.getByLabel("Title (English)").fill("Visit");
  await section.getByLabel("Title (العربية)").fill("الزيارة");
  await section.getByLabel("Add a question").selectOption({ label: "Yes or no" });
  let q = section.locator(".builder-question").nth(0);
  await q.getByLabel("Key", { exact: true }).fill("met_principal");
  await q.getByLabel("Question (English)").fill("Did you meet the principal?");
  await q.getByLabel("Question (العربية)").fill("هل قابلت المدير؟");
  await q.getByLabel("Required").check();
  await section.getByLabel("Add a question").selectOption({ label: "Short text" });
  q = section.locator(".builder-question").nth(1);
  await q.getByLabel("Key", { exact: true }).fill("reason_not_met");
  await q.getByLabel("Question (English)").fill("Why not?");
  // Arabic left out on purpose: the review check must catch it.
  await q.getByLabel("Required").check();
  await q.getByLabel("Show only if").check();
  await q.getByLabel("Value").selectOption("no");
  await section.getByLabel("Add a question").selectOption({ label: "Rating" });
  q = section.locator(".builder-question").nth(2);
  await q.getByLabel("Key", { exact: true }).fill("overall");
  await q.getByLabel("Question (English)").fill("Overall rating");
  await q.getByLabel("Question (العربية)").fill("التقييم العام");
  await q.getByLabel("Required").check();
  await author.getByRole("button", { name: "Save" }).first().click();
  await author.getByText("Saved.").waitFor();
  await author.getByText("Arabic text is missing.").waitFor();
  check(true, "missing Arabic text is flagged next to the question");
  await snap(author, "builder");

  await author.getByRole("tab", { name: "Preview" }).click();
  await author.locator(".preview").getByLabel("Language", { exact: true }).selectOption("ar");
  await author.locator(".preview").getByLabel("Screen", { exact: true }).selectOption("phone");
  const preview = author.locator(".preview-frame");
  check((await preview.locator("text=لماذا لا؟").count()) === 0, "conditional question hidden until its condition holds");
  await preview.getByRole("radio", { name: "لا", exact: true }).check();
  await visible(preview.locator(".question").filter({ hasText: "Why not?" }), "conditional question appears when the answer is No");
  await snap(author, "preview-arabic-phone");
  await author.getByRole("tab", { name: "Edit form" }).click();
  await author.getByRole("button", { name: "Send for review" }).click();
  await author.getByText("The form is not complete", { exact: false }).waitFor();
  check(true, "an incomplete form cannot go to review");
  await section.locator(".builder-question").nth(1).getByLabel("Question (العربية)").fill("لماذا لا؟");
  await author.getByRole("button", { name: "Save" }).first().click();
  await author.getByText("Saved.").waitFor();
  await author.getByRole("button", { name: "Send for review" }).click();
  await author.getByText("Sent to the District Admins for review.").waitFor();
  const formUrl = author.url();

  // Admin returns, author fixes, admin publishes.
  const admin = await signIn("admin");
  await admin.goto(formUrl);
  await admin.getByRole("button", { name: "Return to author" }).click();
  await admin.getByLabel("Comments for the author").fill("Please add help text to the rating.");
  await admin.getByRole("dialog").getByRole("button", { name: "Return to author" }).click();
  await admin.getByText("Returned to the author.").waitFor();
  await author.reload();
  await author.getByText("Please add help text to the rating.").waitFor();
  const rating = author.locator(".builder-question").nth(2);
  if (!(await rating.getAttribute("open"))) await rating.locator("summary").click();
  await rating.getByLabel("Help text (English)").fill("1 is poor, 5 is excellent.");
  await rating.getByLabel("Help text (العربية)").fill("1 ضعيف و5 ممتاز.");
  await author.getByRole("button", { name: "Save" }).first().click();
  await author.getByText("Saved.").waitFor();
  await author.getByRole("button", { name: "Send for review" }).click();
  await author.getByText("Sent to the District Admins for review.").waitFor();
  await admin.reload();
  await admin.getByRole("button", { name: "Publish" }).click();
  const publish = admin.getByRole("dialog");
  await publish.getByLabel("Opens on").fill(kuwaitDate(0));
  await publish.getByLabel("Closes on").fill(kuwaitDate(20));
  await publish.getByRole("button", { name: "Publish" }).click();
  await admin.getByText("Published.").waitFor();
  await visible(admin.getByText(`Open from ${kuwaitDate(0)} to ${kuwaitDate(20)}.`), "published window shown as D/MM/YYYY");
  await snap(admin, "published");

  // A teacher report too: built, sent for review and published the same way.
  await author.goto(`${base}/forms`);
  await author.getByRole("button", { name: "New ministry report" }).click();
  let dialog = author.getByRole("dialog");
  await dialog.getByLabel("Ministry report ID").fill("MOE-TV-01");
  await dialog.getByLabel("Report about").selectOption("teacher");
  await dialog.getByRole("button", { name: "Create" }).click();
  await dialog.waitFor({ state: "detached" });
  await author.locator(".card").filter({ hasText: "MOE-TV-01" }).getByRole("button", { name: "New version" }).click();
  dialog = author.getByRole("dialog");
  await dialog.getByLabel("Version ID").fill("2026.1");
  await dialog.getByLabel("Report title (English)").fill("Classroom observation");
  await dialog.getByLabel("Report title (العربية)").fill("ملاحظة صفية");
  await dialog.getByRole("button", { name: "Create" }).click();
  await author.getByRole("button", { name: "Add section" }).click();
  const tsection = author.locator(".builder-section").first();
  await tsection.getByLabel("Key", { exact: true }).fill("lesson");
  await tsection.getByLabel("Title (English)").fill("Lesson");
  await tsection.getByLabel("Title (العربية)").fill("الدرس");
  await tsection.getByLabel("Add a question").selectOption({ label: "Rating" });
  q = tsection.locator(".builder-question").nth(0);
  await q.getByLabel("Key", { exact: true }).fill("planning");
  await q.getByLabel("Question (English)").fill("Lesson planning");
  await q.getByLabel("Question (العربية)").fill("تخطيط الدرس");
  await q.getByLabel("Required").check();
  await author.getByRole("button", { name: "Save" }).first().click();
  await author.getByText("Saved.").waitFor();
  await author.getByRole("button", { name: "Send for review" }).click();
  await author.getByText("Sent to the District Admins for review.").waitFor();
  await admin.goto(author.url());
  await admin.getByRole("button", { name: "Publish" }).click();
  dialog = admin.getByRole("dialog");
  await dialog.getByLabel("Opens on").fill(kuwaitDate(0));
  await dialog.getByLabel("Closes on").fill(kuwaitDate(20));
  await dialog.getByRole("button", { name: "Publish" }).click();
  await admin.getByText("Published.").waitFor();

  // 2. Cluster Head assigns supervisors -----------------------------------------------------
  const head = await signIn("head");
  await nav(head, "Assignments");
  const row = (name) => head.getByRole("row").filter({ hasText: name });
  for (const [school, supervisor] of [["Al-Nahda Primary", "Noura Al-Saleh"], ["Al-Nahda Primary", "Yousef Al-Kandari"], ["مدرسة الفردوس", "Noura Al-Saleh"]]) {
    await row(school).getByRole("button", { name: "Assign", exact: true }).click();
    const dialog = head.getByRole("dialog");
    await choose(dialog.getByLabel("Supervisor"), new RegExp(supervisor));
    await dialog.getByLabel("From").fill(kuwaitDate(-30));
    await dialog.getByRole("button", { name: "Assign", exact: true }).click();
    await dialog.waitFor({ state: "detached" });
  }
  check((await row("Al-Nahda Primary").locator(".chip").count()) === 2, "two supervisors on the shared school");
  await snap(head, "assignment-board");

  // 3. Supervisor A evaluates -----------------------------------------------------------------
  const supA = await signIn("supa");
  await nav(supA, "Evaluations");
  await supA.getByRole("button", { name: "New evaluation" }).click();
  dialog = supA.getByRole("dialog");
  await choose(dialog.getByLabel("Form"), /MOE-SV-01/);
  await choose(dialog.getByLabel("School"), /Al-Nahda/);
  await dialog.getByRole("button", { name: "Start" }).click();
  await supA.getByRole("heading", { name: /MOE-SV-01/ }).waitFor();
  await supA.getByRole("radio", { name: "No", exact: true }).check();
  await supA.getByRole("button", { name: "Submit" }).click();
  await supA.getByText("This question needs an answer.").first().waitFor();
  check(true, "required answers are flagged by the server next to each question");
  await supA.getByLabel("Why not?").fill("The principal was at a ministry meeting.");
  await supA.getByRole("radio", { name: "4" }).click();
  await supA.getByRole("button", { name: "Submit" }).click();
  await supA.getByText("Submitted.").waitFor();
  const [pdf] = await Promise.all([supA.waitForEvent("download"), supA.getByRole("button", { name: "PDF in Arabic" }).click()]);
  const pdfPath = path.join(out, "evaluation-ar.pdf");
  await pdf.saveAs(pdfPath);
  check(fs.readFileSync(pdfPath).subarray(0, 5).toString() === "%PDF-", "Arabic PDF downloads");
  await supA.getByRole("button", { name: "Amend" }).click();
  await supA.getByRole("radio", { name: "5" }).click();
  await supA.getByLabel("Reason for the amendment").fill("Rating entered wrongly.");
  await supA.getByRole("button", { name: "Save amendment" }).click();
  await supA.getByText("Amendment saved.").waitFor();
  await snap(supA, "evaluation-amended");

  // A teacher evaluation: the form asks for a teacher at the chosen school.
  await nav(supA, "Evaluations");
  await supA.getByRole("button", { name: "New evaluation" }).click();
  dialog = supA.getByRole("dialog");
  await choose(dialog.getByLabel("Form"), /MOE-TV-01/);
  await choose(dialog.getByLabel("School"), /Al-Nahda/);
  await choose(dialog.getByLabel("Teacher"), /Fatima Al-Sabah/);
  await dialog.getByRole("button", { name: "Start" }).click();
  await supA.getByRole("heading", { name: /MOE-TV-01/ }).waitFor();
  await visible(supA.locator(".facts").getByText("Fatima Al-Sabah"), "teacher evaluation names the teacher");
  await supA.getByRole("radio", { name: "3" }).click();
  await supA.getByRole("button", { name: "Submit" }).click();
  await supA.getByText("Submitted.").waitFor();
  for (const [button, file] of [["PDF in English", "teacher-en.pdf"], ["PDF in Arabic", "teacher-ar.pdf"]]) {
    const [download] = await Promise.all([supA.waitForEvent("download"), supA.getByRole("button", { name: button }).click()]);
    await download.saveAs(path.join(out, file));
    check(fs.readFileSync(path.join(out, file)).subarray(0, 5).toString() === "%PDF-", `teacher evaluation ${button}`);
  }
  await snap(supA, "teacher-evaluation");

  // 4. Supervisor A uploads a scanned report ---------------------------------------------------
  await nav(supA, "Scanned reports");
  await supA.getByRole("button", { name: "Upload a report" }).click();
  dialog = supA.getByRole("dialog");
  await choose(dialog.getByLabel("Ministry report and version"), /MOE-SV-01/);
  await choose(dialog.getByLabel("School"), /Al-Nahda/);
  await dialog.locator('input[type=file][multiple]').setInputFiles([path.join(fixtures, "page1.png"), path.join(fixtures, "page2.pdf")]);
  await dialog.getByText("Pages: 1").first().waitFor();
  await dialog.getByRole("button", { name: "Upload and send" }).click();
  await supA.getByRole("heading", { name: "School visit report" }).waitFor();
  const reportUrl = supA.url();
  await visible(supA.getByText("Pages: 2"), "photo and PDF joined into one two-page PDF");
  await snap(supA, "report-sent");

  // 5. Supervisor B sees nothing ---------------------------------------------------------------
  const supB = await signIn("supb");
  await nav(supB, "Scanned reports");
  await supB.getByText("No reports.").waitFor();
  await supB.goto(reportUrl);
  await supB.getByText("Not found.").waitFor();
  check(true, "another supervisor of the same school cannot list or open the report");

  // 6. Admin reviews ---------------------------------------------------------------------------
  await admin.goto(`${base}/`);
  const bell = admin.locator(".bell-count");
  await bell.waitFor();
  check(Number(await bell.innerText()) >= 1, "admin sees unread notifications in the header");
  await nav(admin, "Scanned reports");
  await admin.getByRole("link", { name: "School visit report" }).click();
  for (let i = 0; i < 30 && (await admin.getByText("Virus check running").count()); i++) {
    await admin.waitForTimeout(1000);
    await admin.reload();
  }
  const served = [];
  admin.context().on("response", (r) => r.url().includes("/api/files/download/") && served.push(r));
  const [viewer] = await Promise.all([admin.context().waitForEvent("page"), admin.getByRole("button", { name: "View" }).first().click()]);
  await viewer.waitForLoadState();
  for (let i = 0; i < 20 && !served.length; i++) await admin.waitForTimeout(250);
  check(served.length > 0 && served[0].status() === 200 && served[0].headers()["content-type"] === "application/pdf", "admin opens the report in a new tab");
  // The preview keeps the API's own strict rules; the web server only adds defaults.
  check(/default-src 'none'/.test(served[0].headers()["content-security-policy"] ?? ""), "file preview served with a no-script Content Security Policy");
  await viewer.close();
  await admin.reload();
  await admin.getByText("Viewed").first().waitFor();
  await admin.getByRole("button", { name: "Return to supervisor" }).click();
  await admin.getByLabel("What needs to change?").fill("Page 2 is cut off. Please rescan.");
  await admin.getByRole("dialog").getByRole("button", { name: "Return to supervisor" }).click();
  await admin.getByText("Returned to the supervisor.").waitFor();

  await supA.reload();
  await supA.getByText("Page 2 is cut off. Please rescan.").waitFor();
  await supA.getByRole("button", { name: "Upload new version" }).click();
  dialog = supA.getByRole("dialog");
  await dialog.locator('input[type=file][multiple]').setInputFiles([path.join(fixtures, "page2.pdf")]);
  await dialog.getByText("Pages: 1").waitFor();
  await dialog.getByRole("button", { name: "Upload new version" }).click();
  await supA.getByText("New version uploaded.").waitFor();
  await supA.getByRole("button", { name: "Send to District Admins" }).click();
  await supA.getByRole("dialog").getByRole("button", { name: "Send to District Admins" }).click();
  await supA.getByText("Sent to the District Admins.").waitFor();

  await admin.reload();
  await admin.getByRole("button", { name: "Acknowledge" }).click();
  await admin.getByRole("dialog").getByRole("button", { name: "Acknowledge" }).click();
  await admin.getByText("Acknowledged.").first().waitFor();
  await admin.getByRole("button", { name: "Share with the Cluster Head" }).click();
  await admin.getByRole("dialog").getByRole("button", { name: "Share with the Cluster Head" }).click();
  await admin.getByText("Shared with the Cluster Head.").waitFor();
  await snap(admin, "report-acknowledged");

  await nav(head, "Scanned reports");
  await head.getByRole("heading", { name: "Forwarded to me" }).waitFor();
  await head.getByRole("link", { name: "School visit report" }).click();
  await head.getByText("Copies you open carry your name and the time.").waitFor();
  check(true, "the Cluster Head reads the report once an admin shares it");

  // 7. Notifications, dashboard, phone, Arabic -------------------------------------------------
  await supA.goto(`${base}/notifications`);
  await supA.getByText(/was acknowledged/).waitFor();
  await supA.getByRole("banner").getByRole("button", { name: "Language" }).click();
  await supA.getByText(/تم اعتماد تقريرك/).waitFor();
  check(true, "notification text switches language with the screen");
  await snap(supA, "notifications-arabic");
  await nav(supA, "لوحتي");
  await supA.locator(".stats").waitFor();
  await snap(supA, "dashboard-arabic");

  const phone = await signIn("supb", { width: 375, height: 800 });
  await phone.getByRole("banner").getByRole("button", { name: "Language" }).click();
  await phone.goto(`${base}/reports`);
  await phone.getByRole("button", { name: "رفع تقرير" }).click();
  await phone.getByRole("dialog").waitFor();
  const overflow = await phone.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  check(overflow <= 0, "upload dialog fits a phone screen without sideways scrolling");
  await visible(phone.getByText("التقاط صورة"), "camera capture offered on the phone");
  await snap(phone, "upload-phone-arabic");

  await browser.close();
  if (problems.length) {
    console.error(problems.join("\n"));
    process.exit(1);
  }
  console.log("phase 2 browser test: all checks passed");
})().catch(async (e) => {
  console.error(e);
  if (global.failureShots) await global.failureShots();
  process.exit(1);
});
