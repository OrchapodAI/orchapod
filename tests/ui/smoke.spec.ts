import { expect, test, type Locator, type Page } from "@playwright/test";

// Run by scripts/e2e_ui.py (`make ui-smoke`) against a STUB API (every run costs $0) and the web app.
const API = process.env.E2E_API_URL ?? "";
// a second API at the public demo's scale, ORCHAPOD_ANON_SCALE=0.1 (scripts/e2e_ui.py PUBLIC_CAPS): $3 x 0.1 per run
const PUBLIC_API = process.env.E2E_PUBLIC_API_URL ?? "";
const PUBLIC_RUN_CAP = 3 * 0.1;
// canonical intent -> the slug of its template (scripts/e2e_agent.py INTENTS): later templates may fine-tune too
const SLUGS: Record<string, string> = JSON.parse(process.env.E2E_SLUGS || "{}");

type Template = {
  slug: string; title: string; intent: string; estimate: { usd: number; minutes: number };
  plan: { name: string; nodes: { type: string; inputs?: Record<string, unknown> }[] };
  reduced?: { estimate: { usd: number } }; fits?: boolean;
};

const usd = (n: number) => `$${n.toFixed(2)}`; // the page's own formats
const mins = (n: number) => `~${Math.round(n)} min`;

async function template(n: 1 | 2): Promise<Template> {
  const r = await fetch(`${API}/agent/templates`);
  if (!r.ok) throw new Error(`GET /agent/templates -> HTTP ${r.status}`);
  const all: Template[] = await r.json();
  const found = all.find((t) => t.slug === SLUGS[n]);
  if (!found) throw new Error(`none of the ${all.length} templates has the slug ${SLUGS[n]} of canonical intent #${n}`);
  return found;
}

/** What the page did wrong while a test ran: uncaught errors, console errors, and API calls that failed. */
function watch(page: Page): string[] {
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(`page error: ${e.message}`));
  page.on("console", (m) => m.type() === "error" && !/favicon/.test(m.location().url + m.text()) && problems.push(`console.error: ${m.text()}`));
  page.on("response", (r) => {
    if (r.url().startsWith(API) && r.status() >= 400) problems.push(`${r.request().method()} ${r.url().slice(API.length)} -> ${r.status()}`);
  });
  return problems;
}

/** Waits for `done`, or for the page to say that the run failed; a failure fails the test at once, with its node error in the screenshot. */
async function untilDone(page: Page, done: Locator, timeout = 240_000): Promise<void> {
  const failed = page.getByText(/Run failed|Couldn't start the run|Couldn't load the report/);
  await expect(done.or(failed)).toBeVisible({ timeout });
  await expect(failed, "the run failed: see the screenshot").toHaveCount(0, { timeout: 2_000 });
}

/** A tab of the run page. Its buttons share a row with "logs"; the node column has buttons too, named like "evaluate". */
const tab = (page: Page, name: string) =>
  page.getByRole("button", { name: "logs", exact: true }).locator("xpath=..").getByRole("button", { name: new RegExp(`^${name}$`, "i") });

test("/agent: intent #2 is planned, run and reported", async ({ page }, testInfo) => {
  const problems = watch(page);
  const t = await template(2);

  await page.goto("/agent");
  await page.getByLabel("What should Orchapod build?").fill(t.intent); // typed, as a person would
  await page.getByRole("button", { name: "Plan", exact: true }).click();

  // the plan card (aria-label "Plan"; the templates on the page have estimates and Run buttons too): the canonical plan, its estimate
  const card = page.getByLabel("Plan", { exact: true });
  await expect(card.getByText(t.plan.name, { exact: true })).toBeVisible();
  await expect(card.getByText(`${t.plan.nodes.length} nodes`, { exact: true })).toBeVisible();
  for (const node of t.plan.nodes) await expect(card.getByRole("cell", { name: node.type })).toBeVisible();
  await expect(card.getByTitle("Estimated cost and wall time")).toHaveText(`${usd(t.estimate.usd)} · ${mins(t.estimate.minutes)}`);
  const run = card.getByRole("button", { name: /Run$/ });
  await expect(run).toBeEnabled();

  await run.click();
  await expect(run).toBeDisabled(); // one click, one run

  // the report is written when the run ends (STUB: the deterministic template), cost $0
  await untilDone(page, page.getByText(`${t.plan.name}: succeeded`));
  await expect(page.getByText(`${usd(0)} spent of ${usd(t.estimate.usd)} estimated`)).toBeVisible();

  await tab(page, "artifacts( \\d+)?").click(); // its name carries the artifact count
  for (const name of ["dataset", "train_jsonl", "eval_jsonl", "cost_json"]) {
    await expect(page.getByText(name, { exact: true }).first()).toBeVisible();
  }

  await page.screenshot({ path: testInfo.outputPath("agent-intent-2.png"), fullPage: true });
  expect(problems).toEqual([]);
});

// ---------------------------------------------------------------------------------------------------------------------
// The template gallery, the dataset card, the eval view and the compare playground (frontend-w3) and the golden path (ml-w4's
// vllm-serve): all merged, so a missing piece is a regression and fails.
// ---------------------------------------------------------------------------------------------------------------------

