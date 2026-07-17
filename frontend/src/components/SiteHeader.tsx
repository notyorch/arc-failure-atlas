const NAV = [
  { href: "#overview", label: "Overview" },
  { href: "#guide", label: "For Testers" },
  { href: "#pilot", label: "Pilot Run" },
  { href: "#runs", label: "All Runs" },
  { href: "#public", label: "Public Context" },
  { href: "#reports", label: "Reports" },
]

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-border/50 bg-[#060b0f]/55 backdrop-blur-xl">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-6 px-5 py-3.5 md:px-8">
        <a href="#overview" className="group flex items-center gap-3">
          <img
            src="/logo.svg"
            alt="ATLAS"
            className="h-8 w-8 object-contain transition-transform duration-500 group-hover:rotate-6"
          />
          <span className="hidden text-xs font-bold uppercase tracking-[0.22em] text-foreground/80 sm:inline">
            ATLAS
          </span>
        </a>
        <nav className="flex flex-wrap items-center justify-end gap-x-5 gap-y-1 text-sm font-normal text-muted">
          {NAV.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="relative transition-colors hover:text-foreground after:absolute after:-bottom-1 after:left-0 after:h-px after:w-0 after:bg-heading after:transition-all after:duration-300 hover:after:w-full"
            >
              {item.label}
            </a>
          ))}
        </nav>
      </div>
    </header>
  )
}
