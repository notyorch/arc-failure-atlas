import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { pct, trustLabel } from "@/lib/format"
import type { OverviewData, PilotSummary, PublicRow } from "@/lib/types"

function trustVariant(
  tier: string,
): "accent" | "success" | "warning" | "muted" | "danger" {
  if (tier === "official_verified" || tier === "competition_verified") return "success"
  if (tier === "local_pilot") return "accent"
  if (tier === "self_reported") return "warning"
  if (tier === "preview" || tier === "partial") return "muted"
  return "muted"
}

function ScoreBar({
  label,
  percent,
  meta,
}: {
  label: string
  percent: number
  tone?: "local" | "public" | "self"
  meta: string
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <div className="truncate text-sm font-normal text-foreground">{label}</div>
        <div className="shrink-0 font-mono text-xs text-code">{percent.toFixed(1)}%</div>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-white/10">
        <div
          className="h-full rounded-full bg-white"
          style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
        />
      </div>
      <div className="text-[11px] font-normal text-muted">{meta}</div>
    </div>
  )
}

export function ComparisonSection({
  pilot,
  publicContext,
}: {
  pilot: PilotSummary | null
  publicContext: OverviewData["public_context"]
}) {
  if (!publicContext.available) {
    return (
      <section id="public" className="scroll-mt-20 section-rule border-b">
        <div className="mx-auto max-w-6xl px-5 py-14 md:px-8">
          <Card>
            <CardHeader>
              <CardTitle>Public context</CardTitle>
              <CardDescription>
                {publicContext.message ??
                  "Public results Parquet not found. Run the observatory compare CLI first."}
              </CardDescription>
            </CardHeader>
          </Card>
        </div>
      </section>
    )
  }

  const rows = publicContext.rows ?? []
  const localRows = rows.filter((r) => r.trust_tier === "local_pilot")
  const publicRows = rows
    .filter((r) => r.trust_tier !== "local_pilot")
    .slice(0, 8)

  const chartRows: Array<{
    label: string
    percent: number
    tone: "local" | "public" | "self"
    meta: string
  }> = []

  if (pilot?.solved_rate != null) {
    chartRows.push({
      label: pilot.solver_name ?? "Local pilot",
      percent: pilot.solved_rate * 100,
      tone: "local",
      meta: `local pilot · ${pilot.n_tasks} tasks · ${pilot.comparison_scope}`,
    })
  } else if (localRows[0]?.score_percent != null) {
    const r = localRows[0]
    const localPct = r.score_percent as number
    chartRows.push({
      label: r.submission_name,
      percent: localPct,
      tone: "local",
      meta: `${trustLabel(r.trust_tier)} · ${r.benchmark_name}`,
    })
  }

  for (const r of publicRows) {
    if (r.score_percent == null) continue
    const pctValue = r.score_percent
    chartRows.push({
      label: r.submission_name,
      percent: pctValue,
      tone: r.trust_tier === "self_reported" ? "self" : "public",
      meta: `${trustLabel(r.trust_tier)} · ${r.benchmark_name} · ${r.comparison_scope}`,
    })
  }

  return (
    <section id="public" className="scroll-mt-20 section-rule border-b">
      <div className="mx-auto max-w-6xl px-5 py-14 md:px-8">
        <div className="mb-8">
          <h2 className="font-sans text-3xl font-bold tracking-tight text-heading">
            Public benchmark context
          </h2>
          <p className="mt-3 max-w-2xl text-sm font-normal text-muted">
            Structured observatory rows with trust tiers. Local pilot is an anchor — not a
            controlled bake-off against full ARC-AGI / ARC Prize scores.
          </p>
        </div>

        <div className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
          <Card>
            <CardHeader>
              <CardTitle>Score context</CardTitle>
              <CardDescription>
                Orange = local pilot · Blue = verified/competition · Grey = self-reported
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {chartRows.map((row) => (
                <ScoreBar key={`${row.label}-${row.meta}`} {...row} />
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Trust tiers</CardTitle>
              <CardDescription>How public rows are labeled in the observatory</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {(publicContext.by_trust ?? []).map((t) => (
                <div
                  key={t.trust_tier}
                  className="glass-soft flex items-center justify-between gap-3 rounded-2xl px-3 py-3"
                >
                  <div className="space-y-1">
                    <Badge variant={trustVariant(t.trust_tier)}>
                      {trustLabel(t.trust_tier)}
                    </Badge>
                    <div className="text-xs font-normal text-muted">{t.n} rows</div>
                  </div>
                  <div className="text-right text-sm">
                    <div className="text-muted">max</div>
                    <div className="font-mono font-bold text-code">{pct(t.max_score)}</div>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        <Card className="mt-5">
          <CardHeader>
            <CardTitle>Selected public rows</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="border-b border-border text-[11px] font-bold uppercase tracking-[0.12em] text-muted">
                <tr>
                  <th className="py-2 pr-3">Submission</th>
                  <th className="py-2 pr-3">Benchmark</th>
                  <th className="py-2 pr-3">Score</th>
                  <th className="py-2 pr-3">Trust</th>
                  <th className="py-2">Scope</th>
                </tr>
              </thead>
              <tbody>
                {publicRows.map((r: PublicRow) => (
                  <tr
                    key={`${r.submission_name}-${r.benchmark_name}-${r.split_type}`}
                    className="border-b border-border/40"
                  >
                    <td className="py-3 pr-3 font-normal text-foreground">{r.submission_name}</td>
                    <td className="py-3 pr-3 text-muted">{r.benchmark_name}</td>
                    <td className="py-3 pr-3 font-mono font-bold text-code">
                      {r.score_percent != null ? `${r.score_percent.toFixed(1)}%` : "—"}
                    </td>
                    <td className="py-3 pr-3">
                      <Badge variant={trustVariant(r.trust_tier)}>
                        {trustLabel(r.trust_tier)}
                      </Badge>
                    </td>
                    <td className="py-3 font-mono text-xs text-code">{r.comparison_scope}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      </div>
    </section>
  )
}
