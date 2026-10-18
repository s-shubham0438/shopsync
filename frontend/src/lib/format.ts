const inrWhole = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});
const inrExact = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const compact = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });
const relative = new Intl.RelativeTimeFormat("en-IN", { numeric: "auto" });
const shortDate = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });
const longDate = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" });

/** 5999900 paise → "₹59,999" (Indian digit grouping). */
export function formatPrice(paise: number): string {
  const rupees = paise / 100;
  return (Number.isInteger(rupees) ? inrWhole : inrExact).format(rupees);
}

/** 48210 → "48.2K", 152000 → "1.5L" */
export function formatCount(n: number): string {
  return compact.format(n);
}

export function rupeesToPaise(rupees: number): number {
  return Math.round(rupees * 100);
}

export function percentOff(price: number, mrp: number | null | undefined): number | null {
  if (!mrp || mrp <= price) return null;
  return Math.round((1 - price / mrp) * 100);
}

export function formatRelativeTime(iso: string, from: number = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - from) / 1000);
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31_536_000],
    ["month", 2_592_000],
    ["week", 604_800],
    ["day", 86_400],
    ["hour", 3_600],
    ["minute", 60],
  ];
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return relative.format(Math.round(seconds / size), unit);
  }
  return "just now";
}

export const formatShortDate = (iso: string) => shortDate.format(new Date(iso));
export const formatDate = (iso: string) => longDate.format(new Date(iso));
