# Video script, shot list and screenshots

Draft from the beat list in `hackathon/PLAN.md` and the interfaces in `docs/contracts.md`. The recorded run is the D8 rehearsal, run 0ee1e20a, and every number the narrator says is read off it, never a guess. PLAN.md calls the one-sentence front door the Copilot; the product calls it the Orchapod Agent.

## Rules

- Public on YouTube, English, under 3:00: this cut ends at 2:55. No music and no sound effects, no third-party marks (PLAN.md, "What the submission must contain").
- Everything on screen is a real run. Every segment that is sped up or cut (the planning wait in shot 2, the whole run in shot 3) carries a "sped up or cut" caption. STUB output is never shown as a result, and no non-Nebius GPU footage appears as Nebius (spike 4 ran on vast.ai).
- Say only what ran. The narrator reads numbers off the screen, does not round them in our favour, and reads a win rate below 50% as it is.
- Sponsor names as text, no logos; crop console shots to the content area. No key, token, email or project id in frame (not `.env`, not a terminal).

## The golden run

The recorded run is the D8 rehearsal on the hosted app, run 0ee1e20a-468f-4651-8eee-c39fd094a804 (2026-10-25). The golden sentence was typed on /agent, Super's live plan came back with six nodes, $2.66 and no errors, and then Run. It is the Nebius docs specialist on Lane B, NVIDIA end to end on Nebius (contracts R25): web-research, synth-distilabel (grounded), data-prep, unsloth-train (NVIDIA's Nemotron Nano 8B student, a 16-bit LoRA on an H100 Serverless Job), vllm-serve (base and adapter on one L40S Serverless Endpoint, keep-alive 15 minutes), judge-eval (Nemotron 3 Ultra, base against tuned), then the playground. It took 23.5 min and cost $1.58. The topic is the Nebius docs, because the judges can verify the answers and the base model is unlikely to know them.

The raw footage is in `footage/2026-10-25-rehearsal-0ee1e20a/` in the main checkout. It is gitignored and local only, so never commit it.
- `video/0-agent.webm`: the sentence, the plan and Run.
- `video/1-runs.webm`: the run page.
- `video/2-canvas.webm` and `video/3-canvas.webm`: the canvas.
- `tour/tour.webm`.
- `frames/`: 23 frames, one per node status change.
- The README stills.
- `rehearsal.log`: every timestamp.

## Shot list

