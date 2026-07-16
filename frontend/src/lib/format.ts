export function pct(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—"
  return `${(value * 100).toFixed(digits)}%`
}

export function num(value: number | null | undefined, digits = 0): string {
  if (value == null || Number.isNaN(value)) return "—"
  return value.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })
}

export function msToSec(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—"
  return `${(value / 1000).toFixed(1)} s`
}

export function trustLabel(tier: string): string {
  const map: Record<string, string> = {
    official_verified: "Official verified",
    competition_verified: "Competition verified",
    self_reported: "Self-reported",
    preview: "Preview",
    partial: "Partial",
    local_pilot: "Local pilot",
  }
  return map[tier] ?? tier.replaceAll("_", " ")
}
