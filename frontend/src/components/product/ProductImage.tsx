import {
  Backpack,
  Footprints,
  Headphones,
  Laptop,
  Luggage,
  Package,
  Shirt,
  Smartphone,
  Speaker,
  Watch,
  type LucideIcon,
} from "lucide-react";

import type { Category } from "@/api";
import { cn } from "@/lib/cn";

interface Look {
  icon: LucideIcon;
  bg: string;
  fg: string;
}

const LOOKS: Record<string, Look> = {
  mobiles: { icon: Smartphone, bg: "from-brand-100 via-brand-50 to-ink-100", fg: "text-ink-700" },
  audio: { icon: Headphones, bg: "from-brand-200 via-brand-50 to-brand-100", fg: "text-brand-700" },
  wearables: { icon: Watch, bg: "from-ink-100 via-brand-50 to-brand-200", fg: "text-ink-600" },
  laptops: { icon: Laptop, bg: "from-ink-200 via-ink-100 to-brand-100", fg: "text-ink-700" },
  footwear: { icon: Footprints, bg: "from-brand-200 via-brand-100 to-brand-50", fg: "text-brand-700" },
  clothing: { icon: Shirt, bg: "from-brand-50 via-ink-100 to-brand-200", fg: "text-ink-700" },
  bags: { icon: Backpack, bg: "from-brand-100 via-brand-200 to-brand-50", fg: "text-brand-600" },
};

export function categoryLook(slug: string | undefined): Look {
  return LOOKS[slug ?? ""] ?? { icon: Package, bg: "from-ink-100 via-white to-ink-200", fg: "text-ink-500" };
}

/** Real image when the API has one; otherwise a branded category illustration. */
export function ProductImage({
  title,
  imageUrl,
  category,
  brand,
  className,
  iconClassName,
}: {
  title: string;
  imageUrl: string | null;
  category: Category | null;
  brand?: string | null;
  className?: string;
  iconClassName?: string;
}) {
  if (imageUrl) {
    return (
      <div className={cn("grid place-items-center bg-white", className)}>
        <img src={imageUrl} alt={title} loading="lazy" className="size-full object-contain p-4" />
      </div>
    );
  }
  const look = categoryLook(category?.slug);
  let Icon = look.icon;
  if (/speaker/i.test(title)) Icon = Speaker;
  if (/trolley|suitcase/i.test(title)) Icon = Luggage;

  return (
    <div className={cn("relative grid place-items-center overflow-hidden bg-linear-to-br", look.bg, className)} role="img" aria-label={title}>
      <div className="absolute -right-8 -top-8 size-32 rounded-full bg-white/50 blur-2xl" />
      <div className="absolute -bottom-10 -left-6 size-28 rounded-full bg-white/40 blur-2xl" />
      <Icon className={cn("relative size-1/3 drop-shadow-sm transition-transform duration-500 ease-out group-hover:scale-110 group-hover:-rotate-3", look.fg, iconClassName)} strokeWidth={1.25} />
      {brand && (
        <span className="absolute bottom-3 left-3 rounded-full bg-white/70 px-2 py-0.5 text-[10px] font-semibold tracking-wide text-ink-600 uppercase backdrop-blur">
          {brand}
        </span>
      )}
    </div>
  );
}
