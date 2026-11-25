import { Search, X } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { cn } from "@/lib/cn";

export function SearchBar({ variant = "compact", autoFocus = false }: { variant?: "hero" | "compact"; autoFocus?: boolean }) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [value, setValue] = useState(params.get("q") ?? "");

  // Keep the input in sync when the URL changes (back/forward, chip clicks).
  useEffect(() => setValue(params.get("q") ?? ""), [params]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const q = value.trim();
    if (!q) return;
    navigate(`/search?q=${encodeURIComponent(q)}`);
  }

  const hero = variant === "hero";
  return (
    <form
      role="search"
      onSubmit={submit}
      className={cn(
        "group relative flex w-full items-center bg-white transition",
        hero
          ? "rounded-2xl p-2 shadow-[0_18px_50px_-20px_rgb(31_30_28_/_0.3)] ring-1 ring-ink-200 transition-shadow focus-within:shadow-[0_22px_60px_-18px_rgb(31_30_28_/_0.35)] focus-within:ring-4 focus-within:ring-brand-300/50"
          : "rounded-xl border border-ink-200 focus-within:border-brand-400 focus-within:ring-4 focus-within:ring-brand-300/30",
      )}
    >
      <Search className={cn("pointer-events-none shrink-0 text-ink-400", hero ? "ml-3 size-6" : "ml-3 size-4.5")} />
      <input
        type="search"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        autoFocus={autoFocus}
        placeholder={hero ? "Search iPhone 15, Nike sneakers, Levi's jeans…" : "Search products…"}
        aria-label="Search products"
        className={cn(
          "min-w-0 flex-1 bg-transparent text-ink-900 placeholder:text-ink-400 focus:outline-none [&::-webkit-search-cancel-button]:hidden",
          hero ? "px-3 py-3 text-base sm:text-lg" : "px-2.5 py-2 text-sm",
        )}
      />
      {value && (
        <button
          type="button"
          onClick={() => setValue("")}
          className="mr-1 rounded-md p-1 text-ink-400 hover:bg-ink-100 hover:text-ink-700"
          aria-label="Clear search"
        >
          <X className="size-4" />
        </button>
      )}
      {hero ? (
        <button
          type="submit"
          className="btn-shine bg-gradient-brand inline-flex h-12 items-center gap-2 rounded-xl px-5 font-semibold text-brand-50 shadow-glow transition hover:-translate-y-px active:scale-[0.98] sm:px-7"
        >
          <Search className="size-4.5 sm:hidden" />
          <span className="hidden sm:inline">Compare prices</span>
        </button>
      ) : (
        <button type="submit" className="sr-only">
          Search
        </button>
      )}
    </form>
  );
}
