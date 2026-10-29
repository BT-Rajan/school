// Browser test for Phase 3 (teacher participation), against a server seeded by e2e/seed_phase3.py:
//
//  1. A supervisor starts a school evaluation; its teacher section goes to the contact teacher,
//     and the evaluation cannot be submitted yet.
//  2. The teacher saves a draft and submits; the supervisor returns it with a comment; the teacher
//     resubmits; the supervisor submits the evaluation with the teacher's answers in it.
//  3. Another teacher at the same school gets nothing, even by address, and no scanned reports.
//  4. The Cluster Head waives a teacher's part so a second evaluation can go ahead.
//  5. An admin approves the form for standalone requests; the Cluster Head sends one to the contact
//     teachers of two schools, one of which has none yet; naming a contact routes it.
//  6. The teacher's screens in Arabic on a phone, and the onboarding counts.
//
// Usage: node e2e/phase3.cjs <base url> <seed.json> <output dir>
const { chromium } = require("playwright");
const fs = require("fs");

const { check, visible, choose, nav, session } = require("./lib.cjs");

(async () => {
  const [base, seedFile, out] = process.argv.slice(2);
  const seed = JSON.parse(fs.readFileSync(seedFile, "utf8"));
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch(process.env.E2E_IGNORE_HTTPS === "1" ? { args: ["--ignore-certificate-errors"] } : {});
  const { signIn, snap, problems, failureShots } = session(browser, base, seed, out);
  global.failureShots = failureShots;

  async function startEvaluation(page) {
    await nav(page, "Evaluations");
    await page.getByRole("button", { name: "New evaluation" }).click();
    const dialog = page.getByRole("dialog");
    await choose(dialog.getByLabel("Form"), /MOE-SV-02/);
    await choose(dialog.getByLabel("School"), /Al-Nahda/);
    await dialog.getByRole("button", { name: "Start" }).click();
    await page.getByRole("heading", { name: /MOE-SV-02/ }).waitFor();
    await page.getByRole("radio", { name: "4" }).click();
    await page.getByRole("button", { name: "Save draft" }).click();
    await page.getByText("Draft saved.").waitFor();
    return page.url();
  }

  // 1. The supervisor starts; the teacher section goes to the contact teacher -----------------
  const noura = await signIn("supa");
  const evaluationUrl = await startEvaluation(noura);
  await visible(noura.locator(".card").filter({ hasText: "Teacher's part" }).getByText("Fatima Al-Sabah"), "teacher section routed to the contact teacher");
  await noura.getByRole("button", { name: "Submit" }).click();
  await visible(noura.getByText("The teacher's part is not submitted yet", { exact: false }), "evaluation waits for the teacher's part");

  // 2. The teacher answers; the supervisor returns it; the teacher resubmits ------------------
  const fatima = await signIn("fatima");
  await fatima.getByRole("link", { name: "My requests" }).first().click();
  await fatima.getByRole("link", { name: /MOE-SV-02/ }).click();
  await visible(fatima.getByText("School's input"), "the teacher sees their section");
  check((await fatima.getByText("Overall").count()) === 0, "the teacher never sees the supervisor's section");
  await fatima.getByLabel("Pupils enrolled").fill("420");
  await fatima.getByRole("button", { name: "Save draft" }).click();
  await fatima.getByText("Draft saved.").waitFor();
  await fatima.getByRole("button", { name: "Submit" }).click();
  await fatima.getByText("Submitted. Thank you.").waitFor();
  await snap(fatima, "teacher-submitted");

  await noura.goto(evaluationUrl);
  await noura.getByRole("link", { name: "Open the request" }).click();
  await visible(noura.getByText("420"), "the supervisor reads the submitted answers");
  await noura.getByRole("button", { name: "Return to the teacher" }).click();
  await noura.getByLabel("What should the teacher change?").fill("Please add what the school needs.");
  await noura.getByRole("dialog").getByRole("button", { name: "Return to the teacher" }).click();
  await noura.getByText("Returned to the teacher.").waitFor();

  await fatima.reload();
  await visible(fatima.getByText("Please add what the school needs."), "the teacher sees why it was returned");
  await fatima.getByLabel("What the school needs").fill("Two more science labs.");
  await fatima.getByRole("button", { name: "Submit again" }).click();
  await fatima.getByText("Submitted. Thank you.").waitFor();

  await noura.reload();
  for (const step of ["Sent", "Submitted", "Returned", "Submitted again"]) {
    await visible(noura.locator(".timeline").getByText(step, { exact: true }), `history shows "${step}"`);
  }
  await noura.goto(evaluationUrl);
  await noura.getByRole("button", { name: "Submit" }).click();
  await noura.getByText("Submitted.", { exact: true }).waitFor();
  await visible(noura.getByText("Two more science labs."), "the evaluation carries the teacher's answers");
  const [pdf] = await Promise.all([noura.waitForEvent("download"), noura.getByRole("button", { name: "PDF in English" }).click()]);
  await pdf.saveAs(`${out}/evaluation-with-teacher.pdf`);
  await snap(noura, "evaluation-submitted");

  // 3. Another teacher at the same school gets nothing --------------------------------------------
  const huda = await signIn("huda");
  await huda.getByRole("link", { name: "My requests" }).first().click();
  await huda.getByText("No requests.").waitFor();
  const requestPath = new URL(fatima.url()).pathname;
  await huda.goto(`${base}${requestPath}`);
  await visible(huda.getByText("Not found."), "another teacher cannot open the request by address");
  const api = await huda.evaluate(async (p) => {
    const get = async (u) => (await fetch(u)).status;
    return { request: await get(`/api${p}`), evaluation: await get("/api/evaluations/1"), reports: await (await fetch("/api/documents")).json() };
  }, requestPath);
  check(api.request === 404 && api.evaluation === 404, "the API answers 404 for another teacher's request and the evaluation");
  check(api.reports.total === 0, "teachers see no scanned reports");

  // 4. The Cluster Head waives a teacher's part ----------------------------------------------------
  const second = await startEvaluation(noura);
  const khalid = await signIn("head");
  await nav(khalid, "Teacher requests");
  await khalid.getByLabel("Show").selectOption("open");
  await khalid.getByRole("link", { name: /MOE-SV-02/ }).first().click();
  await khalid.getByRole("button", { name: "Waive" }).click();
  await khalid.getByLabel("Why is the teacher's part not needed?").fill("The contact teacher is on leave this week.");
  await khalid.getByRole("dialog").getByRole("button", { name: "Waive" }).click();
  await khalid.getByText("Waived.", { exact: true }).waitFor();
  await noura.goto(second);
  await noura.getByRole("button", { name: "Submit" }).click();
  await noura.getByText("Submitted.", { exact: true }).waitFor();
  check(true, "a waived teacher's part lets the evaluation be submitted");

  // 5. Standalone requests --------------------------------------------------------------------------
  const admin = await signIn("admin");
  await nav(admin, "Forms");
  const approve = admin.locator(".card").filter({ hasText: "MOE-SV-02" }).getByLabel("Teachers can be asked to answer this on its own");
  // The box shows the server's answer, so it ticks once the change is saved.
  await approve.click();
  for (let i = 0; i < 40 && !(await approve.isChecked()); i++) await admin.waitForTimeout(250);
  check(await approve.isChecked(), "an admin approves the form for teacher requests");
  await nav(khalid, "Teacher requests");
  await khalid.getByRole("button", { name: "New request" }).click();
  const dialog = khalid.getByRole("dialog");
  await choose(dialog.getByLabel("Form"), /MOE-SV-02/);
  await dialog.getByLabel("Instructions").fill("Please confirm this term's enrolment.");
  await dialog.getByLabel(/Al-Nahda/).check();
  await dialog.getByLabel(/مدرسة الفردوس/).check();
  await dialog.getByRole("button", { name: "Send (2)" }).click();
  await dialog.waitFor({ state: "detached" });
  await khalid.getByLabel("Show").selectOption("unaddressed");
  await visible(khalid.getByRole("row").filter({ hasText: "مدرسة الفردوس" }), "a school without a contact teacher waits for one");
  await nav(khalid, "Schools");
  await khalid.getByRole("row").filter({ hasText: "مدرسة الفردوس" }).getByRole("button", { name: "Set contact teacher" }).click();
  await choose(khalid.getByRole("dialog").getByLabel("Contact teacher"), /Salem/);
  await khalid.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  const salem = await signIn("salem");
  await salem.getByRole("link", { name: "My requests" }).first().click();
  await visible(salem.getByRole("link", { name: /MOE-SV-02/ }), "naming a contact teacher routes the waiting request");
  await salem.getByRole("link", { name: /MOE-SV-02/ }).click();
  await visible(salem.getByText("Please confirm this term's enrolment."), "the teacher sees the instructions");

  // 6. Arabic on a phone, and onboarding counts ---------------------------------------------------------
  const phone = await signIn("fatima", { width: 375, height: 800 });
  await phone.getByRole("banner").getByRole("button", { name: "Language" }).click();
  await phone.getByRole("navigation").getByRole("link", { name: "طلباتي" }).click();
  await phone.getByRole("link", { name: /MOE-SV-02/ }).first().click();
  await visible(phone.getByText("مدخلات المدرسة"), "the teacher's form reads in Arabic");
  const overflow = await phone.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  check(overflow <= 0, "the teacher's request fits a phone screen");
  await snap(phone, "teacher-arabic-phone");
  await nav(khalid, "Teachers");
  await visible(khalid.getByText(/Joined: \d+/), "onboarding counts on the Teachers page");

  await browser.close();
  if (problems.length) {
    console.error(problems.join("\n"));
    process.exit(1);
  }
  console.log("phase 3 browser test: all checks passed");
})().catch(async (e) => {
  console.error(e);
  if (global.failureShots) await global.failureShots();
  process.exit(1);
});
