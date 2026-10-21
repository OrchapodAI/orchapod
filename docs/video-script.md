# Video script, shot list and screenshots

Draft from the beat list in `hackathon/PLAN.md` and the interfaces in `docs/contracts.md`. Every shot that needs a live run says TODO(D8), and every number the narrator says is a `{placeholder}` read off the golden run, never a guess. PLAN.md calls the one-sentence front door the Copilot; the product calls it the Orchapod Agent.

## Rules

- Public on YouTube, English, under 3:00: this cut ends at 2:55. No music and no sound effects, no third-party marks (PLAN.md, "What the submission must contain").
- Everything on screen is a real run. Every segment that is sped up or cut (the planning wait in shot 2, the whole run in shot 3) carries a "sped up or cut" caption. STUB output is never shown as a result, and no non-Nebius GPU footage appears as Nebius (spike 4 ran on vast.ai).
- Say only what ran. The narrator reads numbers off the screen, does not round them in our favour, and reads a win rate below 50% as it is.
- Sponsor names as text, no logos; crop console shots to the content area. No key, token, email or project id in frame (not `.env`, not a terminal).

## The golden run

One real run of the golden pipeline on Lane A, the G1 target: web-research, synth-distilabel (grounded), data-prep, tf-finetune, tf-deploy (or vllm-serve, if spike 1 shows Token Factory cannot serve the adapter per token), judge-eval, then the playground. Lane B is a separate run, and appears only in shot 6 if GPU quota lands by G2 (Oct 25). Default topic, from PLAN.md: the Nebius AI Cloud and Token Factory docs, because the judges can verify the answers and the base model is unlikely to know them. The alternative is canonical intent #1 (US real-estate compliance). TODO(D8): Hari picks the topic by D6; it changes the typed sentence and the held-out question. The sentence names its seed sites. Before recording, a live Nemotron 3 Super plan for it must come back with no errors; if it will not, use the topic's template card (alternative for shot 2): both topics have one, "Llama 8B tuned as a Nebius docs specialist" and "Llama 3B tuned on US real-estate compliance". One click on a card runs its reduced plan (fewer pages and rows, and 5 judged questions instead of 30), so the narrated numbers then come from that smaller run.

## Shot list

| # | Time | Screen | Voice-over | Caption | Live run |
| --- | --- | --- | --- | --- | --- |
| 1 | 0:00-0:15 | Title card, text only: "Orchapod.ai" and the caption line (not the 32-word tagline), 5 s. Then the empty /agent page with the cursor in "What should Orchapod build?". | Every team wants a cheaper, private specialist model. Making one takes an ML engineer and a pile of GPU plumbing. Orchapod does it from one sentence. | Describe the specialist model you want in one sentence | no |
| 2 | 0:15-0:40 | /agent. Type the golden sentence and press Plan; "Nemotron is planning…" shows, and the wait is sped up or cut to fit; the plan card appears. Hold on the table (node, type, models, estimate), then on the cost and time at the top right; end with the cursor on Run. Or click Run on the template card (its reduced plan runs at once; no Plan step). | Describe the model you want. Nemotron 3 Super, on Nebius Token Factory, drafts the pipeline from our node catalog. The server checks it against model and cost rules, and the plan card shows every node, every model and the estimated cost and time before anything runs. | Nemotron 3 Super plans the pipeline (wait sped up or cut) | TODO(D8): a live Nemotron 3 Super plan with no errors (Agent API, spike 2); else the template path (a reduced run) |
| 3 | 0:40-1:25 | Press Run. The run view under the plan, or /runs/{id}: nodes go from pending to running to succeeded, log lines stream, the Cost pill rises as each node reports. Time-lapse of the real run: cut at each node's change of status and keep the log timestamps in frame. Open the chart tab on the fine-tune's loss curve. End on the run's row in /runs: its Duration and Cost columns are where the voice-over's totals come from. | Press Run. Tavily finds and extracts the sources. Nemotron 3 Super writes grounded question-and-answer pairs from them, each with its source URL. Data prep removes duplicates and splits the data. Token Factory fine-tunes the small model with LoRA. Logs stream live, and the cost meter updates as each node reports what it spent, under a hard cap per run. The whole run took {minutes} minutes and cost {cost} dollars. | Real run, sped up or cut ({speedup}x) | TODO(D8): the golden run start to finish (live keys; spike 1 for the fine-tune price and the deploy path) |
| 4 | 1:25-1:55 | Eval view of the same run: win-rate stat, win/tie/loss bars, consistency. Then open one sample: question, reference, both answers, the judge's reasoning for both orders. | Then it checks its own work. Nemotron 3 Ultra judges the tuned model against its base on held-out questions, with the reference answer and the source passage in hand, and scores each pair in both orders. A win counts only if it holds in both. Win rate {win_rate} over {n} questions, consistency {consistency}. Here is one judged answer. | Nemotron 3 Ultra judges, both answer orders | TODO(D8): judge-eval results on the golden run and the eval view |
| 5 | 1:55-2:25 | Playground: pick the base and tuned models from the run, paste one held-out question (chosen before the take, not after seeing the answers), send; both answers stream side by side. | Now the same held-out question goes to both models, streamed side by side. {difference} Our keys stay on the server; the browser never sees them. | Held-out question, same prompt | TODO(D8): POST /compare, the playground and a tuned model that is up |
| 6 | 2:25-2:45 | Nebius console, cropped to the content area: the Serverless Job (state, platform) and the Endpoint (state Running) of the Lane B run. A run takes one lane, so this is a second run: show its run id first. The Endpoint exists only for `keep_alive_min` (30 minutes by default), so capture this shot inside that window. | Our Nemotron planner, teacher, judge and reporter run on Nebius Token Factory. The GPU path trains a Nemotron student on an AI Cloud Serverless Job and serves it from a Serverless Endpoint, with artifacts in Object Storage. | Nebius AI Cloud: Serverless Job and Endpoint | TODO(D8): a Lane B run on Nebius (GPU quota, G2 on Oct 25), else the Token Factory line below |
| 7 | 2:45-2:55 | End card, text only: Orchapod.ai, the demo URL, github.com/bangadpurva/orchapod.ai, MIT, and "Nebius Token Factory, Nebius AI Cloud, NVIDIA Nemotron, Tavily". `{next}` takes at most 5 words. | Orchapod is open source under MIT. Try the hosted demo, or run it from the repo. Next: {next} | github.com/bangadpurva/orchapod.ai - MIT - {demo_url} | TODO(D8): the hosted URL, and the repo public and checked logged out |

