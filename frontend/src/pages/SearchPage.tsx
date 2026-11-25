import { ChevronLeft, ChevronRight, SearchX, SlidersHorizontal, X } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";

import type { Category, SortOption } from "@/api";
import { ProductCard, ProductCardSkeleton } from "@/components/product/ProductCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { Reveal } from "@/components/ui/Reveal";
import { Button } from "@/components/ui/Button";
import { useCategories, useSearch } from "@/hooks/queries";
import { cn } from "@/lib/cn";
import { rupeesToPaise } from "@/lib/format";

const SORTS: { value: SortOption; label: string }[] = [
  { value: "relevance", label: "Most relevant" },
  { value: "price_asc", label: "Price: low to high" },
  { value: "price_desc", label: "Price: high to low" },
  { value: "discount", label: "Biggest discount" },
  { value: "rating", label: "Top rated" },
];

const PRICE_PRESETS: { label: string; min?: number; max?: number }[] = [
  { label: "Under ₹2,000", max: 2000 },
  { label: "₹2,000 – ₹10,000", min: 2000, max: 10000 },
  { label: "₹10,000 – ₹40,000", min: 10000, max: 40000 },
  { label: "Above ₹40,000", min: 40000 },
];

const num = (v: string | null) => (v && !Number.isNaN(Number(v)) ? Number(v) : undefined);

