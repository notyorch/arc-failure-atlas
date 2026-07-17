import { useState } from "react"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

const STEPS = [
  {
    id: 1,
    title: "Python env (once)",
    summary: "You're already in this clone. Activate a venv and install deps.",
    detail: (
      <>
        <pre className="code-block">{`# from the repo root (this project)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# prove the judge works before your solver:
make test && make smoke`}</pre>
        <p className="mt-3 text-sm text-muted">
          If <code className="text-code">make smoke</code> is green, later failures are
          about <em>your</em> output — not ATLAS. This dashboard is a local view of
          that same clone, not a hosted site.
        </p>
      </>
    ),
  },
  {
    id: 2,
    title: "Mount a pack",
    summary: "Task corpora are gitignored. Packs accumulate in one Parquet tree.",
    detail: (
      <>
        <pre className="code-block">{`# Tiny example (no download)
python src/main.py --benchmark-pack example_local_pack

# ARC-AGI-2: https://github.com/arcprize/ARC-AGI-2 → data/evaluation/
cp /path/to/ARC-AGI-2/data/evaluation/*.json benchmark_packs/arc_agi_2/tasks/
python src/main.py --benchmark-pack arc_agi_2`}</pre>
        <p className="mt-3 text-sm text-muted">
          ETL accumulates by <code className="text-code">task_id</code>; the sidecar
          reflects the <em>last</em> pack. Re-ETL the target pack before a real run,
          or isolate with <code className="text-code">--output-root</code>.
        </p>
      </>
    ),
  },
  {
    id: 3,
    title: "Pick your path",
    summary: "Lowest friction first — you usually don't rewrite your solver.",
    detail: (
      <>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[480px] text-left text-sm">
          <thead className="border-b border-border text-[11px] font-bold uppercase tracking-[0.12em] text-muted">
            <tr>
              <th className="py-2 pr-3">Your artifact</th>
              <th className="py-2 pr-3">Path</th>
              <th className="py-2">Adapter</th>
            </tr>
          </thead>
          <tbody>
            {[
              ["Kaggle-style submission.json", "A", "submission_file"],
              ["One JSON per task", "B", "submission_dir"],
              ["CLI program (stdin→stdout)", "C", "subprocess_cli"],
              ["Model behind an API key", "D", "LLM-direct"],
            ].map(([a, b, c]) => (
              <tr key={b} className="border-b border-border/40">
                <td className="py-2.5 pr-3 text-foreground">{a}</td>
                <td className="py-2.5 pr-3 font-mono text-code">{b}</td>
                <td className="py-2.5 font-mono text-xs text-code">{c}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-sm text-muted">
        Path C: copy a snippet from{" "}
        <code className="text-code">examples/external_solver/solvers.snippet.json</code>{" "}
        into <code className="text-code">configs/solvers.json</code>.
      </p>
      </>
    ),
  },
  {
    id: 4,
    title: "SMOKE first",
    summary: "3–6 tasks. The integration test — always before partial or full.",
    detail: (
      <>
        <p className="mb-3 text-sm text-muted">
          Submission-first (recommended, no model calls):
        </p>
        <pre className="code-block">{`python src/submission_cli.py validate-submission \\
  --path examples/external_solver/submission.json
python src/submission_cli.py evaluate-submission \\
  --path examples/external_solver/submission.json \\
  --solver-name my-system --experiment-id smoke \\
  --task-id sample01,sample02
python src/build_analytics.py --experiment-id smoke`}</pre>
        <p className="mt-4 text-sm text-muted">
          Pass criteria: validate OK · run writes <code className="text-code">_manifest.json</code> ·
          low <code className="text-code">parse_error</code> · near-zero{" "}
          <code className="text-code">execution_error</code> on a{" "}
          <em>scoped</em> smoke. Without <code className="text-code">--task-id</code>,
          missing pack tasks become <code className="text-code">execution_error</code>{" "}
          (= coverage gap, not a broken judge).
        </p>
      </>
    ),
  },
  {
    id: 5,
    title: "Partial (optional)",
    summary: "~20–50 tasks. Confidence check without paying for the full pack.",
    detail: (
      <pre className="code-block">{`python src/run_evaluation.py \\
  --provider openai --model glm-5.2 --prompt-version arc_grid_v2 \\
  --benchmark-pack arc_agi_2 --limit 30 --experiment-id partial
python src/build_analytics.py --experiment-id partial`}</pre>
    ),
  },
  {
    id: 6,
    title: "Full run",
    summary: "Only after smoke (and ideally partial) looks right.",
    detail: (
      <>
        <pre className="code-block">{`python src/run_evaluation.py \\
  --provider openai --model glm-5.2 --prompt-version arc_grid_v2 \\
  --benchmark-pack arc_agi_2 --experiment-id full-run
python src/build_analytics.py --experiment-id full-run`}</pre>
        <p className="mt-3 text-sm text-muted">
          For ARC-style pass@2 add <code className="text-code">--attempts 2</code>.
          Submission-first: point at your full <code className="text-code">submission.json</code>.
        </p>
      </>
    ),
  },
  {
    id: 7,
    title: "Refresh this dashboard",
    summary: "Export JSON, then open a temporary local UI with npx (no long-running deploy).",
    detail: (
      <>
        <pre className="code-block">{`# from repo root — refresh overview.json from your runs
python scripts/export_frontend_data.py --run-id <your_run_id>

# temporary local UI (Ctrl+C when done)
cd frontend
npm install          # once per machine / after pull
npx vite             # http://localhost:5173`}</pre>
        <p className="mt-3 text-sm text-muted">
          This page is the dashboard of <em>this</em> clone. Nothing is hosted 24/7 —
          <code className="text-code">npx vite</code> is an ephemeral local server you start
          when you want to look at results.
        </p>
      </>
    ),
  },
]

export function GuideSection() {
  const [open, setOpen] = useState(4)

  return (
    <section id="guide" className="scroll-mt-20 section-rule border-b">
      <div className="mx-auto max-w-6xl px-5 py-14 md:px-8">
        <div className="mb-8 anim-rise">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="font-sans text-3xl font-bold tracking-tight text-heading">
                Evaluate your solver
              </h2>
              <p className="mt-3 max-w-2xl text-sm font-normal text-muted">
                You already have this repo open — this UI is the{" "}
                <strong className="text-foreground">local dashboard</strong> of your clone,
                not a public landing page. ATLAS is the{" "}
                <strong className="text-foreground">judge</strong>: bring predictions, score
                them, label failures. Always smoke first.
              </p>
            </div>
            <Badge variant="accent">Local · for testers</Badge>
          </div>

          <div className="mt-6 glass-soft rounded-2xl px-4 py-3 text-sm text-muted">
            <span className="font-bold uppercase tracking-[0.12em] text-[11px] text-heading">
              How you opened this
            </span>
            <pre className="mt-2 overflow-x-auto font-mono text-xs text-code">{`python scripts/export_frontend_data.py
cd frontend && npm install && npx vite`}</pre>
            <p className="mt-2 text-xs">
              Stop with Ctrl+C. Re-export after new runs, then{" "}
              <code className="text-code">npx vite</code> again.
            </p>
          </div>

          <div className="mt-4 glass-soft rounded-2xl px-4 py-3 text-sm text-muted">
            <span className="font-bold uppercase tracking-[0.12em] text-[11px] text-heading">
              Order
            </span>
            <span className="ml-3">
              Env → pack → integrate → <strong className="text-foreground">SMOKE</strong> →
              partial → full → refresh dashboard
            </span>
          </div>
        </div>

        <div className="grid gap-3">
          {STEPS.map((step, i) => {
            const isOpen = open === step.id
            return (
              <Card
                key={step.id}
                className={`anim-rise transition-all duration-300 ${isOpen ? "ring-1 ring-heading/25" : ""}`}
                style={{ animationDelay: `${i * 40}ms` }}
              >
                <button
                  type="button"
                  className="w-full text-left"
                  onClick={() => setOpen(isOpen ? 0 : step.id)}
                  aria-expanded={isOpen}
                >
                  <CardHeader className="flex flex-row items-start gap-4 space-y-0">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-border font-mono text-sm font-bold text-code">
                      {step.id}
                    </span>
                    <div className="min-w-0 flex-1">
                      <CardTitle className="text-lg">{step.title}</CardTitle>
                      <CardDescription className="mt-1">{step.summary}</CardDescription>
                    </div>
                    <span className="shrink-0 text-xs font-bold uppercase tracking-[0.12em] text-muted">
                      {isOpen ? "Hide" : "Show"}
                    </span>
                  </CardHeader>
                </button>
                {isOpen ? (
                  <CardContent className="anim-fade border-t border-border/40 pt-4">
                    {step.detail}
                  </CardContent>
                ) : null}
              </Card>
            )
          })}
        </div>

        <p className="mt-6 text-xs text-muted">
          Full write-up in this clone:{" "}
          <code className="text-code">docs/EVALUATE_YOUR_SOLVER.md</code>
        </p>
      </div>
    </section>
  )
}
