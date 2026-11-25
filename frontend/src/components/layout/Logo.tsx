import { Link } from "react-router";

import { cn } from "@/lib/cn";

/*
 * ShopSync mark: a shopping bag split by an "S" (dark grey top-left, tan bottom-right)
 * with speed lines either side. Paths use the original artwork's coordinate space.
 */
const DARK = "var(--color-ink-700)";
const TAN = "var(--color-brand-400)";

const HANDLE = "M557 432V412a70 70 0 0 1 140 0v20";
const DARK_PART =
  "M757 462L548 532C512 544 512 578 545 584L628 606L492 650C470 656 457 640 460 615L490 462C496 441 508 432 530 432H718C738 432 750 445 757 462Z";
const TAN_PART =
  "M770 497L610 546L712 568C748 576 748 612 718 620L500 690C518 707 536 718 562 718H712C765 718 796 676 792 626L780 516C778 504 775 498 770 497Z";

export function LogoMark({ className, speedLines = false }: { className?: string; speedLines?: boolean }) {
  return (
    <svg
      viewBox={speedLines ? "335 330 585 395" : "445 330 360 395"}
      className={cn("overflow-visible", className)}
      aria-hidden
    >
      {speedLines && (
        <g strokeWidth={26} strokeLinecap="round">
          <g stroke={TAN} className="transition-transform duration-500 ease-out group-hover:-translate-x-[30px]">
            <path d="M401 499H449" />
            <path d="M353 549H431" />
          </g>
          <g stroke={DARK} className="transition-transform duration-500 ease-out group-hover:translate-x-[30px]">
            <path d="M831 551H899" />
            <path d="M821 599H861" />
          </g>
        </g>
      )}
      <path d={HANDLE} fill="none" stroke={DARK} strokeWidth={24} />
      <path d={DARK_PART} fill={DARK} />
      <path d={TAN_PART} fill={TAN} />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("font-logo font-semibold tracking-[-0.02em] lowercase", className)}>
      <span className="text-ink-700">shop</span>
      <span className="text-brand-400">sync</span>
    </span>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <Link to="/" className={cn("group inline-flex items-center gap-2", className)} aria-label="ShopSync home">
      <LogoMark speedLines className="h-8 w-auto transition-transform duration-300 ease-out group-hover:-rotate-3" />
      <Wordmark className="text-[1.4rem] leading-none" />
    </Link>
  );
}
