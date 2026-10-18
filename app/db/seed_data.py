"""Development seed catalogue (mirrors the frontend's demo data so both modes look the same).

Prices are in whole rupees here for readability; the seeder converts them to paise.
"""

from dataclasses import dataclass, field
from typing import Any

type JSONScalar = str | int | float | bool


@dataclass(frozen=True, slots=True)
class PlatformSeed:
    slug: str
    name: str
    base_url: str


@dataclass(frozen=True, slots=True)
class CategorySeed:
    slug: str
    name: str
    parent: str | None = None


@dataclass(frozen=True, slots=True)
class ProductSeed:
    key: str  # stable id used to build listing external_ids (idempotent seeding)
    title: str
    brand: str
    category: str
    mrp: int  # rupees
    rating: float
    reviews: int
    prices: dict[str, int]  # platform slug -> rupees
    attributes: dict[str, JSONScalar]
    model: str | None = None
    ean: str | None = None
    out_of_stock: frozenset[str] = field(default_factory=frozenset)


PLATFORMS: list[PlatformSeed] = [
    PlatformSeed("amazon", "Amazon", "https://www.amazon.in"),
    PlatformSeed("flipkart", "Flipkart", "https://www.flipkart.com"),
    PlatformSeed("myntra", "Myntra", "https://www.myntra.com"),
    PlatformSeed("ajio", "Ajio", "https://www.ajio.com"),
    PlatformSeed("croma", "Croma", "https://www.croma.com"),
    PlatformSeed("tatacliq", "Tata CLiQ", "https://www.tatacliq.com"),
]

CATEGORIES: list[CategorySeed] = [
    CategorySeed("electronics", "Electronics"),
    CategorySeed("mobiles", "Mobiles", "electronics"),
    CategorySeed("audio", "Audio", "electronics"),
    CategorySeed("wearables", "Wearables", "electronics"),
    CategorySeed("laptops", "Laptops", "electronics"),
    CategorySeed("fashion", "Fashion"),
    CategorySeed("clothing", "Clothing", "fashion"),
    CategorySeed("footwear", "Footwear", "fashion"),
    CategorySeed("bags", "Bags & Luggage"),
]

OFFERS: dict[str, list[dict[str, Any]]] = {
    "amazon": [
        {
            "type": "bank",
            "title": "10% instant discount on HDFC Bank cards",
            "description": "Up to ₹1,500 on orders above ₹5,000",
        },
        {
            "type": "cashback",
            "title": "5% cashback with Amazon Pay ICICI card",
            "description": "Unlimited cashback for Prime members",
        },
        {"type": "emi", "title": "No-cost EMI available"},
    ],
    "flipkart": [
        {"type": "bank", "title": "5% unlimited cashback on Flipkart Axis Bank card"},
        {"type": "bank", "title": "₹1,000 off on SBI credit card EMI"},
        {"type": "exchange", "title": "Up to ₹15,000 off on exchange"},
    ],
    "myntra": [
        {
            "type": "coupon",
            "title": "Extra 10% off with code MYNTRA10",
            "description": "On orders above ₹1,499",
        },
        {"type": "bank", "title": "10% instant discount on Kotak cards"},
    ],
    "ajio": [
        {
            "type": "coupon",
            "title": "Flat ₹300 off with code AJIO300",
            "description": "On orders above ₹1,990",
        },
        {"type": "bank", "title": "10% off on IDFC FIRST Bank cards"},
    ],
    "croma": [
        {"type": "bank", "title": "₹2,000 instant discount on ICICI Bank cards"},
        {"type": "emi", "title": "No-cost EMI up to 9 months"},
    ],
    "tatacliq": [
        {"type": "coupon", "title": "Extra 5% off on first order with code CLIQ5"},
        {"type": "bank", "title": "7.5% off on RBL Bank cards"},
    ],
}

DELIVERY: dict[str, str] = {
    "amazon": "Free delivery tomorrow",
    "flipkart": "Free delivery in 2 days",
    "myntra": "Delivery in 3–5 days",
    "ajio": "Delivery in 4–6 days",
    "croma": "Store pickup today · Delivery in 2 days",
    "tatacliq": "Delivery in 3–4 days",
}

