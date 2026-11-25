import {
  ArrowRight,
  BadgePercent,
  BellRing,
  ChartLine,
  Check,
  Search,
  ShieldCheck,
  Sparkles,
  Store,
  TrendingDown,
} from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { Link } from "react-router";

import type { Platform } from "@/api";
import { PLATFORMS, PRODUCTS } from "@/api/mock/data";
import { useAuth } from "@/auth/AuthProvider";
import { CursorCat } from "@/components/cat/CursorCat";
import { categoryLook } from "@/components/product/ProductImage";
import { ProductCard, ProductCardSkeleton } from "@/components/product/ProductCard";
import { StoreBadge } from "@/components/product/StoreBadge";
import { SearchBar } from "@/components/SearchBar";
import { ButtonLink } from "@/components/ui/Button";
import { CountUp, Reveal } from "@/components/ui/Reveal";
import { useDeals, usePlatforms } from "@/hooks/queries";
import { formatPrice } from "@/lib/format";

const POPULAR = ["iPhone 15", "Sony headphones", "Nike sneakers", "Levi's jeans", "Backpack", "Smartwatch"];

const CATEGORY_TILES = [
  { slug: "mobiles", name: "Mobiles", q: "phone" },
  { slug: "audio", name: "Audio", q: "headphones" },
  { slug: "wearables", name: "Smartwatches", q: "watch" },
  { slug: "laptops", name: "Laptops", q: "laptop" },
  { slug: "footwear", name: "Footwear", q: "shoes" },
  { slug: "clothing", name: "Clothing", q: "clothes" },
  { slug: "bags", name: "Bags & Luggage", q: "bag" },
];

/** Inline style for staggered keyframe animations. */
const delay = (ms: number): CSSProperties => ({ animationDelay: `${ms}ms` });

export function HomePage() {
  return (
    <>
      <Hero />
      <StoreStrip />
      <Categories />
      <Deals />
      <HowItWorks />
      <AlertsCta />
    </>
  );
}

/* ------------------------------------------------------------------ Hero -- */

function Hero() {
  return (
    <section className="relative isolate overflow-hidden bg-linear-to-b from-brand-100/80 via-brand-50 to-surface">
      <div className="bg-grid-light absolute inset-0 -z-10 [mask-image:radial-gradient(ellipse_at_top,black_25%,transparent_70%)]" />
      <div className="absolute -top-48 left-1/3 -z-10 h-[480px] w-[760px] -translate-x-1/2 animate-blob rounded-full bg-brand-200/60 blur-[120px]" />
      <div className="absolute top-20 -right-32 -z-10 size-[440px] animate-blob rounded-full bg-brand-300/35 blur-[110px] [animation-delay:-6s]" />
      <div className="absolute bottom-0 left-0 -z-10 size-[360px] animate-blob rounded-full bg-ink-200/50 blur-[100px] [animation-delay:-12s]" />

      <div className="mx-auto grid max-w-7xl items-center gap-14 px-4 pt-14 pb-44 sm:px-6 lg:grid-cols-[1.15fr_1fr] lg:pt-20 lg:pb-48">
        <div>
          <span
            className="inline-flex animate-fade-up items-center gap-2 rounded-full border border-brand-200 bg-white/80 px-3 py-1 text-xs font-medium text-ink-600 shadow-sm backdrop-blur"
            style={delay(0)}
          >
            <span className="relative flex size-2">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-deal-500 opacity-60" />
              <span className="relative inline-flex size-2 rounded-full bg-deal-500" />
            </span>
            Prices from 6 trusted Indian stores, refreshed through the day
          </span>

          <h1 className="mt-6 font-display text-5xl leading-[1.04] font-bold tracking-tight text-ink-900 sm:text-6xl lg:text-7xl">
            <span className="block animate-rise" style={delay(80)}>
              Same product.
            </span>
            <span className="block animate-rise" style={delay(220)}>
              Every store.
            </span>
            <span className="text-gradient-brand block animate-rise pb-1" style={delay(360)}>
              Best price.
            </span>
          </h1>
          <p className="mt-6 max-w-xl animate-fade-up text-lg leading-8 text-ink-500" style={delay(520)}>
            Search once and instantly compare prices, bank offers and ratings across Amazon, Flipkart, Myntra, Ajio
            and more. Stop opening ten tabs.
          </p>

          <div className="mt-9 max-w-2xl animate-fade-up" style={delay(640)}>
            <SearchBar variant="hero" />
          </div>
          <div className="mt-5 flex flex-wrap items-center gap-2">
            <span className="animate-fade-in text-sm text-ink-400" style={delay(760)}>
              Popular:
            </span>
            {POPULAR.map((q, i) => (
              <Link
                key={q}
                to={`/search?q=${encodeURIComponent(q)}`}
                style={delay(800 + i * 60)}
                className="animate-fade-up rounded-full border border-ink-200 bg-white/90 px-3 py-1 text-sm text-ink-600 shadow-sm transition hover:-translate-y-0.5 hover:border-ink-300 hover:bg-white hover:text-ink-900 hover:shadow-card"
              >
                {q}
              </Link>
            ))}
          </div>

          <dl className="mt-12 grid max-w-lg animate-fade-up grid-cols-3 gap-6 border-t border-ink-200/70 pt-8" style={delay(1000)}>
            <div>
              <dt className="font-display text-2xl font-bold text-ink-900 sm:text-3xl">
                <CountUp value={6} duration={900} />+
              </dt>
              <dd className="mt-1 text-sm text-ink-500">stores compared</dd>
            </div>
            <div>
              <dt className="font-display text-2xl font-bold text-ink-900 sm:text-3xl">
                <CountUp value={365} />
                <span className="text-lg text-ink-500"> days</span>
              </dt>
              <dd className="mt-1 text-sm text-ink-500">of price history</dd>
            </div>
            <div>
              <dt className="font-display text-2xl font-bold text-ink-900 sm:text-3xl">Free</dt>
              <dd className="mt-1 text-sm text-ink-500">price-drop alerts</dd>
            </div>
          </dl>
        </div>

        <ComparisonPreview />
      </div>

      <CursorCat />
    </section>
  );
}

