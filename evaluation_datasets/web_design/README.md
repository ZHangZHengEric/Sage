# Web Design v2: Interactive Beauty and Art

An original fixed dataset: **20 training / 10 dev / 10 test** tasks.
Every brief is different and leaves the visual direction open. Each includes a use case and a few interaction requirements. Dev is named `validation` in the JSON.
There are no reference designs or hidden style prompts. This measures relative
visual preference, not an objective design leaderboard.

## Task coverage

All three splits cover ten uses: brand sites, interactive stories, data exploration,
creative tools, learning, playful experiences, workspaces, collections, configurators
and immersive experiences. Training has two tasks per use; dev and test have one each.
Only four of the forty tasks are brand sites.

Complexity varies from a palette mixer or branching story to a linked exhibition
planner, film-night workspace, data explorer or live design editor with undo.
Briefs specify user actions, not a layout or style. Sample data and local state are
enough; no backend or external service is required. Beauty remains the main goal,
with usefulness and coherent interaction states judged against each brief.

## Setup

Run from the Sage repository root with Python 3.12 or newer:

```sh
python3 -m venv evaluation_datasets/web_design/.venv
evaluation_datasets/web_design/.venv/bin/python -m pip install -e '.[desktop]' -r evaluation_datasets/web_design/requirements.txt
evaluation_datasets/web_design/.venv/bin/python -m playwright install chromium
evaluation_datasets/web_design/.venv/bin/python -m evaluation_datasets.web_design.preflight
```

On Linux, install browser libraries with `playwright install --with-deps chromium`.
On Windows use `.venv/Scripts/python.exe`. No dataset MCP server, Docker, database,
Node.js or website build step is required. The local `.venv` stays separate from
Sage's environment. Preflight uses real Chromium and no paid model calls.

## Standard lint runtime

RSI automatically selects Sage's standard lint environment when the target Agent
has `read_lints`. Desktop and MCP use the same default; no per-experiment path or
permission setting is needed. Missing dependencies fail admission before model calls.

For a source checkout, install the runtime once, then validate it:

```sh
npm ci --prefix sagents/v2/tool/official/lint --ignore-scripts --no-audit --no-fund
.venv/bin/python -m evaluation_datasets.web_design.lint_preflight
```

Node.js must be on the host PATH. The preflight uses the real isolated sandbox and
checks valid and invalid JavaScript, HTML and CSS, with no model calls.
ESLint versions and rules live with Sage's official tool, not with this dataset.
The host freezes the selected environment and rejects changes on resume. Target
processes are bounded and network-disabled; no Shell tool is added to the Agent.
Eval and Tuner roles retain their existing process restrictions. Advanced API/MCP
clients can still supply `lint_environment` as an explicit override.

## Test in Desktop

1. Restart the backend after updating Sage. Create a dedicated Agent.
2. Copy `baseline.system.txt` into its system prompt. It only describes the
   workspace, entry file and submission rules; it contains no aesthetic guidance.
3. Enable Sage's built-in `file_write`, `file_update`, `file_read`, `list_dir` and
   `turn_status`, `read_lints` and `load_skill`. Start with no Skills and disable memory. No WebDesign MCP connection is needed.
4. Use the same 48-step budget for the baseline and candidates. Select a tool-calling
   target model and a vision-capable RSI model. Keep model settings fixed within a run.
5. Import `rsi.dataset.json` and `scorer.py` in RSI. Keep `scorer.runtime.json` beside
   the source. The plugin selects pairwise mode and this directory's Python.
6. Paste `goal.txt` into the optimization goal. Optimize instructions and Skills,
   allowing up to five Skills; keep the tools fixed. Disable automatic generation of new tasks.
7. For the full experiment use five rounds, two repeats for train/dev and test,
   concurrency eight, and all 20 training, 10 dev and 10 test tasks.
   `experiment.settings.json` records these settings; it is not a Desktop import file.
   Use equal budgets and repeats for both sides. `baseline.package.json` is the corresponding SDK package, not a
   Desktop settings import.

The baseline system prompt supplies technical requirements only. RSI can learn
reusable design instructions and up to five Skills from training feedback. Do not add design Skills or
style advice to the baseline when comparing experiments.

## Lint checks

Baseline and candidate Agents both have Sage's built-in `read_lints` tool.
It checks HTML5 parsing and CSS syntax locally, including `<style>` blocks and
`style` attributes. Ruff handles Python; an installed ESLint handles JavaScript or
TypeScript. The tool does not download packages. External checks need a usable
local installation and configuration.

Only `passed: true` confirms every requested check completed without diagnostics.
`passed: false` means completed checks found issues. `passed: null` means at least
one check was unsupported, unavailable, still running or failed. An empty
`diagnostics` list alone does not mean success. Lint results stay in execution
evidence. CSS checks cover structure and declarations, not property-value validity,
visual layout or interaction behavior. Inline JavaScript is not checked. Rendering
does not repair code.

## Deliverables and isolation

