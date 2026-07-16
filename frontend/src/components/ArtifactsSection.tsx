import { FileText, FolderOpen, Image, BookOpen } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { ArtifactItem } from "@/lib/types"

const kindIcon = {
  report: FileText,
  parquet: FolderOpen,
  chart: Image,
  docs: BookOpen,
} as const

export function ArtifactsSection({ artifacts }: { artifacts: ArtifactItem[] }) {
  return (
    <section id="reports" className="scroll-mt-20">
      <div className="mx-auto max-w-6xl px-5 py-14 md:px-8">
        <div className="mb-8">
          <h2 className="font-sans text-3xl font-bold tracking-tight text-heading">
            Artifacts & reports
          </h2>
          <p className="mt-3 max-w-2xl text-sm font-normal text-muted">
            Paths relative to the repository root. Open them in your editor or regenerate via
            the Python CLIs.
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          {artifacts.map((item) => {
            const Icon = kindIcon[item.kind as keyof typeof kindIcon] ?? FileText
            return (
              <Card key={item.path} className="transition-colors hover:border-white/25">
                <CardHeader className="flex-row items-start gap-3 space-y-0">
                  <div className="glass-soft mt-0.5 rounded-xl p-2.5 text-foreground">
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <CardTitle className="text-base">{item.label}</CardTitle>
                      <Badge variant={item.exists ? "success" : "danger"}>
                        {item.exists ? "present" : "missing"}
                      </Badge>
                    </div>
                    <CardDescription className="mt-1 break-all font-mono text-xs text-code">
                      {item.path}
                    </CardDescription>
                  </div>
                </CardHeader>
                <CardContent className="pt-0">
                  <span className="text-[11px] font-bold uppercase tracking-[0.14em] text-muted">
                    {item.kind}
                  </span>
                </CardContent>
              </Card>
            )
          })}
        </div>
      </div>
    </section>
  )
}
