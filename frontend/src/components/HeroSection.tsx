import type { OverviewData } from "@/lib/types"

export function Hero({ project }: { project: OverviewData["project"] }) {
  return (
    <section id="overview" className="scroll-mt-20 section-rule border-b">
      <div className="mx-auto max-w-6xl px-5 py-20 md:px-8 md:py-28">
        <div className="glass-panel mx-auto max-w-4xl rounded-[1.6rem] px-6 py-12 md:px-12 md:py-16">
          <div className="mb-8 flex justify-center md:justify-start">
            <img
              src="/logo.svg"
              alt="Atlas logo"
              className="h-16 w-16 object-contain md:h-20 md:w-20"
            />
          </div>
          <p className="mb-4 text-xs font-bold uppercase tracking-[0.22em] text-muted">
            Research observability
          </p>
          <h1 className="font-display max-w-3xl text-4xl font-semibold leading-[1.1] text-heading md:text-6xl">
            {project.name}
          </h1>
          <p className="mt-7 max-w-2xl text-base font-normal leading-relaxed text-foreground/90 md:text-lg">
            {project.mission}
          </p>
          <p className="mt-4 max-w-2xl text-sm font-normal text-muted md:text-base">
            {project.tagline}
          </p>
        </div>
      </div>
    </section>
  )
}
