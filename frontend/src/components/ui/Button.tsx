import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link, type LinkProps } from "react-router";

import { cn } from "@/lib/cn";

import { Spinner } from "./Spinner";

type Variant = "primary" | "secondary" | "ghost" | "dark" | "deal" | "light";
type Size = "sm" | "md" | "lg";

const base =
  "inline-flex items-center justify-center gap-2 rounded-xl font-semibold whitespace-nowrap transition-all duration-200 ease-out disabled:pointer-events-none disabled:opacity-50 active:scale-[0.97]";

const variants: Record<Variant, string> = {
  primary: "btn-shine bg-gradient-brand text-brand-50 shadow-glow hover:-translate-y-px hover:shadow-lift",
  secondary: "border border-ink-200 bg-white text-ink-800 hover:-translate-y-px hover:border-ink-300 hover:bg-brand-50 hover:shadow-card",
  ghost: "text-ink-600 hover:bg-ink-100 hover:text-ink-900",
  dark: "btn-shine bg-ink-800 text-brand-50 hover:-translate-y-px hover:bg-ink-700",
  light: "btn-shine bg-brand-100 text-ink-900 hover:-translate-y-px hover:bg-white",
  deal: "btn-shine bg-deal-600 text-white shadow-[0_8px_24px_-8px_rgb(35_130_79_/_0.55)] hover:-translate-y-px hover:bg-deal-700",
};

const sizes: Record<Size, string> = {
  sm: "h-9 px-3.5 text-sm",
  md: "h-11 px-5 text-sm",
  lg: "h-13 px-6 text-base",
};

interface CommonProps {
  variant?: Variant;
  size?: Size;
  className?: string;
  children: ReactNode;
}

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  className,
  children,
  disabled,
  ...rest
}: CommonProps & ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean }) {
  return (
    <button className={cn(base, variants[variant], sizes[size], className)} disabled={disabled || loading} {...rest}>
      {loading && <Spinner className="size-4" />}
      {children}
    </button>
  );
}

export function ButtonLink({ variant = "primary", size = "md", className, children, ...rest }: CommonProps & LinkProps) {
  return (
    <Link className={cn(base, variants[variant], sizes[size], className)} {...rest}>
      {children}
    </Link>
  );
}

export const buttonClasses = (variant: Variant = "primary", size: Size = "md", className?: string) =>
  cn(base, variants[variant], sizes[size], className);
