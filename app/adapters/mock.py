"""Mock store adapter: realistic demo data for one store, from the shared seed catalogue.

One instance per store, so the runner's parallelism, timeouts and failure isolation are exercised
exactly as they will be with real APIs. Records match the seeded database rows (same external ids,
prices, ratings), so search results line up with stored listings.
"""

import asyncio
import random
import re

from app.adapters.base import AdapterUnavailableError, StoreAdapter
from app.adapters.schemas import Offer, StoreListing, StoreSearchQuery
from app.core.stores import StoreInfo
from app.db.seed_data import (
    CATEGORIES,
    DELIVERY,
    OFFERS,
    PRODUCTS,
    ProductSeed,
    listing_external_id,
    listing_rating,
    listing_review_count,
    store_search_url,
)

# Everyday words people type that should hit a category ("phone" → Mobiles).
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "mobiles": ("phone", "phones", "mobile", "smartphone", "5g"),
    "audio": ("headphones", "earbuds", "earphones", "tws", "speaker", "audio"),
    "wearables": ("watch", "smartwatch", "band", "wearable"),
    "laptops": ("laptop", "notebook", "macbook"),
    "clothing": ("clothes", "shirt", "tshirt", "t-shirt", "jeans", "polo", "apparel"),
    "footwear": ("shoes", "shoe", "sneakers", "running", "footwear"),
    "bags": ("bag", "bags", "backpack", "luggage", "trolley", "suitcase", "rucksack"),
}

_PARENT = {c.slug: c.parent for c in CATEGORIES}
_CATEGORY_NAME = {c.slug: c.name for c in CATEGORIES}
_WORD = re.compile(r"[a-z0-9+'.]+")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _search_words(product: ProductSeed) -> list[str]:
    parent = _PARENT.get(product.category)
    parts = [
        product.title,
        product.brand,
        _CATEGORY_NAME.get(product.category, ""),
        _CATEGORY_NAME.get(parent, "") if parent else "",
        " ".join(CATEGORY_KEYWORDS.get(product.category, ())),
        " ".join(str(v) for v in product.attributes.values()),
    ]
    return _words(" ".join(parts))


def _relevance(product: ProductSeed, tokens: list[str]) -> int | None:
    """Every query word must prefix-match some word ("phone" hits phones, not headphones)."""
    haystack, title = _search_words(product), _words(product.title)
    score = 0
    for token in tokens:
        if not any(w.startswith(token) for w in haystack):
            return None
        score += 3 if any(w.startswith(token) for w in title) else 1
        if product.brand.lower() == token:
            score += 2
    return score


def _in_category(product: ProductSeed, slug: str) -> bool:
    return product.category == slug or _PARENT.get(product.category) == slug


class MockStoreAdapter(StoreAdapter):
    mode = "mock"

    def __init__(
        self,
        store: StoreInfo,
        *,
        latency_ms: int = 150,
        failure_rate: float = 0.0,
        catalogue: tuple[ProductSeed, ...] | list[ProductSeed] = PRODUCTS,
        rng: random.Random | None = None,
    ) -> None:
        super().__init__(store)
        if not 0.0 <= failure_rate <= 1.0:
            raise ValueError("failure_rate must be between 0 and 1")
        self.latency_ms = latency_ms
        self.failure_rate = failure_rate
        # Only for simulated latency/outages; not security-sensitive.
        self._rng = rng or random.Random()  # noqa: S311
        # This store's slice of the catalogue, in a stable order.
        self._products = [p for p in catalogue if store.slug in p.prices]

    async def _simulate_network(self) -> None:
        if self.latency_ms:
            jitter = 0.7 + self._rng.random() * 0.6  # ±30%
            await asyncio.sleep(self.latency_ms * jitter / 1000)
        if self.failure_rate and self._rng.random() < self.failure_rate:
            raise AdapterUnavailableError("simulated store outage")

    def _to_listing(self, product: ProductSeed) -> StoreListing:
        slug = self.platform_slug
        index = list(product.prices).index(slug)
        return StoreListing(
            platform_slug=slug,
            external_id=listing_external_id(product, slug),
            title=product.title,
            url=store_search_url(self.store.base_url, slug, product.title),
            price=product.prices[slug] * 100,
            mrp=product.mrp * 100,
            in_stock=slug not in product.out_of_stock,
            rating=listing_rating(product, index),
            review_count=listing_review_count(product, index),
            offers=tuple(Offer.model_validate(o) for o in OFFERS.get(slug, [])),
            delivery_info=DELIVERY.get(slug),
            brand=product.brand,
            model_number=product.model,
            ean=product.ean,
            category_hint=product.category,
            attributes=dict(product.attributes),
        )

    async def search(self, query: StoreSearchQuery) -> list[StoreListing]:
        await self._simulate_network()
        tokens = _words(query.text)
        if not tokens:  # e.g. "!!": nothing searchable
            return []
        scored: list[tuple[int, int, ProductSeed]] = []
        for position, product in enumerate(self._products):
            price = product.prices[self.platform_slug] * 100
            if query.category_slug and not _in_category(product, query.category_slug):
                continue
            if query.min_price is not None and price < query.min_price:
                continue
            if query.max_price is not None and price > query.max_price:
                continue
            score = _relevance(product, tokens)
            if score is not None:
                scored.append((-score, position, product))
        scored.sort(key=lambda item: item[:2])  # best score first, catalogue order breaks ties
        return [self._to_listing(p) for _, _, p in scored[: query.limit]]

    async def get_product(self, external_id: str) -> StoreListing | None:
        await self._simulate_network()
        for product in self._products:
            if listing_external_id(product, self.platform_slug) == external_id:
                return self._to_listing(product)
        return None
