import pytest

from app.adapters.urls import url_problem

AMAZON = frozenset({"www.amazon.in", "amazon.in"})


@pytest.mark.parametrize(
    "url",
    [
        "https://www.amazon.in/dp/B0CHX1W1XY",
        "https://amazon.in/s?k=iphone+15",
        "https://WWW.AMAZON.IN/dp/B0CHX1W1XY",  # hostnames are case-insensitive
        "https://www.amazon.in:443/dp/B0CHX1W1XY",
        "https://www.amazon.in/dp/X?tag=shopsync-21&ref=abc",
    ],
)
def test_accepts_store_urls(url: str) -> None:
    assert url_problem(url, AMAZON) is None


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://www.amazon.in/dp/X", "url_not_https"),
        ("javascript:alert(1)", "url_not_https"),
        ("//www.amazon.in/dp/X", "url_not_https"),
        # deceptive hosts / subdomains
        ("https://amazon.in.evil.com/dp/X", "url_host_not_allowed"),
        ("https://evil-amazon.in/dp/X", "url_host_not_allowed"),
        ("https://images.amazon.in/dp/X", "url_host_not_allowed"),
        ("https://www.amazon.in.evil.com/", "url_host_not_allowed"),
        ("https://www.amazon.in./dp/X", "url_trailing_dot"),
        # Cyrillic "a" (U+0430) homograph of www.amazon.in
        ("https://www.\u0430mazon.in/dp/X", "url_non_ascii_host"),
        # credential / parser tricks
        ("https://www.amazon.in@evil.com/", "url_has_credentials"),
        ("https://user:pass@www.amazon.in/", "url_has_credentials"),
        ("https://www.amazon.in:8443/dp/X", "url_bad_port"),
        ("https://www.amazon.in:99999/", "url_unparseable"),
        ("https://www.amazon.in\\@evil.com/", "url_bad_characters"),
        ("https://www.amazon.in/dp/X Y", "url_bad_characters"),
        ("https://www.amazon.in/\x00", "url_bad_characters"),
        # open-redirect payloads on an allowed host
        ("https://www.amazon.in/redirect?url=https://evil.com", "url_embedded_redirect"),
        ("https://www.amazon.in/r?to=%2F%2Fevil.com", "url_embedded_redirect"),
        ("https://www.amazon.in/r?to=https%3A%2F%2Fevil.com", "url_embedded_redirect"),
        ("https://www.amazon.in/dp/X#https://evil.com", "url_embedded_redirect"),
        ("https://" + "a" * 2050, "url_too_long"),
    ],
)
def test_rejects_unsafe_urls(url: str, reason: str) -> None:
    assert url_problem(url, AMAZON) == reason


def test_structural_check_without_allowlist() -> None:
    assert url_problem("https://cdn.example.com/img.jpg") is None
    assert url_problem("http://cdn.example.com/img.jpg") == "url_not_https"


# --------------------------------------------------------------------------- #
# A2: redirect bypasses that the first version let through
# --------------------------------------------------------------------------- #
REDIRECT_BYPASSES = {
    # double / triple percent-encoding
    "double-encoded scheme": "https://www.amazon.in/r?u=https%253A%252F%252Fevil.com",
    "triple-encoded scheme": "https://www.amazon.in/r?u=https%25253A%25252F%25252Fevil.com",
    "double-encoded //": "https://www.amazon.in/r?u=%252F%252Fevil.com",
    "double-encoded fragment": "https://www.amazon.in/dp/X#https%253A%252F%252Fevil.com",
    # redirect URLs embedded in the path
    "path absolute URL": "https://www.amazon.in/gp/redirect/https://evil.com",
    "path encoded absolute URL": "https://www.amazon.in/gp/redirect/https%3A%2F%2Fevil.com",
    "path double-encoded URL": "https://www.amazon.in/gp/redirect/https%253A%252F%252Fevil.com",
    "path protocol-relative": "https://www.amazon.in//evil.com/",
    "path encoded //": "https://www.amazon.in/r/%2F%2Fevil.com",
    # encoded slash/backslash combinations (browsers normalise \ to /)
    "query /\\ encoded": "https://www.amazon.in/r?u=%2F%5Cevil.com",
    "query \\/ encoded": "https://www.amazon.in/r?u=%5C%2Fevil.com",
    "query \\\\ encoded": "https://www.amazon.in/r?u=%5C%5Cevil.com",
    "query /\\ double-encoded": "https://www.amazon.in/r?u=%252F%255Cevil.com",
    "path encoded backslash": "https://www.amazon.in/%5Cevil.com",
    "path /\\ encoded": "https://www.amazon.in/r/%2F%5Cevil.com",
    # dangerous schemes in parameters
    "javascript param": "https://www.amazon.in/r?u=javascript:alert(1)",
    "data param": "https://www.amazon.in/r?u=data:text/html,x",
}


@pytest.mark.parametrize("url", REDIRECT_BYPASSES.values(), ids=REDIRECT_BYPASSES.keys())
def test_rejects_redirect_bypasses(url: str) -> None:
    assert url_problem(url, AMAZON) == "url_embedded_redirect"


LEGITIMATE_STORE_URLS = {
    "amazon product": "https://www.amazon.in/Apple-iPhone-15-128-GB/dp/B0CHX1W1XY/ref=sr_1_1"
    "?crid=2X9&keywords=iphone%2015&qid=1700000000&sr=8-1",
    "amazon search with encoded slash in term": "https://www.amazon.in/s?k=t%2Fshirt",
    "amazon single leading slash value": "https://www.amazon.in/s?k=%2Fshirt",
    "amazon affiliate tag": "https://www.amazon.in/dp/B0CHX1W1XY?tag=shopsync-21&linkCode=ll1",
    "myntra demo path": "https://www.myntra.com/Nike+Air+Max+SC+Men%27s+Sneakers",
    "flipkart product": "https://www.flipkart.com/apple-iphone-15-black-128-gb/p/itm6ac6485515ae4"
    "?pid=MOBGTAGPTB3VS24W&lid=LSTMOBGTAGPTB3VS24WKFODHL&marketplace=FLIPKART",
    "flipkart affiliate deep link": "https://dl.flipkart.com/dl/apple-iphone-15/p/itm6ac?affid=abc",
    "encoded spaces and plus": "https://www.amazon.in/s?k=levi%27s+511%20jeans",
}
STORE_HOSTS = AMAZON | {"www.myntra.com", "www.flipkart.com", "dl.flipkart.com"}


@pytest.mark.parametrize("url", LEGITIMATE_STORE_URLS.values(), ids=LEGITIMATE_STORE_URLS.keys())
def test_legitimate_store_urls_still_accepted(url: str) -> None:
    assert url_problem(url, STORE_HOSTS) is None