Placeholders, read off the golden run before the voice-over is recorded: `{minutes}` is the Duration of the run's row in /runs (or the first and last log timestamps) and `{cost}` its Cost (`cost_usd`); `{win_rate}`, `{n}` and `{consistency}` are the eval view's win rate, judged count and consistency; `{speedup}` is the real run's duration divided by the 45 s of shot 3, cuts included; `{difference}` is one sentence of at most 25 words on what the two playground answers show, written after the take; `{next}` is one line of at most 5 words on what comes next (Hari's choice), which keeps shot 7 at 22 of its 23 words; `{demo_url}` is the hosted URL, shown and not spoken.

Say a claim only if the golden run shows it:

- Shot 3: "Tavily finds and extracts" needs web-research to have succeeded with `urls` and `passages` above 0 in its metrics; "hard cap" needs the budget guard on for the recording instance; "fine-tunes the small model" needs tf-finetune to have succeeded on Token Factory.
- Shot 4: the eval summary's `judge_model` is `nvidia/Nemotron-3-Ultra-550b-a55b` and the samples show both orders.
- Shot 5: "keys stay on the server" needs the playground to go through `POST /compare`, with no model call from the browser.
- Shot 6: "GPU path" and "Object Storage" need a Lane B run whose Job and Endpoint ran on Nebius AI Cloud and whose artifacts sit in a Nebius bucket. Otherwise use the Token Factory line below.

Alternatives (not in the table):

- Shot 2, template path (25 s): the template gallery, the card with its estimate in view, then one click on Run, which runs the reduced plan at once. "Pick a template. The card shows the estimate; one click runs the plan." Caption: "Template card with its estimate". Drop "Press Run." from shot 3.
- Shot 6, Token Factory only (20 s): "Our Nemotron planner, teacher, judge and reporter run on Nebius Token Factory, which also runs the fine-tune. Here is the job in the Token Factory console." Caption: "Nebius Token Factory". Use it when there is no GPU quota by G2, and never show a vast.ai run.

## Captions

- Burned in: the Caption column, one per shot, bottom left, white on a dark bar, at least 36 px at 1080p, on screen for the whole shot. The "sped up or cut" label stays on screen for the whole of every such segment: the planning wait in shot 2 and the time-lapse in shot 3.
- Closed: write an `.srt` from the recorded narration (the Voice-over column with the placeholders filled in) and the final cut's timings, and upload it to YouTube; do not rely on auto-captions for "Nemotron" or "Orchapod". It also serves viewers who watch muted.

