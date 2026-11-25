import { Bell, Heart, History } from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router";

import { displayName, useAuth } from "@/auth/AuthProvider";
import { cn } from "@/lib/cn";

const TABS = [
  { to: "/wishlist", label: "Wishlist", icon: Heart },
  { to: "/alerts", label: "Price alerts", icon: Bell },
  { to: "/history", label: "Search history", icon: History },
];

export function AccountShell({
  title,
  subtitle,
  action,
  children,
}: {
  title: string;
  subtitle: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  const { user } = useAuth();
  return (
    <div className="mx-auto max-w-6xl px-4 pt-8 sm:px-6">
      <p className="text-sm text-ink-500">Hi, {user ? displayName(user) : "there"} 👋</p>
      <nav className="mt-4 flex gap-1 overflow-x-auto border-b border-ink-200">
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              cn(
                "-mb-px inline-flex shrink-0 items-center gap-2 border-b-2 px-4 py-3 text-sm font-semibold transition",
                isActive ? "border-brand-500 text-ink-900" : "border-transparent text-ink-500 hover:text-ink-800",
              )
            }
          >
            <t.icon className="size-4" /> {t.label}
          </NavLink>
        ))}
      </nav>
      <div className="mt-8 mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight">{title}</h1>
          <p className="mt-1 text-sm text-ink-500">{subtitle}</p>
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}