Use `index.html` as the entry point, with relative local HTML, CSS, JS and SVG files.
UTF-8 JSON and TXT resources are also supported. Each case and repeat gets a fresh
Sage workspace. Use `file_update` for edits and serialize mutations to the same file.
When ready, use native `turn_status(status="task_done")` and a short completion reply.
There is no dataset-specific `finish` tool.

The plugin checks canonical native file receipts and uses the host's hashed final
workspace files. These are captured before cleanup, so overlapping edits use the
actual saved output. Older recordings use append/update replay; ambiguous parallel
edits fail measurement. Unknown mutations and missing receipts also fail.
Limit final source to 64 files and 1 MiB. Use local assets, inline SVG
or data images; external URLs and package builds are unavailable.

## Screenshots

`scorer.py` declares **prepare only** and makes no model calls. It freezes the final
source, opens `index.html` and follows up to two linked local HTML pages.
Each page uses desktop 1440x1000, tablet 768x1024 and mobile 390x844 viewports.
For long documents, capture four evenly spaced scroll positions including top and
bottom. Short pages need fewer frames.

Frames use labeled square **n-by-n contact boards**, normally 2x2, in row-major
order. Every board is at most 1920x1920. Frames preserve their aspect ratio.
Full-resolution PNGs, source and the screenshot manifest remain available for audit.
JPEG boards use the same per-image budget for both sides. Up to four local browser
processes render at once; this does not change the eight concurrent RSI case slots.

The browser uses a fixed locale, starting time, light color scheme and reduced
motion. External requests are blocked. Fragment links are covered by scrolling;
On each viewport, extra boards capture before/after states of up to two visible
homepage controls in DOM order: buttons, tabs, disclosures, ranges or selects.
Resource responses, JavaScript errors and stylesheet rule counts are recorded for
diagnosis. The renderer never repairs submitted code.

All desktop, tablet and mobile JPEG boards are passed to the Eval Agent, not just
retained on disk. These are responsive viewport captures in Chromium, not separate
Safari or real-device tests. Arbitrary multi-step flows, hover, drag gestures and
animation quality are not fully tested. Uncaptured behavior remains unverified;
this is visual preference evaluation, not complete functional certification.

## Judgment, analysis and selection

The initial baseline receives single-result analysis against the brief and goal.
There is no score or comparison yet. It is not compared with a duplicate of itself.

The Eval Agent first receives the **brief + optimization goal + anonymous A/B
screenshots**. Its fixed rubric prioritizes beauty, visual appeal and artistic
expression: composition, typography, color, imagery, rhythm, originality and
coherent art direction. No style is preferred in advance. More pages, features or
words do not earn credit. It returns A/B/tie and concrete visual reasoning.

For training, a separate analysis step receives the fixed judgment, screenshots, anonymous
execution summaries and complete final source. These are bounded, read-only input
files with verified read coverage. The timeline retains assistant actions, tools,
arguments, outcomes and mutation hashes. Full earlier write bodies stay in the
host's native execution archive rather than being copied repeatedly into analysis.
The analysis explains supported causes, uncertainty and possible improvements;
it cannot change the judgment. Dev and test still receive real paired judgments,
but skip unused separate training analysis.

Missing index.html is an invalid submission. Browser or evidence failures are
measurement failures, never fabricated losses or ties. Sage repeats comparisons
in reverse presentation order. Disagreement counts as a tie. Repeats pair by index;
no best-of selection or all-to-all matching is used.

A native loop guard may stop a task before its final reply. Only a prefix with
complete receipts and confirmed outcomes can be rendered. Rejected native calls
must explicitly confirm that nothing was applied. The original run stays
suspended; evaluating its artifact does not declare task success. Unknown effects,
approvals and provider failures remain missing measurements. Failed executions
are archived separately from reusable completed measurements.

Auxiliary project files, including README files, are retained as text for audit.
Only HTML pages are rendered. The host never executes project scripts or build
steps. Relative paths, file counts and total source size remain bounded.
Native absolute file paths are accepted only under the run-bound workspace roots
declared by the host. They are converted into relative artifact names.

Train/dev compare directly against the retained incumbent. Test compares against
the original baseline. Preferences need not be transitive. Only training analyses
enter modification directions and tuning; dev/test evidence stays separate.
Keep the judge model, renderer, goal and rubric fixed. Inspect a sample of saved
images and judgments before interpreting win rates. Preflight does not establish
live aesthetic judgment quality.

### Frozen scorer execution

Import the scorer after changing its code or dependencies. Sage copies its local
source dependencies and framework worker code into a content-addressed runtime
snapshot. Worker processes import that snapshot, so edits to the development
checkout do not change an admitted scorer. Snapshot tampering is still rejected.
The Python environment remains version-checked; do not upgrade it during a run.
Existing scorer versions keep their old binding. Reimport to use the new isolation.


Rendering uses a seeded random sequence, not a constant random value. This keeps
captures repeatable without breaking unique sampling or random UI actions.
`render-progress.json` records queue, navigation, screenshot and interaction
phases for diagnosis. Scorer timeout cleanup terminates the worker process group
on POSIX, including its browser descendants. Missing capture evidence remains a
measurement failure, never an automatic aesthetic loss.
