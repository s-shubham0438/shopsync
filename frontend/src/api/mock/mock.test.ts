import { describe, expect, it } from "vitest";

import { PRODUCTS } from "./data";
import { buildHistory, searchProducts } from "./index";

describe("mock catalogue", () => {
  it("flags exactly one in-stock best deal per product, at the lowest in-stock price", () => {
    for (const p of PRODUCTS) {
      const best = p.listings.filter((l) => l.is_best_deal);
      expect(best).toHaveLength(1);
      expect(best[0]!.in_stock).toBe(true);
      const cheapest = Math.min(...p.listings.filter((l) => l.in_stock).map((l) => l.current_price));
      expect(best[0]!.current_price).toBe(cheapest);
      expect(p.best_price).toBe(cheapest);
    }
  });

  it("stores all money as integer paise", () => {
    for (const p of PRODUCTS) for (const l of p.listings) expect(Number.isInteger(l.current_price)).toBe(true);
  });
});

describe("searchProducts", () => {
  it("matches category synonyms", () => {
    const res = searchProducts({ q: "phone" });
    expect(res.items.length).toBeGreaterThan(0);
    expect(res.items.every((p) => p.category?.slug === "mobiles")).toBe(true);
  });

  it("requires every word to match", () => {
    expect(searchProducts({ q: "apple watch" }).items.map((p) => p.id)).toContain("apple-watch-se-2-40");
    expect(searchProducts({ q: "apple sneakers" }).total).toBe(0);
  });

  it("filters by parent category and price range (paise)", () => {
    const res = searchProducts({ q: "", category: "fashion", max_price: 200000 });
    expect(res.total).toBeGreaterThan(0);
    for (const p of res.items) expect(p.best_price).toBeLessThanOrEqual(200000);
  });

  it("sorts by price", () => {
    const prices = searchProducts({ q: "", sort: "price_asc" }).items.map((p) => p.best_price);
    expect(prices).toEqual([...prices].sort((a, b) => a - b));
  });

  it("paginates", () => {
    const page1 = searchProducts({ q: "", page: 1 });
    const page2 = searchProducts({ q: "", page: 2 });
    expect(page1.pages).toBe(2);
    expect(page2.items[0]!.id).not.toBe(page1.items[0]!.id);
  });
});

describe("buildHistory", () => {
  it("is deterministic and ends at today's price", () => {
    const product = PRODUCTS[0]!;
    const a = buildHistory(product, 30);
    const b = buildHistory(product, 30);
    expect(a).toEqual(b);
    for (const s of a.series) {
      expect(s.points).toHaveLength(31);
      const listing = product.listings.find((l) => l.id === s.listing_id)!;
      expect(s.points.at(-1)!.price).toBe(listing.current_price);
    }
  });
});