/** A live-looking comparison card for the flagship demo product. */
function ComparisonPreview() {
  const product = PRODUCTS[0]!;
  const listings = product.listings.slice(0, 4);
  const best = listings[0]!;
  const highest = Math.max(...listings.map((l) => l.current_price));
  const look = categoryLook(product.category?.slug);
  const Icon = look.icon;

  return (
    <div className="relative mx-auto w-full max-w-md animate-fade-up lg:max-w-none" style={delay(400)}>
      <div className="absolute -inset-6 -z-10 animate-blob rounded-[2.5rem] bg-linear-to-tr from-brand-300/50 via-transparent to-ink-300/40 blur-2xl" />
      <div
        aria-label="Example comparison"
        className="block animate-float rounded-[1.75rem] border border-ink-100 bg-white p-5 text-ink-900 shadow-lift sm:p-6"
      >
        <div className="flex items-center gap-4">
          <div className={`grid size-16 shrink-0 place-items-center rounded-2xl bg-linear-to-br ${look.bg}`}>
            <Icon className={`size-8 ${look.fg}`} strokeWidth={1.4} />
          </div>
          <div className="min-w-0">
            <p className="text-[11px] font-semibold tracking-wider text-ink-400 uppercase">{product.brand}</p>
            <p className="truncate font-semibold">{product.canonical_title}</p>
            <p className="mt-0.5 text-xs text-ink-500">Compared across {product.store_count} stores · just now</p>
          </div>
        </div>

        <ul className="mt-5 space-y-2">
          {listings.map((l, i) => (
            <li
              key={l.id}
              style={delay(700 + i * 120)}
              className={
                l.is_best_deal
                  ? "relative flex animate-fade-up items-center gap-3 rounded-2xl border-2 border-deal-500 bg-deal-50 px-3 py-3"
                  : "flex animate-fade-up items-center gap-3 rounded-2xl border border-ink-100 px-3 py-3"
              }
            >
              <StoreBadge platform={l.platform} size="sm" />
              <span className="flex-1 text-sm font-semibold">{l.platform.name}</span>
              {l.is_best_deal && (
                <span className="gleam animate-pulse-ring rounded-full bg-deal-600 px-2 py-0.5 text-[10px] font-bold tracking-wide text-white uppercase">
                  Best deal
                </span>
              )}
              <span className={l.is_best_deal ? "font-display text-lg font-bold text-deal-700 tabular-nums" : "font-display text-lg font-semibold text-ink-700 tabular-nums"}>
                {formatPrice(l.current_price)}
              </span>
            </li>
          ))}
        </ul>

        <div className="mt-4 flex animate-fade-up items-center justify-between rounded-2xl bg-ink-900 px-4 py-3 text-brand-50" style={delay(1250)}>
          <span className="inline-flex items-center gap-2 text-sm font-medium">
            <TrendingDown className="size-4 text-deal-500" /> You save
          </span>
          <span className="font-display text-lg font-bold text-brand-300">
            <CountUp value={(highest - best.current_price) / 100} duration={1400} format={(n) => formatPrice(n * 100)} />
          </span>
        </div>
      </div>

      <div
        className="absolute -bottom-5 -left-4 hidden animate-fade-up items-center gap-2 rounded-2xl border border-ink-100 bg-white/95 px-4 py-3 text-sm font-medium text-ink-700 shadow-lift backdrop-blur sm:flex"
        style={delay(1600)}
      >
        <span className="grid size-7 place-items-center rounded-full bg-brand-100">
          <BellRing className="size-4 origin-top animate-[wiggle_1.2s_ease-in-out_2s_2] text-brand-600" />
        </span>
        Price dropped ₹1,500 on Flipkart
      </div>
    </div>
  );
}

