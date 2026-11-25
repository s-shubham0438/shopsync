"""The stores ShopSync knows about: one source of truth for slugs, names and trusted hosts.

`allowed_hosts` is an exact-match allowlist (no suffix/wildcard matching), so look-alikes such as
`amazon.in.evil.com` or `evil-amazon.in` can never pass as a store link.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StoreInfo:
    slug: str
    name: str
    base_url: str
    allowed_hosts: frozenset[str]


STORES: tuple[StoreInfo, ...] = (
    StoreInfo(
        "amazon", "Amazon", "https://www.amazon.in", frozenset({"www.amazon.in", "amazon.in"})
    ),
    StoreInfo(
        "flipkart",
        "Flipkart",
        "https://www.flipkart.com",
        frozenset({"www.flipkart.com", "flipkart.com", "dl.flipkart.com"}),
    ),
    StoreInfo(
        "myntra", "Myntra", "https://www.myntra.com", frozenset({"www.myntra.com", "myntra.com"})
    ),
    StoreInfo("ajio", "Ajio", "https://www.ajio.com", frozenset({"www.ajio.com", "ajio.com"})),
    StoreInfo("croma", "Croma", "https://www.croma.com", frozenset({"www.croma.com", "croma.com"})),
    StoreInfo(
        "tatacliq",
        "Tata CLiQ",
        "https://www.tatacliq.com",
        frozenset({"www.tatacliq.com", "tatacliq.com"}),
    ),
)

STORES_BY_SLUG: dict[str, StoreInfo] = {s.slug: s for s in STORES}
