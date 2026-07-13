export function number(value: number | null | undefined, digits = 2): string {
  return value == null || Number.isNaN(value) ? "—" : new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(value);
}

export function percent(value: number | null | undefined): string {
  return value == null ? "—" : `${number(value * 100, 1)}%`;
}

export function money(value: number | null | undefined): string {
  return value == null ? "—" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 4 }).format(value);
}

export function duration(value: number | null | undefined): string {
  if (value == null) return "—";
  return value < 1000 ? `${number(value, 0)} ms` : `${number(value / 1000, 1)} s`;
}

export function shortHash(value: string | null | undefined): string {
  return value ? value.replace("sha256:", "").slice(0, 10) : "—";
}
