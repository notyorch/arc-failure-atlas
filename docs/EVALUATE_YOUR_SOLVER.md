# Evaluate your solver — step-by-step guide for testers

**Who this is for:** you already cloned this repo and have an ARC solver (a
model, a program, a DSL search, or a Kaggle/ARC-Prize `submission.json`). You
want to score it **locally** under one reproducible protocol.

**What ATLAS does for you:** it is the **judge**, not the solver. You bring
predictions; it parses them, scores them against ground truth, labels *why*
each one failed, and writes reproducible tables/figures.

**What this dashboard is:** a **local UI of this clone** (started with
`npx vite` when you want to look). It is **not** a website hosted 24/7.

> **Golden rule:** always integrate and **smoke-test small first**, then scale
> to a partial run, and only then do a full run. Never start with the full pack —
> you would burn hours (and API budget) just to discover a formatting bug.

---

## How a tester opens the dashboard

From the repo root (after you have runs, or to browse the bundled overview):

```bash
python scripts/export_frontend_data.py          # refresh frontend/public/data/overview.json
cd frontend
npm install                                     # once per machine / after pull
npx vite                                        # temporary local server → http://localhost:5173
```

Stop with Ctrl+C when done. After new evaluation runs, re-export and `npx vite`
again. Prefer `npx vite` over leaving a long-lived `npm run dev` process.

---

## The workflow at a glance

```
1. Python env         →  venv + pip (you're already in the clone)
2. Get tasks          →  mount a benchmark pack (ARC-AGI-1 / ARC-AGI-2 / example)
3. Pick your path     →  submission file · prediction dir · CLI · LLM-direct
4. SMOKE (3–6 tasks)  →  prove the wiring works & output parses   ← do this first
5. PARTIAL (optional) →  ~20–50 tasks, sanity-check behavior
6. FULL run           →  the whole pack, once smoke is clean
7. Refresh dashboard  →  export JSON + npx vite (ephemeral)
```

**"Before the full or partial run?"** — Steps 1–4 (env → mount tasks →
integrate → smoke) always come **first**. The smoke run is your integration
test. A partial run is an optional confidence check. The full run is last.
If the smoke fails, fix that before spending on anything bigger.

---

## Step 1 — Python env (once)

```bash
# already inside this clone
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Prove the platform itself works before touching your solver:
make test        # unit tests
make smoke       # isolated ETL → mock eval → analytics
```

If `make smoke` is green, the judge is healthy and any later failure is about
*your solver's output*, not the platform.

---

## Step 2 — Mount a benchmark pack

Task corpora are **not** shipped (they may be large/licensed). You mount them
into a pack, then run ETL once.

```bash
# Option A: the bundled tiny example pack (no download, great for a first smoke)
python src/main.py --benchmark-pack example_local_pack

# Option B: ARC-AGI-2 public evaluation set
# Official source: https://github.com/arcprize/ARC-AGI-2  →  data/evaluation/
# (license/use is your responsibility; this repo never auto-downloads it)
cp /path/to/ARC-AGI-2/data/evaluation/*.json benchmark_packs/arc_agi_2/tasks/
python src/main.py --benchmark-pack arc_agi_2

python src/main.py --list-benchmark-packs   # confirm task_count > 0
```

**Pack accumulation (important):** ETL writes into the same Hive tree
(`data/parquet/evaluation/`, partitioned by `task_id`). Packs **accumulate** —
running `example_local_pack` after `arc_agi_2` leaves both sets of tasks in the
corpus, and `_benchmark_pack.json` reflects only the **last** pack processed.
Before a real AGI-2 run, re-ETL the target pack:

```bash
python src/main.py --benchmark-pack arc_agi_2
```

To keep corpora isolated, use a separate root:

```bash
python src/main.py --benchmark-pack example_local_pack \
  --output-root /tmp/atlas-example-parquet
```

See [`BENCHMARK_PACKS.md`](BENCHMARK_PACKS.md) for pack structure/manifests.

---

## Step 3 — Pick your integration path

Choose the **lowest-friction** path that matches what your solver already
produces. You do **not** need to implement a Python `solve()` or install our
providers unless you want the LLM-direct path.

| Your artifact | Path | Adapter |
| --- | --- | --- |
| Kaggle-style `submission.json` | **A** | `submission_file` |
| One JSON of predictions per task | **B** | `submission_dir` |
| A command-line program (stdin→stdout) | **C** | `subprocess_cli` |
| Just a model behind an API key | **D** | LLM-direct |

Full adapter reference: [`SOLVER_ADAPTERS.md`](SOLVER_ADAPTERS.md) ·
copy-paste examples: [`QUICKSTART_EXTERNAL_SOLVER.md`](QUICKSTART_EXTERNAL_SOLVER.md)
and `examples/external_solver/`.

---

## Step 4 — SMOKE first (3–6 tasks) — the integration test

### Path A/B — submission-first (recommended, no model calls)

> **Partial submissions vs full packs.** `evaluate-submission` scores your
> artifact against **every** `(task, test)` in the mounted tasks Parquet.
> Tasks present in the pack but **absent** from the submission become
> `execution_error` rows — that is intentional **coverage** visibility, not a
> solver crash. A 2-task smoke against a 120-task pack will look like
> "solved 2 / 169, 167 execution_error". For a scoped smoke, always pass
> `--task-id id1,id2,...` (or `--limit`).

