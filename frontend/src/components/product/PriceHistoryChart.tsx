import { TrendingDown } from "lucide-react";
import { useMemo, useRef, useState, type PointerEvent } from "react";

import type { PriceHistory, PriceHistorySeries } from "@/api";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/cn";
import { formatDate, formatPrice, formatShortDate } from "@/lib/format";

import { PLATFORM_COLORS, StoreBadge } from "./StoreBadge";

const W = 720;
const H = 260;
const PAD = { top: 16, right: 16, bottom: 28, left: 64 };

export const RANGES = [
  { label: "1M", days: 30 },
  { label: "3M", days: 90 },
  { label: "6M", days: 180 },
  { label: "1Y", days: 365 },
] as const;

function niceTicks(min: number, max: number, count = 4): number[] {
  const span = max - min || 1;
  const step = 10 ** Math.floor(Math.log10(span / count));
  const nice = [1, 2, 2.5, 5, 10].map((m) => m * step).find((s) => span / s <= count) ?? step * 10;
  const start = Math.floor(min / nice) * nice;
  const ticks: number[] = [];
  for (let v = start; v <= max + nice / 2; v += nice) if (v >= min - nice / 2) ticks.push(v);
  return ticks;
}

/** Closest point in a time-sorted series (binary search). */
function nearest(series: PriceHistorySeries, t: number) {
  const pts = series.points;
  let lo = 0;
  let hi = pts.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (new Date(pts[mid]!.recorded_at).getTime() < t) lo = mid + 1;
    else hi = mid;
  }
  const a = pts[Math.max(0, lo - 1)];
  const b = pts[lo];
  if (!a || !b) return a ?? b;
  return Math.abs(new Date(a.recorded_at).getTime() - t) < Math.abs(new Date(b.recorded_at).getTime() - t) ? a : b;
}

