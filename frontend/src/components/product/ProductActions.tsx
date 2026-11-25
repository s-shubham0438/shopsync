import { Bell, BellRing, Heart } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router";

import { ApiError, type ProductSummary } from "@/api";
import { useAuth } from "@/auth/AuthProvider";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { useAddToWishlist, useAlerts, useCreateAlert, useRemoveFromWishlist, useWishlist } from "@/hooks/queries";
import { cn } from "@/lib/cn";
import { formatPrice, rupeesToPaise } from "@/lib/format";

function useRequireLogin() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  return (action: () => void) => {
    if (user) return action();
    navigate(`/login?next=${encodeURIComponent(location.pathname)}`);
  };
}

const errorMessage = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

export function WishlistButton({ product, className }: { product: ProductSummary; className?: string }) {
  const { user } = useAuth();
  const toast = useToast();
  const requireLogin = useRequireLogin();
  const { data: wishlist } = useWishlist(!!user);
  const add = useAddToWishlist();
  const remove = useRemoveFromWishlist();
  const entry = wishlist?.find((w) => w.product.id === product.id);

  const toggle = () =>
    requireLogin(async () => {
      try {
        if (entry) {
          await remove.mutateAsync(entry.id);
          toast({ tone: "success", title: "Removed from wishlist" });
        } else {
          await add.mutateAsync({ productId: product.id });
          toast({ tone: "success", title: "Saved to wishlist", body: "We'll keep an eye on the price for you." });
        }
      } catch (e) {
        toast({ tone: "error", title: errorMessage(e) });
      }
    });

  return (
    <Button
      variant="secondary"
      size="lg"
      onClick={toggle}
      loading={add.isPending || remove.isPending}
      aria-pressed={!!entry}
      className={className}
    >
      <Heart key={entry ? "on" : "off"} className={cn("size-5", entry && "animate-pop fill-rose-500 text-rose-500")} />
      {entry ? "Saved" : "Wishlist"}
    </Button>
  );
}

export function AlertButton({
  product,
  className,
  size = "lg",
}: {
  product: ProductSummary;
  className?: string;
  size?: "sm" | "lg";
}) {
  const { user } = useAuth();
  const requireLogin = useRequireLogin();
  const [open, setOpen] = useState(false);
  const { data: alerts } = useAlerts(!!user);
  const existing = alerts?.find((a) => a.product.id === product.id && a.is_active);

  return (
    <>
      <Button variant="secondary" size={size} onClick={() => requireLogin(() => setOpen(true))} className={className}>
        {existing ? <BellRing className="size-5 text-brand-500" /> : <Bell className="size-5" />}
        {existing ? `Alert at ${formatPrice(existing.target_price)}` : "Price alert"}
      </Button>
      {open && <AlertModal product={product} initialTarget={existing?.target_price} onClose={() => setOpen(false)} />}
    </>
  );
}

function AlertModal({
  product,
  initialTarget,
  onClose,
}: {
  product: ProductSummary;
  initialTarget?: number;
  onClose: () => void;
}) {
  const toast = useToast();
  const create = useCreateAlert();
  const suggested = Math.floor((product.best_price * 0.9) / 10000) * 100; // ~10% lower, in rupees
  const [rupees, setRupees] = useState(String(initialTarget ? initialTarget / 100 : suggested));
  const [error, setError] = useState<string | null>(null);

  const target = rupeesToPaise(Number(rupees));
  const quick = [5, 10, 15].map((pct) => Math.floor((product.best_price * (1 - pct / 100)) / 10000) * 100);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!Number.isFinite(target) || target <= 0) return setError("Enter a valid price.");
    if (target >= product.best_price) return setError(`Must be below today's best price of ${formatPrice(product.best_price)}.`);
    try {
      await create.mutateAsync({ productId: product.id, targetPrice: target });
      toast({ tone: "success", title: "Price alert set", body: `We'll notify you when it drops to ${formatPrice(target)}.` });
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Modal open onClose={onClose} title="Get a price-drop alert">
      <p className="text-sm text-ink-500">
        Today's best price is <span className="font-semibold text-ink-900">{formatPrice(product.best_price)}</span> on{" "}
        {product.best_platform.name}. We check every store several times a day.
      </p>
      <form onSubmit={submit} className="mt-5 space-y-4">
        <label className="block">
          <span className="text-sm font-semibold text-ink-700">Alert me when the price drops to</span>
          <div className="mt-2 flex items-center rounded-xl border border-ink-200 focus-within:border-brand-400 focus-within:ring-4 focus-within:ring-brand-500/10">
            <span className="pl-4 text-lg font-semibold text-ink-400">₹</span>
            <input
              inputMode="numeric"
              value={rupees}
              onChange={(e) => {
                setRupees(e.target.value.replace(/[^\d]/g, ""));
                setError(null);
              }}
              className="w-full bg-transparent px-2 py-3 font-display text-2xl font-semibold tabular-nums focus:outline-none"
              aria-invalid={!!error}
              autoFocus
            />
          </div>
        </label>
        <div className="flex flex-wrap gap-2">
          {quick.map((v, i) => (
            <button
              type="button"
              key={v}
              onClick={() => setRupees(String(v))}
              className="rounded-full border border-ink-200 px-3 py-1 text-xs font-semibold text-ink-600 hover:border-brand-300 hover:bg-brand-50 hover:text-brand-700"
            >
              {[5, 10, 15][i]}% lower · ₹{v.toLocaleString("en-IN")}
            </button>
          ))}
        </div>
        {error && <p className="animate-fade-up text-sm font-medium text-rose-700">{error}</p>}
        <Button type="submit" size="lg" className="w-full" loading={create.isPending}>
          <BellRing className="size-5" /> Set alert
        </Button>
      </form>
    </Modal>
  );
}
