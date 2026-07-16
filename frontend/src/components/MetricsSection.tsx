import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { msToSec, num, pct } from "@/lib/format"
import type { PilotSummary } from "@/lib/types"

function Metric({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint?: string
}) {
  return (
    <div className="glass-soft rounded-2xl px-4 py-4">
      <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-muted">
        {label}
      </div>
      <div className="mt-2 font-sans text-2xl font-bold text-foreground">{value}</div>
      {hint ? <div className="mt-1 text-xs font-normal text-muted">{hint}</div> : null}
    </div>
  )
}

export function MetricsSection({ pilot }: { pilot: PilotSummary | null }) {
  if (!pilot) {
    return (
      <section id="pilot" className="scroll-mt-20 section-rule border-b">
        <div className="mx-auto max-w-6xl px-5 py-14 md:px-8">
          <Card>
            <CardHeader>
              <CardTitle>Pilot run</CardTitle>
              <CardDescription>
                No local pilot artifact found. Export data after a completed evaluation run.
              </CardDescription>
            </CardHeader>
          </Card>
        </div>
      </section>
    )
  }

  return (
    <section id="pilot" className="scroll-mt-20 section-rule border-b">
      <div className="mx-auto max-w-6xl px-5 py-14 md:px-8">
        <div className="mb-8 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="font-sans text-3xl font-bold tracking-tight text-heading">
              Pilot run
            </h2>
            <p className="mt-3 max-w-2xl text-sm font-normal text-muted">
              Local pilot on a partial task set. Scope is{" "}
              <code className="text-code">{pilot.comparison_scope}</code>, not a
              full public leaderboard claim.
            </p>
          </div>
          <Badge variant="warning">Partial · n={pilot.n_tasks}</Badge>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>{pilot.solver_name ?? "Unknown solver"}</CardTitle>
            <CardDescription className="font-mono text-xs text-code">
              {pilot.model_name ?? "—"} · {pilot.run_id}
              {pilot.benchmark_name ? ` · ${pilot.benchmark_name}` : ""}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <Metric label="Solved rate" value={pct(pilot.solved_rate)} hint="item-level pass@k" />
              <Metric
                label="Cell accuracy"
                value={pct(pilot.avg_cell_accuracy)}
                hint="valid predictions"
              />
              <Metric label="Avg latency" value={msToSec(pilot.avg_latency_ms)} hint="per item" />
              <Metric
                label="Tokens"
                value={`${num(pilot.tokens_in)} / ${num(pilot.tokens_out)}`}
                hint="in / out"
              />
              <Metric
                label="Dominant failure"
                value={pilot.dominant_failure_mode?.replaceAll("_", " ") ?? "—"}
              />
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  )
}