export function PriceHistoryChart({
  history,
  days,
  onDaysChange,
  loading,
}: {
  history: PriceHistory | undefined;
  days: number;
  onDaysChange: (days: number) => void;
  loading: boolean;
}) {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [hoverT, setHoverT] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const visible = useMemo(
    () => history?.series.filter((s) => !hidden.has(s.listing_id) && s.points.length) ?? [],
    [history, hidden],
  );

  const geometry = useMemo(() => {
    const all = visible.flatMap((s) => s.points);
    if (!all.length) return null;
    const times = all.map((p) => new Date(p.recorded_at).getTime());
    const prices = all.map((p) => p.price);
    const t0 = Math.min(...times);
    const t1 = Math.max(...times);
    const pMin = Math.min(...prices);
    const pMax = Math.max(...prices);
    const pad = (pMax - pMin) * 0.12 || pMax * 0.05;
    const yMin = pMin - pad;
    const yMax = pMax + pad;
    const x = (t: number) => PAD.left + ((t - t0) / (t1 - t0 || 1)) * (W - PAD.left - PAD.right);
    const y = (p: number) => PAD.top + (1 - (p - yMin) / (yMax - yMin)) * (H - PAD.top - PAD.bottom);
    const xTicks = Array.from({ length: 5 }, (_, i) => t0 + ((t1 - t0) * i) / 4);
    return { t0, t1, x, y, yTicks: niceTicks(yMin, yMax), xTicks };
  }, [visible]);

  function onMove(e: PointerEvent<SVGSVGElement>) {
    if (!geometry || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    const ratio = Math.min(1, Math.max(0, (px - PAD.left) / (W - PAD.left - PAD.right)));
    setHoverT(geometry.t0 + ratio * (geometry.t1 - geometry.t0));
  }

  const hoverRows =
    hoverT != null
      ? visible
          .map((s) => ({ s, pt: nearest(s, hoverT) }))
          .filter((r) => r.pt)
          .sort((a, b) => a.pt!.price - b.pt!.price)
      : [];
  const hoverX = hoverT != null && geometry ? geometry.x(hoverT) : null;

  return (
    <section className="rounded-3xl border border-ink-100 bg-white p-5 shadow-card sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-xl font-semibold">Price history</h2>
          {history?.lowest_price != null && history.lowest_at && (
            <p className="mt-1 inline-flex items-center gap-1.5 text-sm text-ink-500">
              <TrendingDown className="size-4 text-deal-600" />
              Lowest in this period:
              <span className="font-semibold text-deal-700">{formatPrice(history.lowest_price)}</span>
              on {formatDate(history.lowest_at)}
            </p>
          )}
        </div>
        <div className="inline-flex rounded-xl bg-ink-100 p-1" role="tablist" aria-label="Time range">
          {RANGES.map((r) => (
            <button
              key={r.days}
              role="tab"
              aria-selected={days === r.days}
              onClick={() => onDaysChange(r.days)}
              className={cn(
                "rounded-lg px-3 py-1.5 text-xs font-semibold transition",
                days === r.days ? "bg-white text-ink-900 shadow-sm" : "text-ink-500 hover:bg-white/60 hover:text-ink-800",
              )}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* Store toggles double as the legend */}
      <div className="mt-4 flex flex-wrap gap-2">
        {history?.series.map((s) => {
          const off = hidden.has(s.listing_id);
          return (
            <button
              key={s.listing_id}
              onClick={() =>
                setHidden((h) => {
                  const next = new Set(h);
                  if (next.has(s.listing_id)) next.delete(s.listing_id);
                  else next.add(s.listing_id);
                  return next;
                })
              }
              aria-pressed={!off}
              className={cn(
                "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold transition",
                off ? "border-ink-200 text-ink-400" : "border-ink-200 bg-white text-ink-700 hover:border-ink-300",
              )}
            >
              <span
                className="size-2.5 rounded-full"
                style={{ background: off ? "#B8BED4" : (PLATFORM_COLORS[s.platform.slug] ?? "#5B6488") }}
              />
              {s.platform.name}
            </button>
          );
        })}
      </div>

      <div className="relative mt-4">
        {loading && !history ? (
          <Skeleton className="aspect-[720/260] w-full rounded-2xl" />
        ) : !geometry ? (
          <div className="grid aspect-[720/260] place-items-center rounded-2xl bg-surface text-sm text-ink-400">
            Select at least one store to see its price trend.
          </div>
        ) : (
          <>
            <svg
              ref={svgRef}
              viewBox={`0 0 ${W} ${H}`}
              className={cn("w-full touch-none select-none transition-opacity", loading && "opacity-50")}
              onPointerMove={onMove}
              onPointerLeave={() => setHoverT(null)}
              role="img"
              aria-label="Price history chart"
            >
              {geometry.yTicks.map((v) => (
                <g key={v}>
                  <line x1={PAD.left} x2={W - PAD.right} y1={geometry.y(v)} y2={geometry.y(v)} stroke="#EEF0F6" />
                  <text x={PAD.left - 10} y={geometry.y(v)} dy="0.32em" textAnchor="end" className="fill-ink-400 text-[11px] tabular-nums">
                    {formatPrice(Math.round(v / 100) * 100)}
                  </text>
                </g>
              ))}
              {geometry.xTicks.map((t, i) => (
                <text
                  key={t}
                  x={geometry.x(t)}
                  y={H - 6}
                  textAnchor={i === 0 ? "start" : i === 4 ? "end" : "middle"}
                  className="fill-ink-400 text-[11px]"
                >
                  {formatShortDate(new Date(t).toISOString())}
                </text>
              ))}

              {visible.map((s) => {
                const color = PLATFORM_COLORS[s.platform.slug] ?? "#5B6488";
                const d = s.points
                  .map((p, i) => `${i ? "L" : "M"}${geometry.x(new Date(p.recorded_at).getTime()).toFixed(1)},${geometry.y(p.price).toFixed(1)}`)
                  .join("");
                return (
                  <path
                    key={`${s.listing_id}-${days}`}
                    d={d}
                    fill="none"
                    stroke={color}
                    strokeWidth={2}
                    strokeLinejoin="round"
                    strokeLinecap="round"
                    pathLength={1}
                    strokeDasharray={1}
                    className="animate-draw"
                  />
                );
              })}

              {hoverX != null && (
                <g>
                  <line x1={hoverX} x2={hoverX} y1={PAD.top} y2={H - PAD.bottom} stroke="#8A92B2" strokeDasharray="3 3" />
                  {hoverRows.map(({ s, pt }) => (
                    <circle
                      key={s.listing_id}
                      cx={geometry.x(new Date(pt!.recorded_at).getTime())}
                      cy={geometry.y(pt!.price)}
                      r={4.5}
                      fill="white"
                      stroke={PLATFORM_COLORS[s.platform.slug] ?? "#5B6488"}
                      strokeWidth={2.5}
                    />
                  ))}
                </g>
              )}
            </svg>

            {hoverX != null && hoverRows.length > 0 && (
              <div
                className="pointer-events-none absolute top-2 z-10 w-52 animate-fade-in rounded-2xl border border-ink-100 bg-white/95 p-3 shadow-lift backdrop-blur"
                style={
                  hoverX / W > 0.55
                    ? { right: `${(1 - hoverX / W) * 100 + 2}%` }
                    : { left: `${(hoverX / W) * 100 + 2}%` }
                }
              >
                <p className="mb-2 text-xs font-semibold text-ink-500">{formatDate(hoverRows[0]!.pt!.recorded_at)}</p>
                <ul className="space-y-1.5">
                  {hoverRows.map(({ s, pt }, i) => (
                    <li key={s.listing_id} className="flex items-center justify-between gap-2 text-sm">
                      <span className="flex items-center gap-2">
                        <StoreBadge platform={s.platform} size="xs" />
                        <span className="text-ink-600">{s.platform.name}</span>
                      </span>
                      <span className={cn("font-semibold tabular-nums", i === 0 ? "text-deal-700" : "text-ink-900")}>
                        {formatPrice(pt!.price)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