export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const [filtersOpen, setFiltersOpen] = useState(false);

  const q = params.get("q") ?? "";
  const category = params.get("category") ?? undefined;
  const sort = (params.get("sort") as SortOption | null) ?? "relevance";
  const page = num(params.get("page")) ?? 1;
  // URL holds rupees (readable); API takes paise.
  const minRupees = num(params.get("min_price"));
  const maxRupees = num(params.get("max_price"));

  const { data, isLoading, isFetching, isError, refetch } = useSearch({
    q,
    category,
    sort,
    page,
    min_price: minRupees != null ? rupeesToPaise(minRupees) : undefined,
    max_price: maxRupees != null ? rupeesToPaise(maxRupees) : undefined,
  });
  const { data: categories } = useCategories();

  function update(patch: Record<string, string | number | undefined>) {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined || v === "") next.delete(k);
      else next.set(k, String(v));
    }
    if (!("page" in patch)) next.delete("page");
    setParams(next);
  }

  const activeCategory = categories?.find((c) => c.slug === category);
  const hasFilters = !!category || minRupees != null || maxRupees != null;

  return (
    <div className="mx-auto max-w-7xl px-4 pt-8 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-ink-500">
            {data ? `${data.total} product${data.total === 1 ? "" : "s"}` : "Searching…"}
            {activeCategory && <> in {activeCategory.name}</>}
          </p>
          <h1 className="mt-1 font-display text-3xl font-bold tracking-tight">
            {q ? (
              <>
                Results for <span className="text-brand-600">“{q}”</span>
              </>
            ) : (
              (activeCategory?.name ?? "All deals")
            )}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" className="lg:hidden" onClick={() => setFiltersOpen((o) => !o)}>
            <SlidersHorizontal className="size-4" /> Filters
          </Button>
          <label className="flex items-center gap-2 text-sm text-ink-500">
            <span className="hidden sm:inline">Sort by</span>
            <select
              value={sort}
              onChange={(e) => update({ sort: e.target.value === "relevance" ? undefined : e.target.value })}
              className="h-9 rounded-xl border border-ink-200 bg-white px-3 text-sm font-semibold text-ink-800 focus:border-brand-400 focus:outline-none"
            >
              {SORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {hasFilters && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {activeCategory && <Chip onRemove={() => update({ category: undefined })}>{activeCategory.name}</Chip>}
          {(minRupees != null || maxRupees != null) && (
            <Chip onRemove={() => update({ min_price: undefined, max_price: undefined })}>
              {minRupees != null ? `₹${minRupees.toLocaleString("en-IN")}` : "₹0"} –{" "}
              {maxRupees != null ? `₹${maxRupees.toLocaleString("en-IN")}` : "any"}
            </Chip>
          )}
          <button
            onClick={() => update({ category: undefined, min_price: undefined, max_price: undefined })}
            className="text-sm font-semibold text-ink-500 hover:text-brand-600"
          >
            Clear all
          </button>
        </div>
      )}

      <div className="mt-6 grid gap-8 lg:grid-cols-[240px_1fr]">
        <aside className={cn("space-y-6 lg:block", filtersOpen ? "block" : "hidden")}>
          <Filters
            key={`${minRupees}-${maxRupees}`}
            categories={categories ?? []}
            category={category}
            min={minRupees}
            max={maxRupees}
            onCategory={(slug) => update({ category: slug })}
            onPrice={(min, max) => update({ min_price: min, max_price: max })}
          />
        </aside>

        <div>
          {isError ? (
            <EmptyState
              icon={SearchX}
              title="We couldn't load results"
              body="One of our services didn't respond. Please try again in a moment."
              action={<Button onClick={() => refetch()}>Try again</Button>}
            />
          ) : isLoading || !data ? (
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 6 }, (_, i) => (
                <ProductCardSkeleton key={i} />
              ))}
            </div>
          ) : data.items.length === 0 ? (
            <EmptyState
              icon={SearchX}
              title="No matching products"
              body={
                <>
                  Try a shorter search, check the spelling, or remove a filter.
                  {hasFilters && " Your filters may be hiding results."}
                </>
              }
              action={
                <div className="flex flex-wrap justify-center gap-2">
                  {["iPhone", "headphones", "sneakers", "backpack"].map((s) => (
                    <Link
                      key={s}
                      to={`/search?q=${s}`}
                      className="rounded-full border border-ink-200 px-3 py-1 text-sm font-medium text-ink-600 hover:border-brand-300 hover:text-brand-700"
                    >
                      {s}
                    </Link>
                  ))}
                </div>
              }
            />
          ) : (
            <>
              <div className={cn("grid grid-cols-1 gap-5 transition-opacity sm:grid-cols-2 xl:grid-cols-3", isFetching && "opacity-60")}>
                {data.items.map((p, i) => (
                  <Reveal key={p.id} delay={(i % 3) * 80}>
                    <ProductCard product={p} />
                  </Reveal>
                ))}
              </div>
              {data.pages > 1 && (
                <nav className="mt-10 flex items-center justify-center gap-2" aria-label="Pagination">
                  <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => update({ page: page - 1 })}>
                    <ChevronLeft className="size-4" /> Prev
                  </Button>
                  <span className="px-3 text-sm text-ink-500">
                    Page <span className="font-semibold text-ink-900">{data.page}</span> of {data.pages}
                  </span>
                  <Button variant="secondary" size="sm" disabled={page >= data.pages} onClick={() => update({ page: page + 1 })}>
                    Next <ChevronRight className="size-4" />
                  </Button>
                </nav>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Chip({ children, onRemove }: { children: ReactNode; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-brand-200 bg-brand-50 py-1 pr-1.5 pl-3 text-xs font-semibold text-brand-700">
      {children}
      <button onClick={onRemove} className="rounded-full p-0.5 hover:bg-brand-100" aria-label="Remove filter">
        <X className="size-3.5" />
      </button>
    </span>
  );
}

function Filters({
  categories,
  category,
  min,
  max,
  onCategory,
  onPrice,
}: {
  categories: Category[];
  category?: string;
  min?: number;
  max?: number;
  onCategory: (slug: string | undefined) => void;
  onPrice: (min?: number, max?: number) => void;
}) {
  const [minInput, setMinInput] = useState(min?.toString() ?? "");
  const [maxInput, setMaxInput] = useState(max?.toString() ?? "");
  const roots = categories.filter((c) => !c.parent_id);

  function applyPrice(e: FormEvent) {
    e.preventDefault();
    onPrice(num(minInput), num(maxInput));
  }

  return (
    <>
      <div className="rounded-3xl border border-ink-100 bg-white p-5 shadow-card">
        <h2 className="text-sm font-semibold text-ink-900">Category</h2>
        <ul className="mt-3 space-y-0.5 text-sm">
          <li>
            <CategoryButton active={!category} onClick={() => onCategory(undefined)}>
              All categories
            </CategoryButton>
          </li>
          {roots.map((root) => (
            <li key={root.id}>
              <CategoryButton active={category === root.slug} onClick={() => onCategory(root.slug)} bold>
                {root.name}
              </CategoryButton>
              <ul className="ml-3 border-l border-ink-100 pl-2">
                {categories
                  .filter((c) => c.parent_id === root.id)
                  .map((c) => (
                    <li key={c.id}>
                      <CategoryButton active={category === c.slug} onClick={() => onCategory(c.slug)}>
                        {c.name}
                      </CategoryButton>
                    </li>
                  ))}
              </ul>
            </li>
          ))}
        </ul>
      </div>

      <div className="rounded-3xl border border-ink-100 bg-white p-5 shadow-card">
        <h2 className="text-sm font-semibold text-ink-900">Price</h2>
        <div className="mt-3 space-y-1">
          {PRICE_PRESETS.map((p) => {
            const active = p.min === min && p.max === max;
            return (
              <button
                key={p.label}
                onClick={() => {
                  setMinInput(p.min?.toString() ?? "");
                  setMaxInput(p.max?.toString() ?? "");
                  onPrice(p.min, p.max);
                }}
                className={cn(
                  "block w-full rounded-lg px-2.5 py-1.5 text-left text-sm transition",
                  active ? "bg-brand-50 font-semibold text-brand-700" : "text-ink-600 hover:bg-ink-100",
                )}
              >
                {p.label}
              </button>
            );
          })}
        </div>
        <form onSubmit={applyPrice} className="mt-4 flex items-center gap-2">
          <PriceInput value={minInput} onChange={setMinInput} placeholder="Min" />
          <span className="text-ink-300">–</span>
          <PriceInput value={maxInput} onChange={setMaxInput} placeholder="Max" />
          <Button type="submit" variant="primary" size="sm" className="px-3">
            Go
          </Button>
        </form>
      </div>
    </>
  );
}

function PriceInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <input
      inputMode="numeric"
      value={value}
      onChange={(e) => onChange(e.target.value.replace(/[^\d]/g, ""))}
      placeholder={`₹ ${placeholder}`}
      aria-label={`${placeholder} price in rupees`}
      className="h-9 w-full min-w-0 rounded-lg border border-ink-200 px-2.5 text-sm focus:border-brand-400 focus:outline-none"
    />
  );
}

function CategoryButton({
  active,
  bold,
  onClick,
  children,
}: {
  active: boolean;
  bold?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "block w-full rounded-lg px-2.5 py-1.5 text-left transition",
        active ? "bg-brand-50 font-semibold text-brand-700" : "text-ink-600 hover:bg-ink-100 hover:text-ink-900",
        bold && !active && "font-medium text-ink-800",
      )}
    >
      {children}
    </button>
  );
}