## Recording

- One live run, recorded end to end from the first keystroke: it is the expensive part (about 20 minutes, PLAN.md). Shots 2, 4 and 5 can be retaken on the finished run or the hosted fixture (`make demo`); record two takes of each (PLAN.md, D8). Shot 6 cannot: the Running Endpoint exists only for `keep_alive_min` (30 minutes by default; a longer keep-alive needs Hari's yes, contracts R14), so capture it in that window. Shot 5 also needs the tuned model up: a tf-deploy model on Token Factory stays up (contracts "tf-deploy"), but `/compare` refuses a vllm-serve endpoint once its `keep_alive_min` has passed, so with vllm-serve take shot 5 inside that window too. Record the voice-over afterwards, over the cut, so it describes what is on screen.
- Recording instance: the hosted app with `ORCHAPOD_ANON_SCALE=1` for the day (PLAN.md records on the hosted app), or a local instance with the address bar out of frame. The app sends no admin header, so at the default 0.1 the run cap is $0.30 and a plan whose estimate is above it is a plan error (`hackathon/LOG.md`, 2026-10-21T01:14Z). Also a funded Token Factory key, Tavily credits and, for shot 6, GPU quota. Restore the hosted scale afterwards.
- OBS Studio: one display capture, canvas and output 1920x1080 at 30 fps, hardware H.264 at about 12 Mbps, record to MKV and remux to MP4; the microphone is the only audio source, desktop audio off. Browser: a clean profile, no bookmarks bar or extensions, zoom 100%, Do Not Disturb on, no other tab.
- TODO(D8): play the upload back logged out and confirm it runs under 3:00.

## README and Devpost screenshots (D7)

Capture from the production build or the hosted app (`pnpm build && pnpm start`), not `pnpm dev`, whose overlay shows in the corner. 1440x900 viewport at 2x, PNG, the app's default theme, no browser chrome, the same safety rules as the video. Every run-based shot comes from the one golden run, whose id goes in the README Results. The README's Results section names the first four kinds (plan card, run view, eval view, playground).

| File | Route and state | Must show | Goes in | Live run |
| --- | --- | --- | --- | --- |
| `docs/img/agent-plan.png` | /agent after Plan, no errors | the sentence, the plan card: nodes with models, cost and time estimate, Run enabled | What it is | TODO(D8): a live plan |
| `docs/img/templates.png` | the template gallery | the templates with their estimates and one-click Run | What it is | no |
| `docs/img/canvas.png` | /canvas/{id} from "Edit on canvas" | the golden plan as nodes and edges | What it is | TODO(D8): a live plan |
| `docs/img/dataset-card.png` | the intent #2 result card | the download link and the stats card | What it is | TODO(D8): an intent #2 run (Nemotron 3 Super tokens only) |
| `docs/img/run-view.png` | /runs/{id}, golden run mid-run | one node succeeded, one running, log lines, Cost above $0 | Run the demo | TODO(D8): the golden run |
| `docs/img/run-finished.png` | /runs/{id}, run succeeded | every node succeeded with its cost, the total, the artifacts with the dataset download | Costs and caps | TODO(D8): the golden run |
| `docs/img/eval-view.png` | the eval view | win-rate stat, win/tie/loss bars, consistency | Results | TODO(D8): judge-eval on the golden run |
| `docs/img/eval-sample.png` | the eval view, one sample open | question, reference, both answers, the judge's reasoning for both orders | Results | TODO(D8): judge-eval on the golden run |
| `docs/img/playground.png` | the compare playground | base and tuned answers to one held-out question, side by side | Results | TODO(D8): POST /compare and a tuned model that is up |
| `docs/img/agent-report.png` | /agent, report card of the finished run | what ran, the metrics, cost against the estimate | Results | TODO(D8): the golden run |
| `docs/img/nebius-console.png` | Nebius console, cropped | the Lane B run's Serverless Job and Endpoint, or the golden run's Token Factory fine-tuning job; ids match the run page | Nebius AI Cloud (Lane B) | TODO(D8): a Lane B run on Nebius, or the Token Factory job |
| `docs/img/architecture.png` | a drawing, not a screenshot | control plane, node containers, providers, Nebius services | How it works | no |
