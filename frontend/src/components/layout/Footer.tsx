import { Link } from "react-router";

import { USE_MOCKS } from "@/api";

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
          <p className="shrink-0">
            © {new Date().getFullYear()} ShopSync{USE_MOCKS && " · Demo data"}
          </p>
        </div>
      </div>
    </footer>
  );
}
