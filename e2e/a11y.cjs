// Accessibility check (section 15: WCAG 2.1 AA in both languages), against a server seeded by
// e2e/seed_phase4.py. Runs axe-core on each role's main screens in English and in Arabic, on a
// desktop and a phone, and checks that the critical journeys' first steps work from the keyboard.
//
// Usage: node e2e/a11y.cjs <base url> <seed.json> <output dir>
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const { session, check } = require("./lib.cjs");

const AXE = require.resolve("axe-core/axe.min.js", { paths: [path.join(__dirname, "../frontend")] });
const PAGES = {
  admin: ["/", "/reports", "/standard-reports", "/forms", "/assignments", "/schools", "/teachers", "/settings", "/audit", "/support", "/notifications", "/account"],
  supa: ["/", "/dashboard", "/evaluations", "/reports", "/requests", "/outbox"],
  head: ["/", "/assignments", "/evaluations", "/standard-reports"],
  fatima: ["/", "/requests"],
};

(async () => {
  const [base, seedFile, out] = process.argv.slice(2);
  const seed = JSON.parse(fs.readFileSync(seedFile, "utf8"));
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch();
  const { signIn, problems } = session(browser, base, seed, out);
  const found = [];

  async function audit(page, label) {
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(400);
    await page.addScriptTag({ path: AXE });
    const result = await page.evaluate(async () =>
      // eslint-disable-next-line no-undef
      axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] } }),
    );
    for (const v of result.violations) {
      found.push({ page: label, id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.slice(0, 3).map((n) => n.target.join(" ")) });
    }
  }

  // The sign-in page, before anyone is signed in.
  const anon = await (await browser.newContext()).newPage();
  for (const locale of ["en", "ar"]) {
    await anon.goto(`${base}/login`);
    if (locale === "ar") await anon.locator(".lang-switch").first().click();
    await audit(anon, `${locale} /login`);
  }

  let skipChecked = false;
  for (const [key, pages] of Object.entries(PAGES)) {
    for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
      const page = await signIn(key, viewport);
      if (!skipChecked) {
        // Keyboard: arriving on a signed-in screen, the first Tab reaches "skip to content".
        await page.reload();
        await page.getByRole("navigation").waitFor();
        await page.keyboard.press("Tab");
        check((await page.evaluate(() => document.activeElement?.className)) === "skip-link", "the first Tab reaches the skip link");
        skipChecked = true;
      }
      for (const locale of ["en", "ar"]) {
        if (locale === "ar") {
          await page.getByRole("banner").locator(".lang-switch").click();
          await page.locator("html[dir=rtl]").waitFor();
        }
        for (const p of pages) {
          await page.goto(`${base}${p}`);
          await audit(page, `${key} ${locale} ${viewport.width}px ${p}`);
        }
      }
      // The choice is saved to the account; back to English for the next sign-in.
      await page.getByRole("banner").locator(".lang-switch").click();
      await page.waitForFunction(() => document.documentElement.dir !== "rtl");
      await page.waitForTimeout(500);
      await page.context().close();
    }
  }

  const byRule = {};
  for (const f of found) (byRule[f.id] ??= { impact: f.impact, help: f.help, pages: [], example: f.nodes[0] }).pages.push(f.page);
  fs.writeFileSync(path.join(out, "a11y.json"), JSON.stringify({ violations: found, byRule }, null, 2));
  for (const [id, r] of Object.entries(byRule)) console.log(`${r.impact} ${id}: ${r.help} (${r.pages.length} pages, e.g. ${r.pages[0]} ${r.example})`);

  // Keyboard: the sign-in form works without a mouse.
  const kb = await (await browser.newContext()).newPage();
  await kb.goto(`${base}/login`);
  const user = seed.users.supa;
  await kb.getByLabel("Email").focus();
  await kb.keyboard.type(user.email);
  await kb.keyboard.press("Tab");
  await kb.keyboard.type(seed.password);
  await kb.keyboard.press("Enter");
  await kb.getByLabel("Code").waitFor();
  check(true, "sign-in proceeds from the keyboard alone");
  await browser.close();
  if (problems.length) console.error(problems.join("\n"));
  console.log(found.length ? `accessibility: ${found.length} violations` : "accessibility: no violations");
  process.exit(found.length || problems.length ? 1 : 0);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
