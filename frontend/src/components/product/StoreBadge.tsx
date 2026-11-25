import type { Platform } from "@/api";
import { cn } from "@/lib/cn";

/** Monogram tiles in each store's colours (no trademark logos bundled). */
const STYLES: Record<string, { bg: string; fg: string; mark: string }> = {
  amazon: { bg: "#131921", fg: "#FF9900", mark: "a" },
  flipkart: { bg: "#2874F0", fg: "#FFE11B", mark: "F" },
  myntra: { bg: "linear-gradient(135deg,#FF3F6C,#F97B4F)", fg: "#FFFFFF", mark: "M" },
  ajio: { bg: "#2C4152", fg: "#E8D9B5", mark: "A" },
  croma: { bg: "#12DAA8", fg: "#0B1020", mark: "C" },
  tatacliq: { bg: "#1A1A1A", fg: "#FFFFFF", mark: "TC" },
};

const SIZES = {
  xs: "size-5 rounded-md text-[10px]",
  sm: "size-7 rounded-lg text-xs",
  md: "size-10 rounded-xl text-sm",
  lg: "size-12 rounded-2xl text-base",
};

export function StoreBadge({
  platform,
  size = "sm",
  className,
}: {
  platform: Platform;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const style = STYLES[platform.slug] ?? { bg: "#3A4366", fg: "#FFFFFF", mark: platform.name[0] ?? "?" };
  if (platform.logo_url) {
    return <img src={platform.logo_url} alt={platform.name} className={cn(SIZES[size], "object-contain", className)} />;
  }
  return (
    <span
      title={platform.name}
      aria-label={platform.name}
      className={cn("inline-grid shrink-0 place-items-center font-display font-bold tracking-tight", SIZES[size], className)}
      style={{ background: style.bg, color: style.fg }}
    >
      {style.mark}
    </span>
  );
}

export const PLATFORM_COLORS: Record<string, string> = {
  amazon: "#FF9900",
  flipkart: "#2874F0",
  myntra: "#FF3F6C",
  ajio: "#2C4152",
  croma: "#0FB98E",
  tatacliq: "#7C3AED",
};