PRODUCTS: list[ProductSeed] = [
    ProductSeed(
        "iphone-15-128-black",
        "Apple iPhone 15 (128 GB) – Black",
        "Apple",
        "mobiles",
        69900,
        4.6,
        48210,
        {"amazon": 61999, "flipkart": 59999, "croma": 62490, "tatacliq": 62990},
        {
            "Storage": "128 GB",
            "Display": '6.1" Super Retina XDR',
            "Chip": "A16 Bionic",
            "Camera": "48 MP + 12 MP",
            "Colour": "Black",
        },
        model="MTP03HN/A",
        ean="0195949035470",
    ),
    ProductSeed(
        "galaxy-s24-fe-8-128",
        "Samsung Galaxy S24 FE 5G (8 GB RAM, 128 GB) – Graphite",
        "Samsung",
        "mobiles",
        59999,
        4.4,
        18934,
        {"amazon": 35999, "flipkart": 34999, "croma": 36490},
        {
            "RAM": "8 GB",
            "Storage": "128 GB",
            "Display": '6.7" Dynamic AMOLED 2X, 120Hz',
            "Processor": "Exynos 2400e",
            "Battery": "4700 mAh",
        },
        model="SM-S721B",
    ),
    ProductSeed(
        "pixel-9a-128",
        "Google Pixel 9a (8 GB RAM, 128 GB) – Obsidian",
        "Google",
        "mobiles",
        49999,
        4.5,
        6120,
        {"flipkart": 44999, "croma": 46999, "amazon": 45999},
        {
            "RAM": "8 GB",
            "Storage": "128 GB",
            "Display": '6.3" Actua pOLED, 120Hz',
            "Chip": "Google Tensor G4",
            "Battery": "5100 mAh",
        },
        model="GA05774-IN",
    ),
    ProductSeed(
        "nord-ce4-lite-8-128",
        "OnePlus Nord CE4 Lite 5G (8 GB RAM, 128 GB) – Super Silver",
        "OnePlus",
        "mobiles",
        20999,
        4.3,
        31255,
        {"amazon": 17999, "flipkart": 18499, "croma": 18299},
        {
            "RAM": "8 GB",
            "Storage": "128 GB",
            "Display": '6.67" AMOLED, 120Hz',
            "Processor": "Snapdragon 695",
            "Battery": "5500 mAh",
        },
        model="CPH2619",
    ),
    ProductSeed(
        "sony-wh1000xm5",
        "Sony WH-1000XM5 Wireless Noise Cancelling Headphones – Black",
        "Sony",
        "audio",
        34990,
        4.5,
        12877,
        {"amazon": 26990, "flipkart": 27490, "croma": 25990, "tatacliq": 27990},
        {
            "Type": "Over-ear",
            "Noise cancellation": "Active (ANC)",
            "Battery": "Up to 30 hours",
            "Connectivity": "Bluetooth 5.2, multipoint",
        },
        model="WH-1000XM5/B",
        ean="4548736132610",
    ),
    ProductSeed(
        "airpods-pro-2-usbc",
        "Apple AirPods Pro (2nd generation) with MagSafe Case (USB-C)",
        "Apple",
        "audio",
        24900,
        4.6,
        22410,
        {"amazon": 19990, "flipkart": 19499, "croma": 20490},
        {
            "Type": "In-ear (TWS)",
            "Noise cancellation": "Active (ANC)",
            "Chip": "H2",
            "Battery": "Up to 30 hours with case",
        },
        model="MTJV3HN/A",
    ),
    ProductSeed(
        "boat-airdopes-141-anc",
        "boAt Airdopes 141 ANC TWS Earbuds with 42H Playtime",
        "boAt",
        "audio",
        4490,
        4.0,
        95412,
        {"amazon": 1299, "flipkart": 1199, "myntra": 1349},
        {
            "Type": "In-ear (TWS)",
            "Noise cancellation": "ANC up to 32 dB",
            "Battery": "Up to 42 hours",
            "Water resistance": "IPX5",
        },
        model="Airdopes 141 ANC",
    ),
    ProductSeed(
        "jbl-flip-6",
        "JBL Flip 6 Portable Waterproof Bluetooth Speaker – Blue",
        "JBL",
        "audio",
        13999,
        4.5,
        14023,
        {"amazon": 8999, "flipkart": 9499, "croma": 9299},
        {
            "Type": "Portable speaker",
            "Output": "30 W",
            "Battery": "Up to 12 hours",
            "Water resistance": "IP67",
        },
        model="JBLFLIP6BLU",
        out_of_stock=frozenset({"croma"}),
    ),
    ProductSeed(
        "noise-colorfit-pro-6-max",
        'Noise ColorFit Pro 6 Max Smartwatch with 1.96" AMOLED Display',
        "Noise",
        "wearables",
        9999,
        4.1,
        8840,
        {"amazon": 4999, "flipkart": 4799, "myntra": 5199},
        {
            "Display": '1.96" AMOLED',
            "Calling": "Bluetooth calling",
            "Battery": "Up to 7 days",
            "Water resistance": "IP68",
        },
    ),
    ProductSeed(
        "apple-watch-se-2-40",
        "Apple Watch SE (2nd Gen, GPS, 40mm) – Midnight Aluminium",
        "Apple",
        "wearables",
        29900,
        4.6,
        9310,
        {"amazon": 22900, "flipkart": 21999, "croma": 23490},
        {
            "Size": "40 mm",
            "Connectivity": "GPS",
            "Sensors": "Heart rate, crash detection",
            "Water resistance": "50 m",
        },
        model="MR9X3HN/A",
    ),
    ProductSeed(
        "macbook-air-m3-13",
        'Apple MacBook Air 13" M3 (8 GB RAM, 256 GB SSD) – Midnight',
        "Apple",
        "laptops",
        114900,
        4.7,
        5122,
        {"amazon": 94990, "flipkart": 92990, "croma": 96990, "tatacliq": 95490},
        {
            "Chip": "Apple M3 (8-core CPU)",
            "RAM": "8 GB",
            "Storage": "256 GB SSD",
            "Display": '13.6" Liquid Retina',
            "Weight": "1.24 kg",
        },
        model="MRXV3HN/A",
    ),
    ProductSeed(
        "nike-air-max-sc",
        "Nike Air Max SC Men's Sneakers – White/Black",
        "Nike",
        "footwear",
        6495,
        4.4,
        3219,
        {"myntra": 4871, "ajio": 5196, "amazon": 5099, "tatacliq": 4999},
        {"Gender": "Men", "Material": "Leather & mesh", "Sole": "Rubber", "Closure": "Lace-up"},
        model="CW4555-102",
    ),
    ProductSeed(
        "adidas-ultraboost-light",
        "Adidas Ultraboost Light Men's Running Shoes – Core Black",
        "Adidas",
        "footwear",
        18999,
        4.5,
        2210,
        {"myntra": 11399, "ajio": 12349, "amazon": 11999},
        {"Gender": "Men", "Use": "Running", "Midsole": "Light BOOST", "Upper": "Primeknit+"},
        model="GY9351",
    ),
    ProductSeed(
        "puma-smash-v2",
        "Puma Smash v2 Unisex Sneakers – White",
        "Puma",
        "footwear",
        4999,
        4.2,
        17602,
        {"myntra": 1999, "ajio": 2249, "amazon": 2099, "flipkart": 2149},
        {
            "Gender": "Unisex",
            "Material": "Synthetic leather",
            "Sole": "Rubber",
            "Closure": "Lace-up",
        },
        model="365215-01",
    ),
    ProductSeed(
        "levis-511-slim",
        "Levi's Men's 511 Slim Fit Mid-Rise Jeans – Dark Indigo",
        "Levi's",
        "clothing",
        3599,
        4.3,
        11054,
        {"myntra": 1799, "ajio": 1979, "amazon": 1899, "flipkart": 1849},
        {"Fit": "Slim", "Rise": "Mid-rise", "Fabric": "Cotton blend with stretch", "Wash": "Dark"},
        model="18298-1080",
    ),
    ProductSeed(
        "allen-solly-polo",
        "Allen Solly Men's Regular Fit Solid Polo T-Shirt – Navy",
        "Allen Solly",
        "clothing",
        1499,
        4.1,
        24871,
        {"myntra": 749, "ajio": 824, "amazon": 779, "flipkart": 799},
        {"Fit": "Regular", "Fabric": "100% cotton pique", "Sleeve": "Short", "Neck": "Polo collar"},
    ),
    ProductSeed(
        "uspa-cotton-shirt",
        "U.S. Polo Assn. Men's Slim Fit Cotton Casual Shirt – Sky Blue",
        "U.S. Polo Assn.",
        "clothing",
        2299,
        4.2,
        6402,
        {"myntra": 1149, "ajio": 1092, "amazon": 1199},
        {"Fit": "Slim", "Fabric": "100% cotton", "Sleeve": "Full", "Pattern": "Solid"},
    ),
    ProductSeed(
        "american-tourister-valex-28l",
        "American Tourister Valex 28L Laptop Backpack – Black",
        "American Tourister",
        "bags",
        3850,
        4.3,
        52317,
        {"amazon": 1599, "flipkart": 1649, "myntra": 1699, "ajio": 1729},
        {
            "Capacity": "28 L",
            "Laptop sleeve": 'Up to 15.6"',
            "Material": "Polyester",
            "Water resistant": True,
        },
    ),
    ProductSeed(
        "wildcraft-trailblazer-45l",
        "Wildcraft Trailblazer 45L Rucksack – Olive",
        "Wildcraft",
        "bags",
        3999,
        4.2,
        4580,
        {"amazon": 2399, "flipkart": 2299, "myntra": 2499},
        {
            "Capacity": "45 L",
            "Use": "Trekking & travel",
            "Rain cover": True,
            "Material": "Polyester",
        },
    ),
    ProductSeed(
        "safari-pentagon-65",
        "Safari Pentagon 65 cm Medium Hard-Sided Trolley Bag – Midnight Blue",
        "Safari",
        "bags",
        8800,
        4.1,
        13208,
        {"amazon": 3299, "flipkart": 3199, "ajio": 3499},
        {
            "Size": "65 cm (Medium)",
            "Shell": "Polypropylene",
            "Wheels": "4 spinner",
            "Lock": "TSA number lock",
        },
    ),
]
