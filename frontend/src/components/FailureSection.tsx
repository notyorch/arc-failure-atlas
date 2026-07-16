import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { PilotSummary } from "@/lib/types"

export function FailureSection({ pilot }: { pilot: PilotSummary | null }) {
  const modes = pilot?.failure_modes ?? []
  const max = Math.max(1, ...modes.map((m) => m.count))

  return (
    <section className="section-rule border-b">
      <div className="mx-auto max-w-6xl px-5 py-14 md:px-8">
        <div className="mb-8">
          <h2 className="font-sans text-3xl font-bold tracking-tight text-heading">
            Failure taxonomy
          </h2>
          <p className="mt-3 max-w-2xl text-sm font-normal text-muted">
            Deterministic labels from the evaluation pipeline (v2). Counts are attempt rows
            from the local pilot.
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Top failure modes</CardTitle>
            <CardDescription>
              {pilot
                ? `${pilot.n_attempts} attempt rows · dominant: ${pilot.dominant_failure_mode ?? "—"}`
                : "No pilot failure data available"}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {modes.length === 0 ? (
              <p className="text-sm font-normal text-muted">No failure-mode rows to display.</p>
            ) : (
              modes.map((m) => (
                <div
                  key={m.mode}
                  className="grid grid-cols-[9rem_1fr_2.5rem] items-center gap-3"
                >
                  <div className="truncate font-mono text-xs text-code">{m.mode}</div>
                  <div className="h-2.5 overflow-hidden rounded-full bg-white/10">
                    <div
                      className="h-full rounded-full bg-white"
                      style={{ width: `${(m.count / max) * 100}%` }}
                    />
                  </div>
                  <div className="text-right font-mono text-xs font-bold text-code">
                    {m.count}
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </section>
  )
}
