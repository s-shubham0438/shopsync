import { Star } from "lucide-react";

import { formatCount } from "@/lib/format";
import { cn } from "@/lib/cn";

export function Rating({
  value,
  count,
  size = "sm",
  className,
}: {
  value: number | null;
  count?: number;
  size?: "sm" | "md";
  className?: string;
}) {
  if (value == null) return <span className="text-xs text-ink-400">No ratings yet</span>;
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <span
        className={cn(
          "inline-flex items-center gap-0.5 rounded-md bg-deal-600 font-semibold text-white",
          size === "sm" ? "px-1.5 py-0.5 text-xs" : "px-2 py-1 text-sm",
        )}
      >
        {value.toFixed(1)}
        <Star className={cn("fill-current", size === "sm" ? "size-3" : "size-3.5")} />
      </span>
      {count != null && (
        <span className={cn("text-ink-500", size === "sm" ? "text-xs" : "text-sm")}>
          {formatCount(count)} ratings
        </span>
      )}
    </span>
  );
}
