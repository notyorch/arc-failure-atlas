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

const OFFICIAL_LINKS = {
  "ARC-AGI-1": {
    page: "https://arcprize.org/arc-agi/1",
    leaderboard: "https://arcprize.org/leaderboard",
  },
  "ARC-AGI-2": {
    page: "https://arcprize.org/arc-agi/2",
    leaderboard: "https://arcprize.org/leaderboard",
  },
} as const

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
          className="h-full rounded-full bg-white transition-[width] duration-700 ease-out"
          style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
        />
      </div>
      <div className="text-[11px] font-normal text-muted">{meta}</div>
    </div>
  )
}

function isAgi1(name: string): boolean {
  const n = name.toLowerCase()
  return n.includes("agi-1") || n.includes("agi1") || n === "arc-agi"
}

function isAgi2(name: string): boolean {
  const n = name.toLowerCase()
  return n.includes("agi-2") || n.includes("agi2")
}

function BenchmarkTable({
  title,
  officialPage,
  officialLeaderboard,
  rows,
  defaultOpen = false,
}: {
  title: string
  officialPage: string
  officialLeaderboard: string
  rows: PublicRow[]
  defaultOpen?: boolean
}) {
  return (
    <details className="group glass-panel anim-rise rounded-[var(--radius-glass)]" open={defaultOpen}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 p-6 [&::-webkit-details-marker]:hidden">
        <div>
          <h3 className="font-sans text-lg font-bold tracking-tight text-heading">{title}</h3>
          <p className="mt-1 text-sm font-normal text-muted">
            {rows.length} curated rows · observatory context only
          </p>
        </div>
        <span className="shrink-0 text-xs font-bold uppercase tracking-[0.12em] text-muted">
          <span className="group-open:hidden">Show table ↓</span>
          <span className="hidden group-open:inline">Hide table ↑</span>
        </span>
      </summary>

      <div className="anim-fade border-t border-border/40">
        <div className="flex flex-wrap items-center justify-between gap-3 px-6 pt-5">
          <CardDescription>
            Published ARC Prize context — not your local judge scores.
          </CardDescription>
          <div className="flex flex-wrap gap-2">
            <a
              href={officialPage}
              target="_blank"
              rel="noreferrer"
              className="glass-soft rounded-full px-3 py-1.5 text-[11px] font-bold uppercase tracking-[0.12em] text-foreground transition-all hover:scale-[1.03] hover:text-heading"
            >
              Benchmark →
            </a>
            <a
              href={officialLeaderboard}
              target="_blank"
              rel="noreferrer"
              className="rounded-full border border-border px-3 py-1.5 text-[11px] font-bold uppercase tracking-[0.12em] text-muted transition-colors hover:text-foreground"
            >
              Official scores →
            </a>
          </div>
        </div>
      <CardContent className="pt-4">
        {rows.length === 0 ? (
          <p className="text-sm text-muted">No curated rows for this benchmark yet.</p>
        ) : (
          <table className="w-full table-fixed text-left text-sm">
            <thead className="border-b border-border text-[11px] font-bold uppercase tracking-[0.12em] text-muted">
              <tr>
                <th className="w-[38%] py-2 pr-3">Submission</th>
                <th className="w-[14%] py-2 pr-3">Score</th>
                <th className="w-[23%] py-2 pr-3">Trust</th>
                <th className="w-[25%] py-2">Scope</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r: PublicRow) => (
                <tr
                  key={`${r.submission_name}-${r.benchmark_name}-${r.split_type}`}
                  className="border-b border-border/40 transition-colors hover:bg-white/[0.03]"
                >
                  <td className="break-words py-3 pr-3 font-normal text-foreground">
                    {r.submission_name}
                  </td>
                  <td className="py-3 pr-3 font-mono font-bold text-code">
                    {r.score_percent != null ? `${r.score_percent.toFixed(1)}%` : "—"}
                  </td>
                  <td className="py-3 pr-3">
                    <Badge variant={trustVariant(r.trust_tier)}>
                      {trustLabel(r.trust_tier)}
                    </Badge>
                  </td>
                  <td className="break-words py-3 font-mono text-xs text-code">
                    {r.comparison_scope}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
      </div>
    </details>
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
  const publicRows = rows.filter((r) => r.trust_tier !== "local_pilot")

  const agi1Rows = publicRows.filter((r) => isAgi1(r.benchmark_name))
  const agi2Rows = publicRows.filter((r) => isAgi2(r.benchmark_name))

  const chartRows: Array<{
    label: string
    percent: number
    meta: string
  }> = []

  if (pilot?.solved_rate != null) {
    chartRows.push({
      label: pilot.solver_name ?? "Local pilot",
      percent: pilot.solved_rate * 100,
      meta: `local pilot · ${pilot.n_tasks} tasks · ${pilot.comparison_scope}`,
    })
  } else if (localRows[0]?.score_percent != null) {
    const r = localRows[0]
    chartRows.push({
      label: r.submission_name,
      percent: r.score_percent as number,
      meta: `${trustLabel(r.trust_tier)} · ${r.benchmark_name}`,
    })
  }

  for (const r of publicRows.slice(0, 8)) {
    if (r.score_percent == null) continue
    chartRows.push({
      label: r.submission_name,
      percent: r.score_percent,
      meta: `${trustLabel(r.trust_tier)} · ${r.benchmark_name} · ${r.comparison_scope}`,
    })
  }

  return (
    <section id="public" className="scroll-mt-20 section-rule border-b">
      <div className="mx-auto max-w-6xl px-5 py-14 md:px-8">
        <div className="mb-8 anim-rise">
          <h2 className="font-sans text-3xl font-bold tracking-tight text-heading">
            Public benchmark context
          </h2>
          <p className="mt-3 max-w-2xl text-sm font-normal text-muted">
            Structured observatory rows with trust tiers. Local pilot is an anchor — not a
            controlled bake-off against full ARC Prize scores. Official published scores live
            on{" "}
            <a
              href="https://arcprize.org/leaderboard"
              target="_blank"
              rel="noreferrer"
              className="text-heading underline-offset-2 hover:underline"
            >
              arcprize.org/leaderboard
            </a>
            .
          </p>
        </div>

        <div className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
          <Card className="anim-rise">
            <CardHeader>
              <CardTitle>Score context</CardTitle>
              <CardDescription>
                Local pilot vs curated public / competition rows
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {chartRows.map((row) => (
                <ScoreBar key={`${row.label}-${row.meta}`} {...row} />
              ))}
            </CardContent>
          </Card>

          <Card className="anim-rise" style={{ animationDelay: "60ms" }}>
            <CardHeader>
              <CardTitle>Trust tiers</CardTitle>
              <CardDescription>How public rows are labeled in the observatory</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {(publicContext.by_trust ?? []).map((t) => (
                <div
                  key={t.trust_tier}
                  className="glass-soft flex items-center justify-between gap-3 rounded-2xl px-3 py-3 transition-transform duration-300 hover:scale-[1.01]"
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

        <div className="mt-5 space-y-4">
          <BenchmarkTable
            title="ARC-AGI-1"
            officialPage={OFFICIAL_LINKS["ARC-AGI-1"].page}
            officialLeaderboard={OFFICIAL_LINKS["ARC-AGI-1"].leaderboard}
            rows={agi1Rows}
            defaultOpen
          />
          <BenchmarkTable
            title="ARC-AGI-2"
            officialPage={OFFICIAL_LINKS["ARC-AGI-2"].page}
            officialLeaderboard={OFFICIAL_LINKS["ARC-AGI-2"].leaderboard}
            rows={agi2Rows}
          />
        </div>
      </div>
    </section>
  )
}