| # | Time | Screen | Voice-over | Caption | Live run |
| --- | --- | --- | --- | --- | --- |
| 1 | 0:00-0:15 | Title card, text only: "Orchapod.ai" and the caption line (not the 32-word tagline), 5 s. Then the empty /agent page with the cursor in "What should Orchapod build?". | Every team wants a cheaper, private specialist model. Making one takes an ML engineer and a pile of GPU plumbing. Orchapod does it from one sentence. | Describe the specialist model you want in one sentence | no |
| 2 | 0:15-0:40 | /agent. Type the golden sentence and press Plan; "Nemotron is planning…" shows, and the wait is sped up or cut to fit; the plan card appears. Hold on the table (node, type, models, estimate), then on the cost and time at the top right; end with the cursor on Run. Or click Run on the template card (its reduced plan runs at once; no Plan step). | Describe the model you want. Nemotron 3 Super, on Nebius Token Factory, drafts the pipeline from our node catalog. The server checks it against model and cost rules, and the plan card shows every node, every model and the estimated cost and time before anything runs. | Nemotron 3 Super plans the pipeline (wait sped up or cut) | recorded: `video/0-agent.webm`, Super's live plan at 08:35:09Z (six nodes, $2.66, no errors) |
| 3 | 0:40-1:25 | Press Run. The run view under the plan, or /runs/{id}: nodes go from pending to running to succeeded, log lines stream, the Cost pill rises as each node reports. Time-lapse of the real run: cut at each node's change of status and keep the log timestamps in frame. Open the chart tab on the fine-tune's loss curve. End on the run's row in /runs: its Duration and Cost columns are where the voice-over's totals come from. | Press Run. Tavily finds and extracts the sources. Nemotron 3 Super writes grounded question-and-answer pairs from them, each with its source URL. Data prep removes duplicates and splits the data. Unsloth fine-tunes NVIDIA's Nemotron Nano student with LoRA on a Nebius Serverless Job, and vLLM serves base and tuned on one Serverless Endpoint. Logs stream live, and the cost meter updates as each node reports what it spent, under a hard cap per run. The whole run took 23.5 minutes and cost 1.58 dollars. | Real run, sped up or cut (31x) | recorded: `video/1-runs.webm` and `frames/01` to `23` (run 0ee1e20a, 08:35:15Z to 08:58:57Z) |
| 4 | 1:25-1:55 | Eval view of the same run: win-rate stat, win/tie/loss bars, consistency. Then open one sample: question, reference, both answers, the judge's reasoning for both orders. | Then it checks its own work. Nemotron 3 Ultra judges the tuned model against its base on held-out questions, with the reference answer and the source passage in hand, and scores each pair in both orders. A win counts only if it holds in both. Win rate 57 percent over 30 questions: 7 wins, 20 ties and 3 losses. Consistency 67 percent. Here is one judged answer. | Nemotron 3 Ultra judges, both answer orders | recorded: the eval tab in `video/1-runs.webm`, and the stills `eval-view.png` and `eval-sample.png` |
| 5 | 1:55-2:25 | Playground: pick the base and tuned models from the run, paste one held-out question (chosen before the take, not after seeing the answers), send; both answers stream side by side. | Now the same held-out question goes to both models, streamed side by side. The tuned model answers in one line; the base invents a PRICE=SPOT format. The reference differs from both, so the judge called it a tie. Our keys stay on the server; the browser never sees them. | Held-out question, same prompt | recorded: `video/1-runs.webm`, 08:59:02Z to 08:59:09Z (both answers in 7 s), and `playground.png` |
| 6 | 2:25-2:45 | The run page's node cards, in two captures taken at different times, because the Job and the Endpoint never run at once. First the unsloth_train card reading "Nebius Job … RUNNING" (frame 14), then the vllm_serve card reading "Nebius Endpoint … RUNNING" (frame 20). There is no Nebius console capture. | Our Nemotron planner, teacher, judge and reporter run on Nebius Token Factory. The GPU path trains a Nemotron student on an AI Cloud Serverless Job and serves it from a Serverless Endpoint, with artifacts in Object Storage. | Nebius AI Cloud: Serverless Job and Endpoint | recorded: `frames/14-unsloth_train-running-RUNNING.png` and `frames/20-vllm_serve-running-RUNNING.png` |
| 7 | 2:45-2:55 | End card, text only: Orchapod.ai, the demo URL, github.com/bangadpurva/orchapod.ai, MIT, and "Nebius Token Factory, Nebius AI Cloud, NVIDIA Nemotron, Tavily". `{next}` takes at most 5 words. | Orchapod is open source under MIT. Try the hosted demo, or run it from the repo. Next: {next} | github.com/bangadpurva/orchapod.ai - MIT - app.orchapod.dev | TODO(D8): `{next}` (Hari's choice), and the repo public and checked logged out |

The numbers above are run 0ee1e20a's, as its screens show them:
- 23.5 minutes and 1.58 dollars ($1.5811).
- Win rate 57 percent (0.567) and consistency 67 percent (0.667), over 30 questions.
- 31x = 1,410 s of run over the 45 s of shot 3.
- Shot 5's sentence describes the take: the judge scored that pair a tie.
- `{next}` is still open: at most 5 words on what comes next (Hari's choice), which keeps shot 7 at 22 of its 23 words.
- The demo URL is shown, not spoken.

Say a claim only if the recorded run shows it; all of these hold for run 0ee1e20a:

- Shot 3: "Tavily finds and extracts" needs web-research to have succeeded with `urls` and `passages` above 0 in its metrics; "hard cap" needs the budget guard on for the recording instance; "fine-tunes … on a Nebius Serverless Job" needs unsloth-train to have succeeded on a Nebius Job; "vLLM serves base and tuned" needs vllm-serve to have succeeded with `lora_adapter`.
- Shot 4: the eval summary's `judge_model` is `nvidia/Nemotron-3-Ultra-550b-a55b` and the samples show both orders.
- Shot 5: "keys stay on the server" needs the playground to go through `POST /compare`, with no model call from the browser.
- Shot 6: "GPU path" and "Object Storage" need a Lane B run whose Job and Endpoint ran on Nebius AI Cloud and whose artifacts sit in a Nebius bucket. Otherwise use the Token Factory line below.

Alternatives (not in the table):

- Shot 2, template path (25 s): the template gallery, the card with its estimate in view, then one click on Run, which runs the reduced plan at once. "Pick a template. The card shows the estimate; one click runs the plan." Caption: "Template card with its estimate". Drop "Press Run." from shot 3.
- Shot 6, Token Factory only (20 s): "Our Nemotron planner, teacher, judge and reporter run on Nebius Token Factory, which also runs the fine-tune. Here is the job in the Token Factory console." Caption: "Nebius Token Factory". Use it when the golden run trains on Token Factory (Lane A, the real-estate topic), and never show a vast.ai run.

## Captions

- Burned in: the Caption column, one per shot, bottom left, white on a dark bar, at least 36 px at 1080p, on screen for the whole shot. The "sped up or cut" label stays on screen for the whole of every such segment: the planning wait in shot 2 and the time-lapse in shot 3.
- Closed: write an `.srt` from the recorded narration (the Voice-over column with the placeholders filled in) and the final cut's timings, and upload it to YouTube; do not rely on auto-captions for "Nemotron" or "Orchapod". It also serves viewers who watch muted.

## Recording

- One live run, recorded end to end from the first keystroke: it is the expensive part (the rehearsal took 23.5 minutes). Shots 2 and 4 can be retaken on the finished run or the hosted fixture (`make demo`); record two takes of each (PLAN.md, D8). Shots 5 and 6 cannot. The Running Endpoint exists only for `keep_alive_min` (15 minutes in the docs template; a longer keep-alive needs Hari's yes, contracts R14), judge-eval runs inside that window, and `/compare` refuses the endpoint once it has passed, so take both shots in what is left of it. The executor deletes the Job when it ends, so capture the Job while it trains. The control plane deletes the endpoint at expiry, as it did on both live runs (the rehearsal's at 09:12:20Z). Record the voice-over afterwards, over the cut, so it describes what is on screen.
- Recording instance: the hosted app at its public scale, `ORCHAPOD_ANON_SCALE=0.1`. Never raise it to 1 there: the GPU guard stops only callers below scale 1, so any visitor could then start GPU nodes. The rehearsal was recorded headless (Playwright), with the admin header (`X-Orchapod-Admin`) added only to the requests to the API. A local instance with the address bar out of frame works too. The take also needs a funded Token Factory key, Tavily credits and GPU quota.
- OBS Studio: one display capture, canvas and output 1920x1080 at 30 fps, hardware H.264 at about 12 Mbps, record to MKV and remux to MP4; the microphone is the only audio source, desktop audio off. Browser: a clean profile, no bookmarks bar or extensions, zoom 100%, Do Not Disturb on, no other tab.
- TODO(D8): play the upload back logged out and confirm it runs under 3:00.

## README and Devpost screenshots (D7)

Capture from the production build or the hosted app (`pnpm build && pnpm start`), not `pnpm dev`, whose overlay shows in the corner. 1440x900 viewport at 2x, PNG, the app's default theme, no browser chrome, the same safety rules as the video. The committed shots (082cf60) come from the hosted app on 2026-10-25. Every run-based shot is from the rehearsal run 0ee1e20a; `templates.png` is the public gallery. There are no Nebius console shots: the run page's node cards show the Job and the Endpoint with their live states instead (`run-view-train.png`, `run-view.png`). The README shows 7 of them inline and links the rest.

| File | Route and state | Must show | Goes in | Live run |
| --- | --- | --- | --- | --- |
| `docs/img/agent-plan.png` | /agent after Plan, no errors | the golden sentence's plan card: six nodes with their models, $2.66, Run enabled | What it is | done: 0ee1e20a's live plan |
| `docs/img/templates.png` | the template gallery at the public scale | the five templates with their estimates; three above a visitor's run cap | What it is (linked) | no |
| `docs/img/canvas.png` | /canvas/{id}?run={run_id} | the golden plan, each node coloured by its status | What it is | done: 0ee1e20a |
| `docs/img/dataset-card.png` | the intent #2 result card | the download link and the stats card | What it is | TODO(D8), optional: an intent #2 run on the hosted app |
| `docs/img/run-view.png` | /runs/{id}, mid-run | the vllm_serve card "Nebius Endpoint … RUNNING", the vLLM command in the log, Cost above $0 | Run the demo | done: 0ee1e20a |
| `docs/img/run-view-train.png` | /runs/{id}, while the Job trains | the unsloth_train card "Nebius Job … RUNNING" | Nebius AI Cloud (Lane B), in place of a console shot | done: 0ee1e20a |
| `docs/img/run-logs.png` | /runs/{id}, Logs tab, run ended | every node's log lines, kept after the run | Run the demo (linked) | done: 0ee1e20a |
| `docs/img/run-finished.png` | /runs/{id}, Artifacts tab, run ended | every node done with its cost, $1.581 in all, the artifacts | Costs and caps | done: 0ee1e20a |
| `docs/img/loss-chart.png` | /runs/{id}, Chart tab | train and validation loss over 60 steps | Results (linked) | done: 0ee1e20a |
| `docs/img/eval-view.png` | the eval view | win rate 57%, 7 wins, 20 ties, 3 losses, consistency 67% | Results | done: 0ee1e20a |
| `docs/img/eval-sample.png` | the eval view, sample #0 open | question, reference, both answers, the judge's reasoning | Results (linked) | done: 0ee1e20a |
| `docs/img/playground.png` | the Compare tab inside the keep-alive | base and tuned on held-out sample #0, side by side | Results | done: 0ee1e20a |
| `docs/img/run-report.png` | /runs/{id}, Report tab | Super's report: what ran, results, cost, how to use it | Run the demo (linked) | done: 0ee1e20a |
| `docs/img/multistate-eval.png` | /runs/{id}, Eval tab, of the multi-state run | win rate 68%, 11 wins, 19 ties, 0 losses, consistency 70%; base and tuned are GGUFs judged on CPU | Results (linked) | done: ca9838b7 |
| `docs/img/architecture.png` | a drawing, not a screenshot | control plane, node containers, providers, Nebius services | How it works | no |
