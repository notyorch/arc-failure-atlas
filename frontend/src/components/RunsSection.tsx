import { useState } from "react"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { msToSec, pct } from "@/lib/format"
import type { RunRow } from "@/lib/types"

const DEFAULT_VISIBLE = 5

function shortId(runId: string): string {
  const parts = runId.split("_")
  return parts.length >= 2 ? parts.slice(1).join("_") : runId
}

export function RunsSection({ runs }: { runs: RunRow[] }) {
  const [expanded, setExpanded] = useState(false)

  if (!runs || runs.length === 0) {
    return null
  }

  const hasMore = runs.length > DEFAULT_VISIBLE
  const visibleRuns = expanded ? runs : runs.slice(0, DEFAULT_VISIBLE)

  return (
    <section id="runs" className="scroll-mt-20 section-rule border-b">
      <div className="mx-auto max-w-6xl px-5 py-14 md:px-8">
        <div className="mb-8 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="font-sans text-3xl font-bold tracking-tight text-heading">
              All evaluation runs
            </h2>
            <p className="mt-3 max-w-2xl text-sm font-normal text-muted">
              Every local judge run on disk, newest first. All rows are{" "}
              <code className="text-code">local_pilot_partial</code>. Split
              failure modes carefully: <strong>parse_error</strong> = unreadable
              grid; <strong>execution_error</strong> on a submission run often
              means a coverage gap (task not in the artifact), not a crashed
              solver — scope with <code className="text-code">--task-id</code>.
            </p>
          </div>
          <Badge variant="accent">
            {expanded || !hasMore ? `${runs.length} runs` : `${DEFAULT_VISIBLE} of ${runs.length}`}
          </Badge>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Run ledger</CardTitle>
            <CardDescription>
              <code className="text-code">task_solved_rate</code> is ARC-official.
              <code className="text-code"> parse_error</code> ≠ wrong answer.
              <code className="text-code"> execution_error</code> on submissions
              is often a coverage gap (use <code className="text-code">--task-id</code>).
            </CardDescription>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full min-w-[960px] text-left text-sm">
              <thead className="border-b border-border text-[11px] font-bold uppercase tracking-[0.12em] text-muted">
                <tr>
                  <th className="py-2 pr-3">Model</th>
                  <th className="py-2 pr-3">Benchmark</th>
                  <th className="py-2 pr-3 text-right">Tasks</th>
                  <th className="py-2 pr-3 text-right">Task solved</th>
                  <th className="py-2 pr-3 text-right">Solved (items)</th>
                  <th className="py-2 pr-3 text-right">Parse error</th>
                  <th className="py-2 pr-3 text-right">Exec error</th>
                  <th className="py-2 pr-3 text-right">Latency</th>
                  <th className="py-2">Run id</th>
                </tr>
              </thead>
              <tbody>
                {visibleRuns.map((r) => (
                  <tr key={r.run_id} className="border-b border-border/40 align-top">
                    <td className="py-3 pr-3 font-normal text-foreground">
                      {r.model_name ?? r.solver_name ?? "—"}
                      {r.prompt_version ? (
                        <div className="text-[11px] font-normal text-muted">
                          {r.prompt_version}
                        </div>
                      ) : null}
                    </td>
                    <td className="py-3 pr-3 text-muted">{r.benchmark_name ?? r.pack_id ?? "—"}</td>
                    <td className="py-3 pr-3 text-right font-mono text-code">
                      {r.n_task_count ?? r.n_tasks}
                    </td>
                    <td className="py-3 pr-3 text-right font-mono font-bold text-code">
                      {pct(r.task_solved_rate)}
                    </td>
                    <td className="py-3 pr-3 text-right font-mono text-code">
                      {pct(r.solved_rate)}
                    </td>
                    <td className="py-3 pr-3 text-right font-mono text-code">
                      {pct(r.parse_error_rate)}
                    </td>
                    <td className="py-3 pr-3 text-right font-mono text-code">
                      {pct(r.execution_error_rate)}
                    </td>
                    <td className="py-3 pr-3 text-right font-mono text-code">
                      {msToSec(r.avg_latency_ms)}
                    </td>
                    <td className="py-3 font-mono text-[11px] text-code">{shortId(r.run_id)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {hasMore ? (
              <div className="mt-4 flex justify-center">
                <button
                  type="button"
                  onClick={() => setExpanded((v) => !v)}
                  className="glass-soft rounded-full px-5 py-2 text-xs font-bold uppercase tracking-[0.12em] text-foreground transition-colors hover:text-heading"
                >
                  {expanded
                    ? "Show fewer"
                    : `Show all ${runs.length} runs`}
                </button>
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </section>
  )
}
