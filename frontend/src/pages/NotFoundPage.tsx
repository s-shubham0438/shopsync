import { Compass } from "lucide-react";

import { SearchBar } from "@/components/SearchBar";
import { ButtonLink } from "@/components/ui/Button";

export function NotFoundPage() {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center px-4 py-24 text-center">
      <div className="bg-gradient-brand grid size-16 place-items-center rounded-2xl text-white shadow-glow">
        <Compass className="size-8" />
      </div>
      <p className="mt-8 font-display text-7xl font-bold text-ink-200">404</p>
      <h1 className="mt-2 font-display text-3xl font-bold">This page went out of stock</h1>
      <p className="mt-3 text-ink-500">The link may be broken or the page may have moved. Try searching instead.</p>
      <div className="mt-8 w-full">
        <SearchBar />
      </div>
      <ButtonLink to="/" variant="secondary" className="mt-4">
        Back to home
      </ButtonLink>
    </div>
  );
}
