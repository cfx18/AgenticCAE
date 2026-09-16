# Kimi Perception Smoke And Xifeng Resource Discovery

Date: 2026-09-16. Work confined to `E:/AgenticCAE`.

## Scope

This is a difficulty/calibration smoke, not proof that the pilot improves a model.
Native Kimi Code 0.43.1, configured model `kimi-k3`, receives only each public
question and raster images through a three-tool MCP: observe, conclude, submit.
The CLI agent profile AND tool configuration allow only those three names.
There are no shell, filesystem read, browser, network, delegation or code
execution tools. This is a capability restriction, not an audited OS sandbox.
The trusted MCP returns only images named in `public/task.json`, validates crop
bounds, records exact returned image hashes, and accepts one JSON submission.
No private correctness feedback is returned to the model. Private grading runs
after the CLI process exits. The human review web server is not a model tool.

Fifteen JSON-answer tasks are selected in advance. Five CAD execution tasks are
not run here: three repairs and two reconstructions still require the planned
execution sandbox. Projection tasks in this smoke use the two raster exports;
the agent cannot inspect STEP topology. This is not the unrestricted native
Kimi + AutoCAD benchmark and must not be compared as if the harness were identical.

The user is correct that the fixtures are simple. Clarification prompts already
identify missing axial information; cross-view prompts and drawings explicitly
name axes; dimensions are clean and sparse. A correct answer does not demonstrate
robustness to a dense industrial drawing, or transfer to OmniMech bad cases.
Keep these as smoke/regression fixtures unless harder evidence justifies promotion.

## Reproduction And Records

```powershell
.local/posttrain-env/Scripts/python.exe evals/posttrain/run_kimi_smoke.py .local/posttrain/new-kimi-smoke
.local/posttrain-env/Scripts/python.exe evals/posttrain/summarize_kimi_smoke.py .local/posttrain/new-summary.json .local/posttrain/new-kimi-smoke
```

Environment credentials are read from the existing Kimi `.env`, never copied
into task packages, command records or prompts. Generated CLI homes, media,
temporary files and logs are workspace-local. Each task has a 180-second timeout;
timeouts remain ungraded rather than silently becoming geometry errors.

- `kimi-smoke-r1`: CLI configuration failure (`--auto` cannot accompany `--prompt`),
  before model/tool activity; not a model attempt in accuracy calculations.
- `kimi-smoke-r2/line-01`: corrected first real inference, selected before outcomes.
- `kimi-smoke-r3`: the remaining fourteen perception tasks, one attempt each.
- Per-run `prompt.txt`, `run.json`, native `kimi-events.jsonl`, `stderr.log`.
- Per-episode `events.jsonl`: hash-chained observation intents, actual crop bounds,
  exact image paths/hashes, brief public findings and final submission receipts.
- `private-verdict.json`: evaluator-side field checks, not model feedback.
- `summarize_kimi_smoke.py`: offline extraction, verifies event chains and image
  hashes, flags tool names outside the configured allowlist; never reruns a model.

## Completed Smoke Results

The original 180-second-per-task smoke completed all 15 attempts: 14 correct
submissions and one timeout without a final answer. Deadline success is 14/15
(93.33%); submitted-answer accuracy is 14/14. These denominators are different.
The five unrun CAD tasks are excluded from both, not counted as passes.

There were 45 image observations, including 21 crops, and 29 brief public findings.
Every event chain and returned image hash passed offline validation. Observed
tool names were only the three configured public MCP tools. Combined records:
`.local/posttrain/kimi-smoke-summary-r1.json`.

The timeout was `projection-01`: nine image observations, seven crops, no recorded
finding and no submitted answer before 180 seconds. It had successfully received
the images; stderr reported no transport error. This is an observation/latency
finding, not proof of a line-semantics incapability.

A separate fresh diagnostic attempt on that task used the same inputs, profile
and no correctness feedback, with a 600-second allowance. It submitted the correct
answer in 238.80 seconds, after eight observations and four public findings:
hidden edges were rendered solid, and geometry did not need changing.
Path: `.local/posttrain/kimi-smoke-timeout-diagnostic-r1/`.
This was a new stochastic attempt, not a continuation; it does not prove the
original attempt would have finished correctly. It does show capability on this
fixture. The diagnostic result never replaces the original timeout or turns the
initial smoke into a 15/15 claim.

Conclusion: these tasks are useful for plumbing/regression and reveal excessive
local inspection in at least this run, but do not establish valuable training
signal for the OmniMech failures. They are mostly too easy/explicit to be the
main training pool. No SFT/RL or downstream learning effect was measured.

Regression checks: 93 passed, 2 skipped (existing optional trimesh tests).
Do not infer model accuracy from the separate 20/20 trusted-reference acceptance.

## Website Acquisition Probe

Source: <https://xifengboke.com/category-8_2.html>.
The exercise category advertises 59 pages. The bounded probe follows only pages
2 and 3, then eight listed articles plus two explicitly selected drawing articles.

