import type { OverviewData } from "@/lib/types"

export function Hero({ project }: { project: OverviewData["project"] }) {
  return (
    <section id="overview" className="scroll-mt-20 section-rule border-b relative overflow-hidden">
      <div className="pointer-events-none absolute inset-0 anim-aurora opacity-60" aria-hidden />
      <div className="relative mx-auto max-w-6xl px-5 py-20 md:px-8 md:py-28">
        <div className="glass-panel anim-rise mx-auto max-w-4xl rounded-[1.6rem] px-6 py-12 md:px-12 md:py-16">
          <div className="mb-8 flex items-center justify-center gap-3 md:justify-start">
            <img
              src="/logo.svg"
              alt="ATLAS logo"
              className="h-12 w-12 object-contain anim-float md:h-14 md:w-14"
            />
            <span className="font-display text-2xl font-semibold tracking-[0.12em] text-heading md:text-3xl">
              ATLAS
            </span>
          </div>
          <p className="mb-4 text-xs font-bold uppercase tracking-[0.28em] text-muted">
            {project.name}
          </p>
          <h1 className="font-display max-w-3xl text-4xl font-semibold leading-[1.08] text-heading md:text-6xl">
            See why solvers fail — not just that they fail
          </h1>
          <p className="mt-7 max-w-2xl text-base font-normal leading-relaxed text-foreground/90 md:text-lg">
            {project.mission}
          </p>
          <p className="mt-4 max-w-2xl text-sm font-normal text-muted md:text-base">
            {project.tagline}
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <a
              href="#guide"
              className="glass-soft rounded-full px-5 py-2.5 text-xs font-bold uppercase tracking-[0.14em] text-foreground transition-all duration-300 hover:scale-[1.03] hover:text-heading"
            >
              Evaluate your solver →
            </a>
            <a
              href="#pilot"
              className="rounded-full px-5 py-2.5 text-xs font-bold uppercase tracking-[0.14em] text-muted transition-colors hover:text-foreground"
            >
              View pilot
            </a>
          </div>
        </div>
      </div>
    </section>
  )
}
