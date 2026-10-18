import {
  ArrowUpRight,
  BadgePercent,
  ChevronDown,
  ChevronRight,
  Clock,
  CreditCard,
  Gift,
  PackageX,
  RefreshCw,
  Tag,
  TrendingDown,
  Truck,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { api, ApiError, type Listing, type OfferType, type ProductDetail } from "@/api";
import { PriceHistoryChart } from "@/components/product/PriceHistoryChart";
import { AlertButton, WishlistButton } from "@/components/product/ProductActions";
import { ProductImage } from "@/components/product/ProductImage";
import { Rating } from "@/components/product/Rating";
import { StoreBadge } from "@/components/product/StoreBadge";
import { buttonClasses, ButtonLink } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { usePriceHistory, useProduct } from "@/hooks/queries";
import { cn } from "@/lib/cn";
import { formatPrice, formatRelativeTime } from "@/lib/format";

const OFFER_ICONS: Record<OfferType, LucideIcon> = {
  bank: CreditCard,
  coupon: Tag,
  cashback: Gift,
  exchange: RefreshCw,
  emi: Clock,
};

export function ProductPage() {
  const { id = "" } = useParams();
  const { data: product, isLoading, error } = useProduct(id);
  const [days, setDays] = useState(90);
  const history = usePriceHistory(id, days);

  if (error) {
    const notFound = error instanceof ApiError && error.status === 404;
    return (
      <div className="mx-auto max-w-3xl px-4 py-16">
        <EmptyState
          icon={PackageX}
          title={notFound ? "Product not found" : "Couldn't load this product"}
          body={notFound ? "It may have been removed or the link is wrong." : "Please try again in a moment."}
          action={<ButtonLink to="/">Back to home</ButtonLink>}
        />
      </div>
    );
  }
  if (isLoading || !product) return <ProductSkeleton />;

  const best = product.listings.find((l) => l.is_best_deal) ?? product.listings[0]!;
  const savings = product.highest_price - product.best_price;

  return (
    <div className="mx-auto max-w-7xl px-4 pt-6 sm:px-6">
      <Breadcrumbs product={product} />

      <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-12">
        {/* Left: image + key specs */}
        <div className="lg:sticky lg:top-24 lg:self-start">
          <div className="overflow-hidden rounded-[2rem] border border-ink-100 bg-white shadow-card">
            <ProductImage
              title={product.canonical_title}
              imageUrl={product.image_url}
              category={product.category}
              className="aspect-square"
              iconClassName="size-2/5"
            />
          </div>
          <Specs product={product} />
        </div>

        {/* Right: summary + comparison */}
        <div className="min-w-0 space-y-8">
          <section>
            {product.brand && (
              <p className="text-sm font-semibold tracking-wider text-brand-600 uppercase">{product.brand}</p>
            )}
            <h1 className="mt-2 font-display text-3xl leading-tight font-bold tracking-tight sm:text-4xl">
              {product.canonical_title}
            </h1>
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-ink-500">
              <Rating value={product.rating} count={product.review_count} size="md" />
              <span>Compared across {product.store_count} stores</span>
            </div>

            <div className="relative mt-6 overflow-hidden rounded-3xl border border-brand-100 bg-linear-to-br from-brand-100 via-brand-50 to-white p-6">
              <div className="absolute -top-16 -right-10 size-56 rounded-full bg-brand-200/40 blur-3xl" />
              <div className="relative flex flex-wrap items-end justify-between gap-6">
                <div>
                  <p className="flex items-center gap-2 text-sm text-ink-500">
                    Best price today on
                    <StoreBadge platform={best.platform} size="xs" />
                    <span className="font-semibold text-ink-900">{best.platform.name}</span>
                  </p>
                  <div className="mt-2 flex flex-wrap items-baseline gap-3">
                    <span className="font-display text-5xl font-bold tracking-tight text-ink-900 tabular-nums">
                      {formatPrice(product.best_price)}
                    </span>
                    {best.mrp && best.mrp > best.current_price && (
                      <>
                        <span className="text-lg text-ink-400 line-through tabular-nums">{formatPrice(best.mrp)}</span>
                        <span className="rounded-lg bg-deal-100 px-2 py-0.5 text-sm font-bold text-deal-700">
                          {best.discount_percent}% off
                        </span>
                      </>
                    )}
                  </div>
                  {savings > 0 && (
                    <p className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-deal-700">
                      <TrendingDown className="size-4" />
                      {formatPrice(savings)} cheaper than the highest price ({formatPrice(product.highest_price)})
                    </p>
                  )}
                </div>
                <a
                  href={api.buyUrl(best)}
                  target="_blank"
                  rel="noopener noreferrer sponsored"
                  className={buttonClasses("primary", "lg", "w-full sm:w-auto")}
                >
                  Buy on {best.platform.name} <ArrowUpRight className="size-5" />
                </a>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3">
              <WishlistButton product={product} />
              <AlertButton product={product} />
            </div>
          </section>

          <section>
            <div className="mb-4 flex items-end justify-between">
              <h2 className="font-display text-xl font-semibold">Compare prices</h2>
              <p className="text-xs text-ink-400">Updated {formatRelativeTime(best.last_checked_at)}</p>
            </div>
            <ul className="space-y-3">
              {product.listings.map((l, i) => (
                <ListingRow key={l.id} listing={l} index={i} />
              ))}
            </ul>
          </section>

          <PriceHistoryChart history={history.data} days={days} onDaysChange={setDays} loading={history.isFetching} />
        </div>
      </div>
    </div>
  );
}

function Breadcrumbs({ product }: { product: ProductDetail }) {
  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-sm text-ink-500">
      <Link to="/" className="hover:text-ink-900">
        Home
      </Link>
      {product.category && (
        <>
          <ChevronRight className="size-3.5 text-ink-300" />
          <Link to={`/search?q=&category=${product.category.slug}`} className="hover:text-ink-900">
            {product.category.name}
          </Link>
        </>
      )}
      <ChevronRight className="size-3.5 text-ink-300" />
      <span className="truncate text-ink-700">{product.brand}</span>
    </nav>
  );
}