Canonical probe: `.local/posttrain/xifeng-discovery-r2/`.
It contains 28 indexed article URLs, 10 inspected article records and 155 unique
image URLs within their respective articles. Section-heading heuristics identify
137 solution-step candidates, 7 target-render candidates, 7 input-drawing
candidates and 4 unclassified images. These are **unreviewed role hints**, not
verified image semantics, global deduplication or 155 independent training tasks.
Nine article download sections require VIP/login; one exposes a public download
link. No CAD file or valid CAD/drawing GT pair has been acquired.

The first probe included a site icon as an image; r2 excludes non-raster formats.
Two public preview downloads were attempted. The image CDN's robots endpoint
returned HTTP 403, so the acquisition helper stopped instead of bypassing the
restriction. Independent web retrieval of a listed drawing image also returned
403. **Zero preview files downloaded.** Public metadata remains useful even
when the underlying image or download is unavailable.

Priority candidates, not accepted data:

- <https://xifengboke.com/post/1936.html>: reducer component/assembly drawing
  examples; useful for multi-view, section and assembly questions after inspecting
  actual files. High-resolution PDF download is member-gated; CAD GT not confirmed.
- <https://xifengboke.com/post/2627.html>: competition assembly/part drawing package,
  exposed cloud-drive link; downloadable PDF is advertised, not verified CAD GT.
  Freeform design questions must not be graded against a falsely unique solid.
- <https://xifengboke.com/post/2679.html>: drawing paired with a gated modelling
  video/source download section; potentially useful after authorized acquisition.
- <https://xifengboke.com/post/1576.html>: drill tutorial with modelling screenshots,
  not automatically a complete multiview drawing input. Gated model source.

The site disclaimer retains original-author copyright, restricts commercial use
and asks that learning/testing downloads be deleted within 24 hours. Research-only
intent and VIP access do not by themselves establish training or redistribution
permission. Catalog entries are marked `permission_required`, `training_eligible:
false`, and `no_cad_file_acquired_or_verified`. No site content enters SFT/RL.
Index dates may be refreshed; do not label them original publication dates.

```powershell
$env:PYTHONPATH = "$PWD/src"
.local/posttrain-env/Scripts/python.exe -m cad_evoloop.posttrain.web_discovery .local/posttrain/new-xifeng-probe --details 8 --extra-posts 1936 2679 --sample-posts 1936 2679
```

The helper uses a descriptive user agent, single-threaded rate limiting, robots
checks, allowed hosts, redirect guards, per-file and total byte limits, HTML
parsing, hashes and request audit. It does not fetch hidden links, scrape login
forms, evade challenges, remove watermarks, or execute downloaded code. Metadata
is separate from optional short-lived inspection previews. Preview expiry would
be recorded, not automatically enforced; the current probe has none to expire.

After the user confirmed no VIP and requested public resources only, the catalog
was extended with index pages 1, 4, 5, 20 and 40. Combined with pages 2 and 3 this
gives **99 distinct article URLs**, not 99 downloadable or GT-backed tasks.
Additional index: `.local/posttrain/xifeng-public-index-r1/`.
Four further competition drawing pages were inspected under
`.local/posttrain/xifeng-public-drawings-r1/`, all exposing public download links:

- <https://xifengboke.com/post/2586.html>: horizontal plunger pump.
- <https://xifengboke.com/post/2574.html>: harvester gearbox, housing and milling cutter.
- <https://xifengboke.com/post/2573.html>: ejector assembly/parts.
- <https://xifengboke.com/post/2572.html>: compressor drawing package.

Together with post 2627, there are **5 public-download candidates among 14
inspected articles**; the other 9 are member-gated. These five are advertised
drawing packages, not verified CAD truth. The ejector task explicitly requires
designing some undimensioned parts from assembly relationships; do not invent a
unique solid GT for those parts. Cloud-drive retrieval could not be completed
through the available web/browser session, so no file contents are claimed.

Merged public catalog: `.local/posttrain/xifeng-public-catalog-r1.json`, generated
by `evals/posttrain/merge_web_discovery.py`. It preserves probe hashes, article
URLs, access/rights states and visible public download targets. No VIP links
were retrieved, no images/PDFs/CAD files were downloaded, and no resource was
promoted into the training corpus.

## Promotion To Training Data

1. Resolve source-owner permissions and obtain the actual drawing and native CAD
   files through authorized download. Keep their ancestry and licenses separate.
2. Validate file types, archive paths and hashes; quarantine scripts/macros and
   executables. Never execute a downloaded tutorial to obtain its alleged GT.
3. Convert authorized CAD to STEP with units, frame and topology recorded. Check
   drawing dimensions against the solid. Mark unresolved dimensions as ambiguous.
4. Separate problem drawings from solution screenshots, videos and feature trees.
   Teacher outputs are not learner input. Preserve genuine missing-information
   requests; do not insert all desired dimensions into the prompt by default.
5. Make feature-level questions about line roles, section/hidden geometry,
   dimension attachment and localized repairs, with checked reference evidence.
   A newly reconstructed solid is a reviewed reference candidate, not original GT.
6. Calibrate on Kimi, including text-only controls for prompt shortcuts. Retain
   useful failures; split by original design and template, not image or crop.

Next gate: resource access/permission review and harder source/GT pairing, not
mass downloading tutorials or multiplying easy box/ring fixtures.
