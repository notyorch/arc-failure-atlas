import { useEffect, useState } from "react"
import { ArtifactsSection } from "@/components/ArtifactsSection"
import { ComparisonSection } from "@/components/ComparisonSection"
import { FailureSection } from "@/components/FailureSection"
import { GuideSection } from "@/components/GuideSection"
import { Hero } from "@/components/HeroSection"
import { MetricsSection } from "@/components/MetricsSection"
import { RunsSection } from "@/components/RunsSection"
import { SiteHeader } from "@/components/SiteHeader"
import { Separator } from "@/components/ui/separator"
import type { OverviewData } from "@/lib/types"

export default function App() {
  const [data, setData] = useState<OverviewData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch("/data/overview.json")
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`Failed to load overview.json (${res.status})`)
        }
        return (await res.json()) as OverviewData
      })
      .then((json) => {
        if (!cancelled) setData(json)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load overview data")
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="min-h-screen">
      <SiteHeader />
      <main>
        {error ? (
          <div className="mx-auto max-w-6xl px-5 py-20 md:px-8">
            <div className="glass-panel rounded-[1.4rem] px-6 py-10 md:px-10">
              <h1 className="font-sans text-3xl font-bold text-heading">Data unavailable</h1>
              <p className="mt-3 text-muted">{error}</p>
              <p className="mt-2 text-sm text-muted">
                Run <code className="text-code">python scripts/export_frontend_data.py</code>{" "}
                then restart the Vite dev server.
              </p>
            </div>
          </div>
        ) : !data ? (
          <div className="mx-auto max-w-6xl px-5 py-20 text-muted md:px-8">
            Loading observatory overview…
          </div>
        ) : (
          <>
            <Hero project={data.project} />
            <GuideSection />
            <MetricsSection pilot={data.pilot} />
            <RunsSection runs={data.runs ?? []} />
            <ComparisonSection
              pilot={data.pilot}
              publicContext={data.public_context}
            />
            <FailureSection pilot={data.pilot} />
            <ArtifactsSection artifacts={data.artifacts} />
            <Separator className="mx-auto max-w-6xl bg-border/50" />
            <footer className="mx-auto max-w-6xl px-5 py-8 text-xs font-normal text-muted md:px-8">
              ATLAS · overview generated {new Date(data.generated_at).toUTCString()}. Metrics come
              from local evaluation / public-results Parquet — not invented for the UI.
            </footer>
          </>
        )}
      </main>
    </div>
  )
}