function ListingRow({ listing: l, index }: { listing: Listing; index: number }) {
  const [showOffers, setShowOffers] = useState(false);
  return (
    <li
      style={{ animationDelay: `${150 + index * 90}ms` }}
      className={cn(
        "relative animate-fade-up rounded-3xl border bg-white p-4 transition duration-300 hover:-translate-y-0.5 hover:shadow-lift sm:p-5",
        l.is_best_deal ? "border-2 border-deal-500 shadow-[0_12px_32px_-12px_rgb(16_185_129_/_0.35)]" : "border-ink-100 shadow-card",
        !l.in_stock && "opacity-70",
      )}
    >
      {l.is_best_deal && (
        <span className="gleam absolute -top-3 left-5 inline-flex items-center gap-1 rounded-full bg-deal-600 px-3 py-1 text-[11px] font-bold tracking-wide text-white uppercase shadow">
          <BadgePercent className="size-3.5" /> Best deal
        </span>
      )}
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex min-w-40 flex-1 items-center gap-3">
          <StoreBadge platform={l.platform} size="md" />
          <div>
            <p className="font-semibold text-ink-900">{l.platform.name}</p>
            <div className="mt-0.5 flex items-center gap-2">
              <Rating value={l.rating} />
              <span className="text-xs text-ink-400">({l.review_count.toLocaleString("en-IN")})</span>
            </div>
          </div>
        </div>

        <div className="hidden min-w-44 flex-1 text-xs text-ink-500 md:block">
          {l.in_stock ? (
            <span className="inline-flex items-center gap-1.5">
              <Truck className="size-4 text-ink-400" /> {l.delivery_info}
            </span>
          ) : (
            <span className="font-semibold text-rose-700">Out of stock</span>
          )}
        </div>

        <div className="text-right">
          <p className={cn("font-display text-2xl font-bold tabular-nums", l.is_best_deal ? "text-deal-700" : "text-ink-900")}>
            {formatPrice(l.current_price)}
          </p>
          {l.mrp && l.mrp > l.current_price && (
            <p className="text-xs text-ink-400">
              <span className="line-through">{formatPrice(l.mrp)}</span>{" "}
              <span className="font-semibold text-deal-600">{l.discount_percent}% off</span>
            </p>
          )}
        </div>

        <a
          href={api.buyUrl(l)}
          target="_blank"
          rel="noopener noreferrer sponsored"
          aria-disabled={!l.in_stock}
          className={buttonClasses(l.is_best_deal ? "deal" : "secondary", "md", cn("w-full sm:w-auto", !l.in_stock && "pointer-events-none opacity-40"))}
        >
          {l.in_stock ? "Go to store" : "Unavailable"} <ArrowUpRight className="size-4" />
        </a>
      </div>

      <div className="mt-3 flex items-center justify-between gap-2 md:hidden">
        <p className="text-xs text-ink-500">{l.in_stock ? l.delivery_info : "Out of stock"}</p>
      </div>

      {l.offers.length > 0 && (
        <div className="mt-3 border-t border-dashed border-ink-200 pt-3">
          <button
            onClick={() => setShowOffers((s) => !s)}
            aria-expanded={showOffers}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-brand-600 hover:text-brand-700"
          >
            <Tag className="size-3.5" />
            {l.offers.length} offer{l.offers.length > 1 ? "s" : ""} available
            <ChevronDown className={cn("size-3.5 transition", showOffers && "rotate-180")} />
          </button>
          {showOffers && (
            <ul className="mt-3 grid animate-fade-up gap-2 sm:grid-cols-2">
              {l.offers.map((o) => {
                const Icon = OFFER_ICONS[o.type];
                return (
                  <li key={o.title} className="flex gap-2.5 rounded-xl bg-brand-50/60 p-3 text-xs">
                    <Icon className="mt-0.5 size-4 shrink-0 text-brand-600" />
                    <div>
                      <p className="font-semibold text-ink-800">{o.title}</p>
                      {o.description && <p className="mt-0.5 text-ink-500">{o.description}</p>}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

function Specs({ product }: { product: ProductDetail }) {
  const rows: [string, string][] = [
    ...Object.entries(product.attributes).map(([k, v]): [string, string] => [k, typeof v === "boolean" ? (v ? "Yes" : "No") : String(v)]),
    ...(product.model_number ? [["Model", product.model_number] as [string, string]] : []),
  ];
  if (!rows.length) return null;
  return (
    <div className="mt-6 rounded-3xl border border-ink-100 bg-white p-5 shadow-card">
      <h2 className="font-display text-lg font-semibold">Key specifications</h2>
      <dl className="mt-3 divide-y divide-ink-100 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4 py-2.5">
            <dt className="text-ink-500">{k}</dt>
            <dd className="text-right font-medium text-ink-800">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function ProductSkeleton() {
  return (
    <div className="mx-auto max-w-7xl px-4 pt-6 sm:px-6">
      <Skeleton className="h-4 w-48" />
      <div className="mt-6 grid gap-8 lg:grid-cols-[5fr_7fr] lg:gap-12">
        <Skeleton className="aspect-square rounded-[2rem]" />
        <div className="space-y-4">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-2/3" />
          <Skeleton className="h-40 w-full rounded-3xl" />
          <Skeleton className="h-24 w-full rounded-3xl" />
          <Skeleton className="h-24 w-full rounded-3xl" />
        </div>
      </div>
    </div>
  );
}
