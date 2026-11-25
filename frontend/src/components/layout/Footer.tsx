import { Link } from "react-router";

import { API_MODE, USE_MOCKS } from "@/api";
import { useHealth } from "@/hooks/queries";

import { Logo } from "./Logo";

const COLUMNS = [
  {
    title: "Shop",
    links: [
      ["Mobiles", "/search?q=phone&category=mobiles"],
      ["Headphones", "/search?q=headphones&category=audio"],
      ["Sneakers", "/search?q=sneakers&category=footwear"],
      ["Backpacks", "/search?q=backpack&category=bags"],
    ],
  },
  {
    title: "Your account",
    links: [
      ["Wishlist", "/wishlist"],
      ["Price alerts", "/alerts"],
      ["Search history", "/history"],
      ["Sign in", "/login"],
    ],
  },
] as const;

const STATUS_STYLE = {
  ok: { dot: "bg-emerald-500", label: "API online" },
  degraded: { dot: "bg-amber-500", label: "API degraded" },
  offline: { dot: "bg-red-500", label: "API offline" },
} as const;

function ApiStatus() {
  const { data, isPending } = useHealth();
  if (API_MODE === "true") return null; // pure demo mode: no backend involved
  if (isPending) return <span className="text-ink-400">Checking API…</span>;
  const state = data?.status ?? "offline";
  const failing = Object.entries(data?.checks ?? {})
    .filter(([, c]) => c.status === "error")
    .map(([name]) => name);
  const title = data?.version
    ? `v${data.version} · ${data.environment}${failing.length ? ` · down: ${failing.join(", ")}` : ""}`
    : "Backend unreachable. Is uvicorn running on :8000?";
  return (
    <span className="inline-flex items-center gap-1.5" title={title} role="status">
      <span className={`h-2 w-2 rounded-full ${STATUS_STYLE[state].dot}`} />
      {STATUS_STYLE[state].label}
      {failing.length > 0 && ` (${failing.join(", ")})`}
    </span>
  );
}

export function Footer() {
  return (
    <footer className="mt-24 border-t border-ink-100 bg-white text-ink-500">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-14 sm:px-6 md:grid-cols-[1.4fr_1fr_1fr]">
        <div>
          <Logo />
          <p className="mt-4 max-w-sm text-sm leading-6 text-ink-500">
            Compare prices, offers and ratings for the same product across India's most trusted stores — and buy
            where it's cheapest.
          </p>
        </div>
        {COLUMNS.map((col) => (
          <div key={col.title}>
            <h3 className="text-sm font-semibold text-ink-900">{col.title}</h3>
            <ul className="mt-4 space-y-2.5 text-sm">
              {col.links.map(([label, to]) => (
                <li key={to}>
                  <Link to={to} className="text-ink-500 transition hover:text-brand-600">
                    {label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-ink-100 bg-surface">
        <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-6 text-xs leading-5 text-ink-400 sm:px-6 md:flex-row md:justify-between">
          <p className="max-w-3xl">
            ShopSync may earn a commission when you buy through links on this site, at no extra cost to you. Prices,
            offers and availability change often — always confirm on the store before buying.
          </p>
          <p className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1">
            <ApiStatus />
            <span>
              © {new Date().getFullYear()} ShopSync{USE_MOCKS && " · Demo data"}
            </span>
          </p>
        </div>
      </div>
    </footer>
  );
}
