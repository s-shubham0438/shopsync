import { Bell, ChevronDown, Heart, History, LogOut, User as UserIcon } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router";

import { displayName, useAuth } from "@/auth/AuthProvider";
import { SearchBar } from "@/components/SearchBar";
import { ButtonLink } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";

import { Logo } from "./Logo";

function useScrolled(threshold = 8) {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > threshold);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [threshold]);
  return scrolled;
}

export function Header() {
  const { pathname } = useLocation();
  const isHome = pathname === "/";
  const scrolled = useScrolled();
  // On the home page the header blends into the hero (which has its own big search) until you scroll.
  const atHeroTop = isHome && !scrolled;

  return (
    <header
      className={cn(
        "sticky top-0 z-50 transition-colors duration-300",
        atHeroTop ? "border-b border-transparent bg-transparent" : "border-b border-ink-100 bg-white/85 backdrop-blur-xl",
      )}
    >
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 sm:px-6">
        <Logo />
        <div className={cn("mx-auto hidden w-full max-w-xl md:block", atHeroTop && "md:invisible")}>
          <SearchBar />
        </div>
        <nav className="ml-auto flex items-center gap-1">
          <IconLink to="/wishlist" label="Wishlist">
            <Heart className="size-5" />
          </IconLink>
          <IconLink to="/alerts" label="Price alerts">
            <Bell className="size-5" />
          </IconLink>
          <AccountMenu />
        </nav>
      </div>
      {!isHome && (
        <div className="px-4 pb-3 md:hidden">
          <SearchBar />
        </div>
      )}
    </header>
  );
}

function IconLink({ to, label, children }: { to: string; label: string; children: ReactNode }) {
  return (
    <NavLink
      to={to}
      title={label}
      aria-label={label}
      className={({ isActive }) =>
        cn(
          "grid size-10 place-items-center rounded-xl transition",
          "text-ink-500 hover:bg-ink-100 hover:text-ink-900",
          isActive && "bg-brand-50 text-brand-600",
        )
      }
    >
      {children}
    </NavLink>
  );
}

function AccountMenu() {
  const { user, logout } = useAuth();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { pathname } = useLocation();

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  if (!user) {
    return (
      <ButtonLink to="/login" size="sm" variant="primary" className="ml-2">
        Sign in
      </ButtonLink>
    );
  }

  const name = displayName(user);
  return (
    <div ref={ref} className="relative ml-1">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
        className={cn(
          "flex items-center gap-2 rounded-xl py-1.5 pr-2 pl-1.5 text-ink-800 transition hover:bg-ink-100",
        )}
      >
        <span className="bg-gradient-brand grid size-8 place-items-center rounded-lg text-sm font-bold text-white uppercase">
          {/^[a-z]/i.test(name) ? name[0] : <UserIcon className="size-4" />}
        </span>
        <span className="hidden max-w-28 truncate text-sm font-semibold sm:block">{name}</span>
        <ChevronDown className="size-4 opacity-60" />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 mt-2 w-60 origin-top-right animate-scale-in rounded-2xl border border-ink-100 bg-white p-2 shadow-lift">
          <div className="border-b border-ink-100 px-3 pt-2 pb-3">
            <p className="truncate text-sm font-semibold text-ink-900">{name}</p>
            <p className="truncate text-xs text-ink-500">{user.email ?? user.phone}</p>
          </div>
          <MenuLink to="/wishlist" icon={<Heart className="size-4" />}>Wishlist</MenuLink>
          <MenuLink to="/alerts" icon={<Bell className="size-4" />}>Price alerts</MenuLink>
          <MenuLink to="/history" icon={<History className="size-4" />}>Search history</MenuLink>
          <button
            role="menuitem"
            onClick={async () => {
              await logout();
              toast({ tone: "success", title: "Signed out" });
            }}
            className="mt-1 flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm text-ink-600 hover:bg-ink-100 hover:text-ink-900"
          >
            <LogOut className="size-4" /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

function MenuLink({ to, icon, children }: { to: string; icon: ReactNode; children: ReactNode }) {
  return (
    <Link role="menuitem" to={to} className="flex items-center gap-3 rounded-xl px-3 py-2 text-sm text-ink-600 hover:bg-ink-100 hover:text-ink-900">
      {icon}
      {children}
    </Link>
  );
}