```bash
# 1) validate the shape BEFORE scoring — catches bad JSON / non-rect grids
python src/submission_cli.py validate-submission \
  --path examples/external_solver/submission.json

# 2) score ONLY the tasks in the fixture (sample01, sample02)
python src/submission_cli.py evaluate-submission \
  --path examples/external_solver/submission.json \
  --solver-name my-system --experiment-id smoke \
  --task-id sample01,sample02

# 3) build analytics for the smoke
python src/build_analytics.py --experiment-id smoke
```

### Path C — wrap a CLI solver

Register the entry in **`configs/solvers.json`** (copy a snippet from
`examples/external_solver/solvers.snippet.json`), then dry-run:

```bash
python src/run_evaluation.py --solver my-cli-solver --limit 3 --dry-run
```

### Path D — LLM-direct smoke (uses your API key + budget)

```bash
export OPENAI_API_KEY="…"                       # your key, kept in your shell only
export OPENAI_BASE_URL="https://opencode.ai/zen/go/v1"

python src/run_evaluation.py \
  --provider openai --model glm-5.2 \
  --prompt-version arc_grid_v2 \
  --benchmark-pack arc_agi_2 \
  --limit 5 --attempts 1 \
  --experiment-id smoke
```

**What "smoke passed" means:**

| Check | Expect |
| --- | --- |
| `validate-submission` | `status: OK`, 0 errors |
| run completes | a run dir with `_manifest.json` is written |
| parse errors | **low** — high `parse_error` = output is not a clean grid; fix formatting before scaling |
| execution errors | on a **scoped** smoke (`--task-id` / `--limit`), should be near zero. A flood of `execution_error` after scoring a partial submission against the full pack is **coverage gap**, not a broken judge |
| analytics | `summary_by_solver.csv` with a `solved_rate` you can read |

> A high `parse_error` rate is a **model/output-format** problem, not a wrong
> answer and not a broken judge. Fix it at smoke stage — it is the single most
> common reason a full run wastes time.
>
> A high `execution_error` rate on a submission run usually means the pack has
> more tasks than your artifact. Scope with `--task-id` / `--limit`, or submit
> predictions for the full pack.

---

## Step 5 — Partial run (optional confidence check)

Once the smoke is clean, scale to a representative subset (e.g. 20–50 tasks) to
see real behavior without paying for the full pack:

```bash
python src/run_evaluation.py \
  --provider openai --model glm-5.2 --prompt-version arc_grid_v2 \
  --benchmark-pack arc_agi_2 --limit 30 --experiment-id partial
python src/build_analytics.py --experiment-id partial
```

---

## Step 6 — Full run

Only after smoke (and ideally partial) look right:

```bash
python src/run_evaluation.py \
  --provider openai --model glm-5.2 --prompt-version arc_grid_v2 \
  --benchmark-pack arc_agi_2 --experiment-id full-run
python src/build_analytics.py --experiment-id full-run
```

Submission-first: drop `--limit` / point at your full `submission.json`.
For ARC-style pass@2, add `--attempts 2`.

---

## Step 7 — Read results + refresh this dashboard

**Tables (`data/parquet/.../` + `reports/tables/`)** — the numbers that matter:

- `solved_rate` — item-level pass@k (per test example).
- `task_solved_rate` — **ARC-official** (a task counts only if *all* its test
  examples are correct).
- `exact_match_rate` — per attempt.
- `parse_error_rate` — output could not be read as a grid (≠ wrong answer).

**Local dashboard** (this UI — ephemeral, not deployed):

```bash
python scripts/export_frontend_data.py --run-id <your_run_id>
cd frontend && npm install && npx vite   # http://localhost:5173 · Ctrl+C when done
```

The **All runs** table shows your runs newest-first and keeps `parse_error` in
its own column so you never confuse "couldn't read it" with "read it, but wrong".

---

## FAQ

**Do I have to change my solver's code?**
No. Paths A–C accept the artifacts you already produce. Only Path D calls a model
directly.

**Where does my API key live?**
Only in your shell environment. The pipeline reads `os.environ`; it never writes
keys to disk and `.env` is gitignored. Rotate any key you paste into a chat.

**Are my results uploaded anywhere?**
No. Everything is local. Run outputs land under `data/` (gitignored). The
"public observatory" is *curated public context only*, never your data.

**My solved_rate is 0% — is the judge broken?**
Check `parse_error_rate` first. High parse error = output-format issue. Low parse
error with 0% solved = genuinely hard tasks, not an infrastructure failure.

---

Related: [`QUICKSTART_EXTERNAL_SOLVER.md`](QUICKSTART_EXTERNAL_SOLVER.md) ·
[`SOLVER_ADAPTERS.md`](SOLVER_ADAPTERS.md) ·
[`BENCHMARK_PACKS.md`](BENCHMARK_PACKS.md) ·
[`PUBLIC_RESULTS_OBSERVATORY.md`](PUBLIC_RESULTS_OBSERVATORY.md)
