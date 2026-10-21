import { expect, test, type Page } from "@playwright/test";

// Run by scripts/e2e_ui.py (`make ui-smoke`) against a STUB API (every run costs $0) and the web app.
const API = process.env.E2E_API_URL ?? "";
const STRICT = process.env.E2E_STRICT === "1";
// canonical intent -> why it cannot run yet, from the planner's own errors (scripts/e2e_agent.py PENDING)
const PENDING: Record<string, string[]> = JSON.parse(process.env.E2E_PENDING || "{}");

type Template = { slug: string; title: string; intent: string; plan: { name: string; nodes: { type: string; inputs?: Record<string, unknown> }[] } };

/** A step whose piece is not merged yet: a loud SKIP that is never a pass. --strict (E2E_STRICT=1) fails it instead. */
function pending(why: string | string[]): never {
  const message = `SKIP (this is NOT a pass): ${([] as string[]).concat(why).join("; ")}`;
  console.log(`\n${message}`);
  test.skip(!STRICT, message);
  throw new Error(message);
}

async function template(n: 1 | 2): Promise<Template> {
  const all: Template[] = await (await fetch(`${API}/agent/templates`)).json();
  const found = all.find((t) => t.plan.nodes.some((x) => (n === 1 ? x.type === "tf-finetune"
    : x.type === "synth-distilabel" && x.inputs?.pipeline_template === "structured")));
  if (!found) throw new Error(`none of the ${all.length} templates is canonical intent #${n}`);
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

test("/agent: intent #2 is planned, run and reported", async ({ page }, testInfo) => {
  const problems = watch(page);
  const t = await template(2);

  await page.goto("/agent");
  await page.getByLabel("What should Orchapod build?").fill(t.intent); // typed, as a person would
  await page.getByRole("button", { name: "Plan", exact: true }).click();

  // the plan card (the nearest ancestor of the plan's name that holds the node table; the templates on the page have estimates too)
  const name = page.getByText(t.plan.name, { exact: true });
  await expect(name).toBeVisible();
  const card = name.locator("xpath=ancestor::*[.//table][1]");
  await expect(card.getByText("2 nodes", { exact: true })).toBeVisible();
  for (const node of t.plan.nodes) await expect(card.getByRole("cell", { name: node.type })).toBeVisible();
  await expect(card.getByTitle("Estimated cost and wall time")).toHaveText(/^\$0\.15 · ~\d+ min$/);
  const run = card.getByRole("button", { name: "▶ Run" });
  await expect(run).toBeEnabled();

  await run.click();
  await expect(run).toBeDisabled(); // one click, one run

  // the report is written when the run ends (STUB: the deterministic template), cost $0; a failure shows up as soon as it happens
  const succeeded = page.getByText(`${t.plan.name}: succeeded`);
  await expect(succeeded.or(page.getByText(/Run failed|Couldn't start the run|Couldn't load the report/))).toBeVisible({ timeout: 240_000 });
  await expect(succeeded).toBeVisible();
  await expect(page.getByText("$0.00 spent of $0.15 estimated")).toBeVisible();

  await page.getByRole("button", { name: "artifacts" }).click();
  for (const name of ["dataset", "train_jsonl", "eval_jsonl", "cost_json"]) {
    await expect(page.getByText(name, { exact: true }).first()).toBeVisible();
  }

  await page.screenshot({ path: testInfo.outputPath("agent-intent-2.png"), fullPage: true });
  expect(problems).toEqual([]);
});

// ---------------------------------------------------------------------------------------------------------------------
// The template gallery, the dataset card, the eval view and the compare playground (frontend-w3, merged: a missing piece is a
// regression and fails), and the golden path, which SKIPs only for what is not merged yet (vllm-serve, ml-w4).
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
  await expect(download).toBeVisible({ timeout: 120_000 });
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

// What the run page shows for a judge-eval result (docs/contracts.md "judge-eval", "ModelRef", "/compare"): used by the golden path
// on real STUB data, and by the next test on a run served from a fixture, which needs neither judge-eval nor POST /compare.
async function checkEvalView(page: Page): Promise<void> {
  await page.getByRole("button", { name: "eval", exact: true }).click({ timeout: 180_000 }); // the tab appears when judge-eval is done
  await expect(page.getByText("Win rate, tuned vs base")).toBeVisible(); // not exact: the label has a STUB pill beside it
  await expect(page.getByText(/Consistency/).first()).toBeVisible();
  await expect(page.getByText("Judged samples", { exact: true })).toBeVisible(); // not "Loading the judged samples…"
  await page.locator("details > summary").first().click(); // a judged sample opens with both orders' reasoning
  await expect(page.getByText(/Judge, tuned shown first/).first()).toBeVisible(); // first(): every sample has its own
  await expect(page.getByText(/Judge, base shown first/).first()).toBeVisible();
}

async function checkPlayground(page: Page): Promise<void> {
  await page.getByRole("button", { name: "compare", exact: true }).click(); // the tab appears with two model refs
  await page.getByLabel("Prompt").fill("What does a Loan Estimate show?");
  await page.locator("form").getByRole("button", { name: "Compare", exact: true }).click();
  await expect(page.getByText(/^done/)).toHaveCount(2, { timeout: 60_000 }); // both sides streamed to the end
}

const RUN = "00000000-0000-4000-8000-000000000001";
const ref = (model: string) => ({ base_url: "https://api.tokenfactory.nebius.com/v1", model, api_key_env: "NEBIUS_API_KEY", base_model: null });
const STATS = {
  n: 2, judged: 2, wins: 1, ties: 1, losses: 0, errors: 0, win_rate: 0.75, consistency: 0.5, exact_match: null,
  base: ref("meta-llama/Llama-3.2-3B-Instruct"), tuned: ref("orchapod-3b-lora"), judge_model: "nvidia/Nemotron-3-Ultra-550b-a55b",
  decoding: { temperature: 0, max_tokens: 512 }, stub: true,
};
const verdict = (i: number, v: "win" | "tie") => ({
  i, question: `Question ${i}?`, reference: "Reference.", context: null, source_url: null, base: "Base answer", tuned: "Tuned answer",
  base_correct: null, tuned_correct: null, verdict: v, error: null,
  judgments: [{ order: "tuned_first", winner: "tuned", reasoning: "Tuned sticks to the passage." },
              { order: "base_first", winner: v === "win" ? "tuned" : "tie", reasoning: "Same on the second look." }],
});

test("run page: eval view and compare playground on a run served from a fixture", async ({ page }) => {
  const problems = watch(page);
  const art = (id: string, node_id: string, name: string, meta: object = {}) =>
    ({ id, node_id, name, kind: "metrics", uri: `r2://b/runs/${RUN}/${node_id}/${name}`, download_url: `/artifacts/${id}/download`, meta });
  const summary = {
    run_id: RUN, status: "succeeded", cost_usd: 0, error: null,
    nodes: [{ node_id: "evaluate", type: "judge-eval", status: "succeeded", usd: 0, error: null, started_at: null, finished_at: null }],
    artifacts: [art("ev", "evaluate", "eval_summary"), art("mj", "evaluate", "metrics_json", STATS)],
  };
  const run = { id: RUN, workflow_id: RUN, user_id: RUN, status: "succeeded", inputs: {}, cost_usd: 0, started_at: null, finished_at: null,
                gpu_provider: "local-docker", created_at: "2026-01-01T00:00:00" };
  const sse = [{ i: 0, delta: "side A " }, { i: 0, delta: "streams" }, { i: 1, delta: "side B streams" }, { i: 0, done: true, usd: null },
               { i: 1, done: true, usd: null }].map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
  const cors = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" };
  await page.route(`${API}/**`, (route) => {
    const { pathname } = new URL(route.request().url());
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
    if (pathname === `/runs/${RUN}`) return route.fulfill({ json: run, headers: cors });
    if (pathname === `/runs/${RUN}/summary`) return route.fulfill({ json: summary, headers: cors });
    if (pathname === "/artifacts/ev/download") return route.fulfill({ json: { ...STATS, samples: [verdict(0, "win"), verdict(1, "tie")] }, headers: cors });
    if (pathname === "/compare") return route.fulfill({ headers: { ...cors, "content-type": "text/event-stream" }, body: sse });
    return route.fulfill({ status: 404, body: "not in the fixture", headers: cors }); // reported by watch()
  });

  await page.goto(`/runs/${RUN}`);
  await checkEvalView(page);
  await expect(page.getByText("75%").first()).toBeVisible(); // win rate = (1 win + 0.5 x 1 tie) / 2
  await checkPlayground(page);
  await expect(page.getByText("side A streams", { exact: true })).toBeVisible(); // the deltas of one side join
  await expect(page.getByText("side B streams", { exact: true })).toBeVisible();
  expect(problems).toEqual([]);
});

test("golden path: template, run, eval view, compare playground", async ({ page }) => {
  const problems = watch(page);
  const t = await template(1);
  if (PENDING["1"]) pending(PENDING["1"]);
  await runFromGallery(page, t);

  await checkEvalView(page); // the eval view on the judge-eval node's real STUB result
  await checkPlayground(page); // the playground over POST /compare: one prompt, two models, streamed side by side
  expect(problems).toEqual([]);
});