/* ----------------------------------------------------------- Store strip -- */

function StoreStrip() {
  const { data } = usePlatforms();
  const platforms: Platform[] = data ?? PLATFORMS;
  const loop = [...platforms, ...platforms, ...platforms, ...platforms];
  return (
    <section className="border-y border-ink-100 bg-white/70 py-6 backdrop-blur" aria-label="Stores we compare">
      <div className="mx-auto flex max-w-7xl items-center gap-8 px-4 sm:px-6">
        <p className="hidden shrink-0 text-sm font-semibold text-ink-500 md:block">Comparing prices across</p>
        <div className="group relative flex-1 overflow-hidden [mask-image:linear-gradient(to_right,transparent,black_8%,black_92%,transparent)]">
          <div className="flex w-max animate-marquee gap-10 group-hover:[animation-play-state:paused]">
            {loop.map((p, i) => (
              <span key={`${p.id}-${i}`} className="flex items-center gap-2.5 text-ink-700">
                <StoreBadge platform={p} size="sm" />
                <span className="font-display text-lg font-semibold">{p.name}</span>
              </span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------ Categories -- */

function SectionHeading({ eyebrow, title, action }: { eyebrow: string; title: string; action?: ReactNode }) {
  return (
    <Reveal className="mb-8 flex items-end justify-between gap-4">
      <div>
        <p className="text-sm font-semibold tracking-wide text-brand-600 uppercase">{eyebrow}</p>
        <h2 className="mt-1 font-display text-3xl font-bold tracking-tight sm:text-4xl">{title}</h2>
      </div>
      {action}
    </Reveal>
  );
}

function Categories() {
  return (
    <section className="mx-auto max-w-7xl px-4 pt-20 sm:px-6">
      <SectionHeading eyebrow="Browse" title="Shop by category" />
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-7">
        {CATEGORY_TILES.map((c, i) => {
          const look = categoryLook(c.slug);
          const Icon = look.icon;
          return (
            <Reveal key={c.slug} delay={i * 60}>
              <Link
                to={`/search?q=${c.q}&category=${c.slug}`}
                className="group flex flex-col items-center rounded-3xl border border-ink-100 bg-white p-5 text-center shadow-card transition duration-300 hover:-translate-y-1.5 hover:border-brand-200 hover:shadow-lift"
              >
                <span className={`grid size-16 place-items-center rounded-2xl bg-linear-to-br ${look.bg} transition duration-300 group-hover:scale-110 group-hover:rotate-3`}>
                  <Icon className={`size-7 ${look.fg}`} strokeWidth={1.6} />
                </span>
                <span className="mt-3 text-sm font-semibold text-ink-800">{c.name}</span>
              </Link>
            </Reveal>
          );
        })}
      </div>
    </section>
  );
}

/* ----------------------------------------------------------------- Deals -- */

function Deals() {
  const { data, isLoading } = useDeals();
  return (
    <section className="mx-auto max-w-7xl px-4 pt-20 sm:px-6">
      <SectionHeading
        eyebrow="Biggest price gaps today"
        title="Top deals right now"
        action={
          <Link to="/search?q=&sort=discount" className="group hidden items-center gap-1 text-sm font-semibold text-ink-700 hover:text-ink-900 sm:inline-flex">
            View all <ArrowRight className="size-4 transition group-hover:translate-x-1" />
          </Link>
        }
      />
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {isLoading || !data
          ? Array.from({ length: 8 }, (_, i) => <ProductCardSkeleton key={i} />)
          : data.map((p, i) => (
              <Reveal key={p.id} delay={(i % 4) * 90}>
                <ProductCard product={p} />
              </Reveal>
            ))}
      </div>
    </section>
  );
}

/* ---------------------------------------------------------- How it works -- */

function HowItWorks() {
  const steps = [
    {
      icon: Search,
      title: "Search once",
      body: "Type what you want. We query every store in parallel and match the exact same product — by model number, barcode and specs.",
    },
    {
      icon: BadgePercent,
      title: "Compare everything",
      body: "Price, MRP, bank offers, coupons, delivery time and ratings side by side. The best deal is highlighted for you.",
    },
    {
      icon: ChartLine,
      title: "Buy at the right time",
      body: "See up to a year of price history, then set an alert. We'll tell you the moment it drops to your price.",
    },
  ];
  return (
    <section className="mx-auto max-w-7xl px-4 pt-24 sm:px-6">
      <Reveal className="overflow-hidden rounded-[2rem] border border-ink-100 bg-white p-8 shadow-card sm:p-12">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-sm font-semibold tracking-wide text-brand-600 uppercase">How ShopSync works</p>
          <h2 className="mt-1 font-display text-3xl font-bold tracking-tight sm:text-4xl">From ten tabs to one answer</h2>
        </div>
        <div className="relative mt-12 grid gap-8 md:grid-cols-3">
          <div className="absolute top-6 right-[16%] left-[16%] hidden h-px bg-linear-to-r from-transparent via-brand-300 to-transparent md:block" />
          {steps.map((s, i) => (
            <Reveal key={s.title} delay={150 + i * 150} className="relative">
              <div className="flex items-center gap-3">
                <span className="bg-gradient-brand grid size-12 place-items-center rounded-2xl text-brand-100 shadow-glow transition duration-300 hover:-rotate-6 hover:scale-110">
                  <s.icon className="size-5" />
                </span>
                <span className="font-display text-sm font-bold text-brand-400">0{i + 1}</span>
              </div>
              <h3 className="mt-5 font-display text-xl font-semibold">{s.title}</h3>
              <p className="mt-2 text-sm leading-6 text-ink-500">{s.body}</p>
            </Reveal>
          ))}
        </div>
        <div className="mt-12 flex flex-wrap justify-center gap-x-8 gap-y-3 border-t border-ink-100 pt-8 text-sm text-ink-600">
          {[
            [ShieldCheck, "Only official & trusted stores"],
            [Store, "No extra cost — you pay the store's price"],
            [Check, "Free to use, no sign-up needed to compare"],
          ].map(([Icon, text]) => {
            const I = Icon as typeof Check;
            return (
              <span key={text as string} className="inline-flex items-center gap-2">
                <I className="size-4 text-deal-600" />
                {text as string}
              </span>
            );
          })}
        </div>
      </Reveal>
    </section>
  );
}

/* ------------------------------------------------------------ Alerts CTA -- */

function AlertsCta() {
  const { user } = useAuth();
  return (
    <section className="mx-auto max-w-7xl px-4 pt-24 sm:px-6">
      <Reveal className="relative isolate overflow-hidden rounded-[2rem] bg-ink-900 px-8 py-12 sm:px-14 sm:py-16">
        <div className="absolute -top-20 -right-20 -z-10 size-80 animate-blob rounded-full bg-brand-400/25 blur-3xl" />
        <div className="absolute -bottom-24 left-1/3 -z-10 size-72 animate-blob rounded-full bg-brand-200/15 blur-3xl [animation-delay:-8s]" />
        <BellRing className="absolute top-10 right-10 hidden size-40 -rotate-12 animate-float text-brand-300/20 md:block" strokeWidth={1.2} />
        <div className="max-w-xl">
          <Sparkles className="size-6 text-brand-300" />
          <h2 className="mt-4 font-display text-3xl font-bold tracking-tight text-brand-50 sm:text-4xl">
            Never miss a <span className="text-gradient-brand">price drop.</span>
          </h2>
          <p className="mt-3 text-lg text-ink-300">
            Save products to your wishlist and set a target price. We watch every store and ping you the moment
            it's time to buy.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <ButtonLink
              to={user ? "/alerts" : "/login?mode=signup"}
              size="lg"
              variant="light"
            >
              {user ? "Manage my alerts" : "Create free account"} <ArrowRight className="size-4" />
            </ButtonLink>
          </div>
        </div>
      </Reveal>
    </section>
  );
}