/** One click on a template card of the gallery (under the chat box on /agent; its button is named "Run template: <title>"). */
async function runFromGallery(page: Page, t: Template): Promise<void> {
  await page.goto("/agent");
  await page.getByRole("button", { name: `Run template: ${t.title}` }).click();
}

test("templates: one click runs intent #2 to a finished run with its dataset card", async ({ page }) => {
  const problems = watch(page);
  const t = await template(2);
  await runFromGallery(page, t);

  // DatasetCard (frontend-w3): the download link of data-prep's dataset and the stats card from its metrics `fields`
  const download = page.getByRole("link", { name: /download dataset/i });
  await untilDone(page, download);
  await expect(download).toHaveAttribute("href", /\/artifacts\/[0-9a-f-]{36}\/download$/);
  for (const field of ["user_id", "movie_title", "action", "timestamp", "device"]) {
    await expect(page.getByText(field, { exact: true }).first()).toBeVisible();
  }
  // the card's row count is the dataset's: the one-click Run may run a reduced plan, so the template's n_samples says nothing
  const shown = Number((await page.getByText(/^\d+ rows$/).first().innerText()).split(" ")[0]);
  const file = await page.request.get((await download.getAttribute("href"))!); // the API's 307 to object storage, followed
  expect(file.ok()).toBe(true);
  expect((await file.text()).split("\n").filter(Boolean)).toHaveLength(shown);
  expect(problems).toEqual([]);
});

// frontend-w4: on the public app a template whose reduced plan is above the per-run cap (`fits: false`) keeps Run disabled and
// says why; the page reads GET /agent/templates from the public-scale API, since its own runs at full scale.
test("templates: at ORCHAPOD_ANON_SCALE=0.1 a template above the per-run cap cannot be run and says why", async ({ page }) => {
  const problems = watch(page);
  const r = await fetch(`${PUBLIC_API}/agent/templates`);
  if (!r.ok) throw new Error(`GET ${PUBLIC_API}/agent/templates -> HTTP ${r.status}`);
  const all: Template[] = await r.json();
  const over = all.filter((t) => t.fits === false);
  expect(over.length, "at the public scale some template is above the cap, and some is not").toBeGreaterThan(0);
  expect(over.length).toBeLessThan(all.length);
  await page.route(`${API}/agent/templates`, (route) => route.continue({ url: `${PUBLIC_API}/agent/templates` }));

  await page.goto("/agent");
  for (const t of all) {
    const run = page.getByRole("button", { name: `Run template: ${t.title}`, exact: true });
    if (t.fits !== false) {
      await expect(run).toBeEnabled();
      continue;
    }
    const usdOver = (t.reduced ?? t).estimate.usd;
    expect(usdOver, `${t.slug}: its card says it is above the $${PUBLIC_RUN_CAP.toFixed(2)} cap`).toBeGreaterThan(PUBLIC_RUN_CAP);
    await expect(run).toBeDisabled();
    await expect(run).toHaveAccessibleDescription(`about ${usd(usdOver)} — above the public demo's per-run cap; watch the golden run`);
    await expect(page.locator(`#cap-${t.slug}`).getByRole("link", { name: "watch the golden run" }))
      .toHaveAttribute("href", `/runs?q=${encodeURIComponent(t.plan.name)}`);
  }
  expect(problems).toEqual([]);
});

// What the run page shows for a judge-eval result (docs/contracts.md "judge-eval", "ModelRef", "/compare"), on the golden path's real
// STUB data.
async function checkEvalView(page: Page): Promise<void> {
  await tab(page, "eval").click({ timeout: 180_000 }); // the tab appears when judge-eval is done
  await expect(page.getByText("Win rate, tuned vs base")).toBeVisible(); // not exact: the label has a STUB pill beside it
  await expect(page.getByText(/Consistency/).first()).toBeVisible();
  await expect(page.getByText("Judged samples", { exact: true })).toBeVisible(); // not "Loading the judged samples…"
  await page.locator("details > summary").first().click(); // a judged sample opens with both orders' reasoning
  await expect(page.getByText(/Judge, tuned shown first/).first()).toBeVisible(); // first(): every sample has its own
  await expect(page.getByText(/Judge, base shown first/).first()).toBeVisible();
}

async function checkPlayground(page: Page): Promise<void> {
  await tab(page, "compare").click(); // the tab appears with two model refs
  const prompt = page.getByLabel("Prompt");
  await prompt.fill("What does a Loan Estimate show?");
  await prompt.locator("xpath=ancestor::form").getByRole("button", { name: /^compare$/i }).click(); // its form's button, not the tab
  await expect(page.getByText(/^done/)).toHaveCount(2, { timeout: 60_000 }); // both sides streamed to the end
}

test("golden path: template, run, eval view, compare playground", async ({ page }) => {
  const problems = watch(page);
  const t = await template(1);
  await runFromGallery(page, t);

  await untilDone(page, tab(page, "eval"), 180_000); // a failed node shows at once: do not wait out the eval tab
  await checkEvalView(page); // the eval view on the judge-eval node's real STUB result
  await checkPlayground(page); // the playground over POST /compare: one prompt, two models, streamed side by side
  expect(problems).toEqual([]);
});
