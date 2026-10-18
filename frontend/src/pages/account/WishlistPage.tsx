import { ArrowRight, Heart, Trash2, TrendingDown } from "lucide-react";
import { Link } from "react-router";

import { ProductImage } from "@/components/product/ProductImage";
import { StoreBadge } from "@/components/product/StoreBadge";
import { AlertButton } from "@/components/product/ProductActions";
import { ButtonLink } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { useRemoveFromWishlist, useWishlist } from "@/hooks/queries";
import { formatPrice, formatRelativeTime } from "@/lib/format";

import { AccountShell } from "./AccountShell";

export function WishlistPage() {
  const { data, isLoading } = useWishlist();
  const remove = useRemoveFromWishlist();
  const toast = useToast();

  return (
    <AccountShell title="Your wishlist" subtitle="Products you're watching, with today's best price across every store.">
      {isLoading || !data ? (
        <div className="space-y-4">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-32 rounded-3xl" />
          ))}
        </div>
      ) : data.length === 0 ? (
        <EmptyState
          icon={Heart}
          title="Your wishlist is empty"
          body="Tap the heart on any product to save it here and keep an eye on its price."
          action={<ButtonLink to="/">Discover deals</ButtonLink>}
        />
      ) : (
        <ul className="space-y-4">
          {data.map(({ id, product, created_at, target_price }, i) => (
            <li key={id} style={{ animationDelay: `${i * 70}ms` }} className="flex animate-fade-up flex-col gap-4 rounded-3xl border border-ink-100 bg-white p-4 shadow-card sm:flex-row sm:items-center">
              <Link to={`/products/${product.id}`} className="shrink-0">
                <ProductImage
                  title={product.canonical_title}
                  imageUrl={product.image_url}
                  category={product.category}
                  className="aspect-[4/3] w-full rounded-2xl sm:size-28 sm:aspect-auto"
                />
              </Link>
              <div className="min-w-0 flex-1">
                <p className="text-[11px] font-semibold tracking-wider text-ink-400 uppercase">{product.brand}</p>
                <Link to={`/products/${product.id}`} className="line-clamp-2 font-semibold text-ink-900 hover:text-brand-600">
                  {product.canonical_title}
                </Link>
                <p className="mt-1 text-xs text-ink-400">Saved {formatRelativeTime(created_at)}</p>
                {target_price != null && product.best_price <= target_price && (
                  <p className="mt-2 inline-flex items-center gap-1 rounded-full bg-deal-50 px-2.5 py-1 text-xs font-semibold text-deal-700">
                    <TrendingDown className="size-3.5" /> Below your target of {formatPrice(target_price)}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-3 sm:flex-col sm:items-end">
                <div className="sm:text-right">
                  <p className="font-display text-2xl font-bold tabular-nums">{formatPrice(product.best_price)}</p>
                  <p className="flex items-center gap-1.5 text-xs text-ink-500 sm:justify-end">
                    on <StoreBadge platform={product.best_platform} size="xs" /> {product.best_platform.name}
                  </p>
                </div>
              </div>
              <div className="flex gap-2 sm:flex-col">
                <ButtonLink to={`/products/${product.id}`} variant="primary" size="sm" className="flex-1">
                  Compare <ArrowRight className="size-4" />
                </ButtonLink>
                <div className="flex gap-2">
                  <AlertButton product={product} size="sm" className="flex-1" />
                  <button
                    onClick={async () => {
                      await remove.mutateAsync(id);
                      toast({ tone: "success", title: "Removed from wishlist" });
                    }}
                    className="grid size-9 shrink-0 place-items-center rounded-xl border border-ink-200 text-ink-400 transition hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600"
                    aria-label="Remove from wishlist"
                  >
                    <Trash2 className="size-4" />
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </AccountShell>
  );
}
