import { BellOff, BellRing, Check, Pencil, Trash2, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { ApiError, type PriceAlert } from "@/api";
import { ProductImage } from "@/components/product/ProductImage";
import { ButtonLink } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { useAlerts, useDeleteAlert, useUpdateAlert } from "@/hooks/queries";
import { cn } from "@/lib/cn";
import { formatPrice, formatRelativeTime, rupeesToPaise } from "@/lib/format";

import { AccountShell } from "./AccountShell";

export function AlertsPage() {
  const { data, isLoading } = useAlerts();
  const active = data?.filter((a) => a.is_active).length ?? 0;

  return (
    <AccountShell
      title="Price alerts"
      subtitle={data?.length ? `${active} active · we check every store several times a day` : "Get notified the moment a price drops to your target."}
    >
      {isLoading || !data ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-24 rounded-3xl" />
          ))}
        </div>
      ) : data.length === 0 ? (
        <EmptyState
          icon={BellRing}
          title="No price alerts yet"
          body="Open any product and tap “Price alert” to choose your target price."
          action={<ButtonLink to="/">Find a product</ButtonLink>}
        />
      ) : (
        <ul className="space-y-3">
          {data.map((alert) => (
            <AlertRow key={alert.id} alert={alert} />
          ))}
        </ul>
      )}
    </AccountShell>
  );
}

function AlertRow({ alert }: { alert: PriceAlert }) {
  const { product } = alert;
  const update = useUpdateAlert();
  const remove = useDeleteAlert();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(String(alert.target_price / 100));

  const gap = product.best_price - alert.target_price;
  const progress = Math.max(0, Math.min(100, (alert.target_price / product.best_price) * 100));
  const reached = gap <= 0;

  async function save() {
    const target = rupeesToPaise(Number(value));
    if (!target || target <= 0) return;
    try {
      await update.mutateAsync({ id: alert.id, patch: { target_price: target } });
      setEditing(false);
      toast({ tone: "success", title: "Alert updated" });
    } catch (e) {
      toast({ tone: "error", title: e instanceof ApiError ? e.message : "Couldn't update alert" });
    }
  }

  return (
    <li className={cn("rounded-3xl border bg-white p-4 shadow-card transition", alert.is_active ? "border-ink-100" : "border-ink-100 opacity-60")}>
      <div className="flex flex-wrap items-center gap-4">
        <Link to={`/products/${product.id}`} className="shrink-0">
          <ProductImage title={product.canonical_title} imageUrl={product.image_url} category={product.category} className="size-16 rounded-2xl" />
        </Link>
        <div className="min-w-48 flex-1">
          <Link to={`/products/${product.id}`} className="line-clamp-1 font-semibold text-ink-900 hover:text-brand-600">
            {product.canonical_title}
          </Link>
          <div className="mt-2 flex items-center gap-3 text-xs">
            <div className="h-1.5 w-32 overflow-hidden rounded-full bg-ink-100" aria-hidden>
              <div className={cn("h-full rounded-full", reached ? "bg-deal-500" : "bg-gradient-brand")} style={{ width: `${progress}%` }} />
            </div>
            <span className={reached ? "font-semibold text-deal-700" : "text-ink-500"}>
              {reached ? "Target reached!" : `${formatPrice(gap)} to go`}
            </span>
          </div>
          {alert.last_notified_at && <p className="mt-1 text-xs text-ink-400">Last notified {formatRelativeTime(alert.last_notified_at)}</p>}
        </div>

        <div className="grid grid-cols-2 gap-6 text-sm">
          <div>
            <p className="text-xs text-ink-400">Now</p>
            <p className="font-semibold tabular-nums">{formatPrice(product.best_price)}</p>
          </div>
          <div>
            <p className="text-xs text-ink-400">Your target</p>
            {editing ? (
              <div className="flex items-center gap-1">
                <span className="text-ink-400">₹</span>
                <input
                  value={value}
                  onChange={(e) => setValue(e.target.value.replace(/\D/g, ""))}
                  onKeyDown={(e) => e.key === "Enter" && save()}
                  inputMode="numeric"
                  autoFocus
                  aria-label="Target price in rupees"
                  className="w-20 rounded-md border border-ink-200 px-1.5 py-0.5 font-semibold tabular-nums focus:border-brand-400 focus:outline-none"
                />
                <button onClick={save} className="rounded-md p-1 text-deal-600 hover:bg-deal-50" aria-label="Save">
                  <Check className="size-4" />
                </button>
                <button onClick={() => setEditing(false)} className="rounded-md p-1 text-ink-400 hover:bg-ink-100" aria-label="Cancel">
                  <X className="size-4" />
                </button>
              </div>
            ) : (
              <button onClick={() => setEditing(true)} className="group inline-flex items-center gap-1.5 font-semibold text-brand-600 tabular-nums">
                {formatPrice(alert.target_price)}
                <Pencil className="size-3.5 opacity-50 group-hover:opacity-100" />
              </button>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            role="switch"
            aria-checked={alert.is_active}
            aria-label={alert.is_active ? "Pause alert" : "Resume alert"}
            onClick={() => update.mutate({ id: alert.id, patch: { is_active: !alert.is_active } })}
            className={cn("relative h-6 w-11 rounded-full transition", alert.is_active ? "bg-deal-500" : "bg-ink-200")}
          >
            <span className={cn("absolute top-0.5 left-0.5 size-5 rounded-full bg-white shadow transition", alert.is_active && "translate-x-5")} />
          </button>
          <button
            onClick={async () => {
              await remove.mutateAsync(alert.id);
              toast({ tone: "success", title: "Alert deleted" });
            }}
            className="grid size-9 place-items-center rounded-xl text-ink-400 transition hover:bg-rose-50 hover:text-rose-600"
            aria-label="Delete alert"
          >
            <Trash2 className="size-4" />
          </button>
        </div>
      </div>
      {!alert.is_active && (
        <p className="mt-3 inline-flex items-center gap-1.5 text-xs text-ink-500">
          <BellOff className="size-3.5" /> Paused — you won't get notifications for this product.
        </p>
      )}
    </li>
  );
}
