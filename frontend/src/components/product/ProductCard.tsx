import { ArrowRight, Store } from "lucide-react";
import { Link } from "react-router";

import type { ProductSummary } from "@/api";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatPrice } from "@/lib/format";

import { ProductImage } from "./ProductImage";
import { Rating } from "./Rating";
import { StoreBadge } from "./StoreBadge";

export function ProductCard({ product }: { product: ProductSummary }) {
  const spread = product.highest_price - product.best_price;
  return (
    <Link
      to={`/products/${product.id}`}
      className="group flex flex-col overflow-hidden rounded-3xl border border-ink-100 bg-white shadow-card transition duration-200 hover:-translate-y-1 hover:border-ink-200 hover:shadow-lift"
    >
      <div className="relative">
        <ProductImage
          title={product.canonical_title}
          imageUrl={product.image_url}
          category={product.category}
          className="aspect-[4/3] transition duration-300 group-hover:scale-[1.03]"
        />
        {product.max_discount_percent ? (
          <span className="absolute left-3 top-3 rounded-full bg-ink-900 px-2.5 py-1 text-xs font-bold text-brand-100 shadow-sm">
            −{product.max_discount_percent}%
          </span>
        ) : null}
        <span className="absolute right-3 top-3 inline-flex items-center gap-1 rounded-full bg-white/85 px-2.5 py-1 text-xs font-semibold text-ink-700 backdrop-blur">
          <Store className="size-3.5" />
          {product.store_count} stores
        </span>
      </div>

      <div className="flex flex-1 flex-col p-4">
        {product.brand && (
          <p className="text-[11px] font-semibold tracking-wider text-ink-400 uppercase">{product.brand}</p>
        )}
        <h3 className="mt-1 line-clamp-2 min-h-10 text-sm leading-5 font-semibold text-ink-900 group-hover:text-brand-600">
          {product.canonical_title}
        </h3>
        <Rating value={product.rating} count={product.review_count} className="mt-2" />

        <div className="mt-auto pt-4">
          <div className="flex items-end justify-between gap-2">
            <div>
              <p className="text-[11px] font-medium text-ink-400">Best price</p>
              <p className="font-display text-2xl font-bold tracking-tight text-ink-900 tabular-nums">
                {formatPrice(product.best_price)}
              </p>
            </div>
            <div className="flex items-center gap-1.5 pb-1 text-xs text-ink-500">
              at <StoreBadge platform={product.best_platform} size="xs" />
              <span className="font-semibold text-ink-700">{product.best_platform.name}</span>
            </div>
          </div>
          <div className="mt-3 flex items-center justify-between border-t border-dashed border-ink-200 pt-3 text-xs">
            {spread > 0 ? (
              <span className="font-semibold text-deal-600">Save up to {formatPrice(spread)}</span>
            ) : (
              <span className="text-ink-400">Same price everywhere</span>
            )}
            <span className="inline-flex items-center gap-1 font-semibold text-ink-700 group-hover:text-brand-600">
              Compare <ArrowRight className="size-3.5 transition group-hover:translate-x-0.5" />
            </span>
          </div>
        </div>
      </div>
    </Link>
  );
}

export function ProductCardSkeleton() {
  return (
    <div className="overflow-hidden rounded-3xl border border-ink-100 bg-white">
      <Skeleton className="aspect-[4/3] rounded-none" />
      <div className="space-y-3 p-4">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-7 w-28" />
      </div>
    </div>
  );
}
