const NAV = [
  { href: "#overview", label: "Overview" },
  { href: "#pilot", label: "Pilot Run" },
  { href: "#public", label: "Public Context" },
  { href: "#reports", label: "Reports" },
]

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-border/50 bg-[#060b0f]/55 backdrop-blur-xl">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-6 px-5 py-3.5 md:px-8">
        <a href="#overview" className="flex items-center gap-3">
          <img src="/logo.svg" alt="Atlas" className="h-8 w-8 object-contain" />
          <span className="hidden text-xs font-bold uppercase tracking-[0.18em] text-foreground/80 sm:inline">
            Solver Eval
          </span>
        </a>
        <nav className="flex flex-wrap items-center justify-end gap-x-5 gap-y-1 text-sm font-normal text-muted">
          {NAV.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="transition-colors hover:text-foreground"
            >
              {item.label}
            </a>
          ))}
        </nav>
      </div>
    </header>
  )
}
