/**
 * Realistic fake catalogue used until real store adapters exist.
 * Prices are written in rupees for readability and converted to paise.
 */
import type { Category, Listing, Offer, Platform, ProductDetail, ProductSummary } from "../types";

export const PLATFORMS: Platform[] = [
  { id: "amazon", name: "Amazon", slug: "amazon", logo_url: null, base_url: "https://www.amazon.in" },
  { id: "flipkart", name: "Flipkart", slug: "flipkart", logo_url: null, base_url: "https://www.flipkart.com" },
  { id: "myntra", name: "Myntra", slug: "myntra", logo_url: null, base_url: "https://www.myntra.com" },
  { id: "ajio", name: "Ajio", slug: "ajio", logo_url: null, base_url: "https://www.ajio.com" },
  { id: "croma", name: "Croma", slug: "croma", logo_url: null, base_url: "https://www.croma.com" },
  { id: "tatacliq", name: "Tata CLiQ", slug: "tatacliq", logo_url: null, base_url: "https://www.tatacliq.com" },
];

type Slug = "amazon" | "flipkart" | "myntra" | "ajio" | "croma" | "tatacliq";
const platform = (slug: Slug) => PLATFORMS.find((p) => p.slug === slug)!;

export const CATEGORIES: Category[] = [
  { id: "c-electronics", name: "Electronics", slug: "electronics", parent_id: null },
  { id: "c-mobiles", name: "Mobiles", slug: "mobiles", parent_id: "c-electronics" },
  { id: "c-audio", name: "Audio", slug: "audio", parent_id: "c-electronics" },
  { id: "c-wearables", name: "Wearables", slug: "wearables", parent_id: "c-electronics" },
  { id: "c-laptops", name: "Laptops", slug: "laptops", parent_id: "c-electronics" },
  { id: "c-fashion", name: "Fashion", slug: "fashion", parent_id: null },
  { id: "c-clothing", name: "Clothing", slug: "clothing", parent_id: "c-fashion" },
  { id: "c-footwear", name: "Footwear", slug: "footwear", parent_id: "c-fashion" },
  { id: "c-bags", name: "Bags & Luggage", slug: "bags", parent_id: null },
];

/** Extra search words per category so "phone" or "shoes" find the right things. */
export const CATEGORY_KEYWORDS: Record<string, string[]> = {
  mobiles: ["phone", "phones", "mobile", "smartphone", "5g"],
  audio: ["headphones", "earbuds", "earphones", "tws", "speaker", "audio"],
  wearables: ["watch", "smartwatch", "band", "wearable"],
  laptops: ["laptop", "notebook", "macbook"],
  clothing: ["clothes", "shirt", "tshirt", "t-shirt", "jeans", "polo", "apparel"],
  footwear: ["shoes", "shoe", "sneakers", "running", "footwear"],
  bags: ["bag", "bags", "backpack", "luggage", "trolley", "suitcase", "rucksack"],
};

const category = (slug: string) => CATEGORIES.find((c) => c.slug === slug)!;

interface Seed {
  id: string;
  title: string;
  brand: string;
  model?: string;
  ean?: string;
  category: string;
  mrp: number;
  rating: number;
  reviews: number;
  prices: Partial<Record<Slug, number>>;
  outOfStock?: Slug[];
  attributes: Record<string, string | number | boolean>;
}

const SEEDS: Seed[] = [
  {
    id: "iphone-15-128-black",
    title: "Apple iPhone 15 (128 GB) – Black",
    brand: "Apple",
    model: "MTP03HN/A",
    ean: "0195949035470",
    category: "mobiles",
    mrp: 69900,
    rating: 4.6,
    reviews: 48210,
    prices: { amazon: 61999, flipkart: 59999, croma: 62490, tatacliq: 62990 },
    attributes: { Storage: "128 GB", Display: '6.1" Super Retina XDR', Chip: "A16 Bionic", Camera: "48 MP + 12 MP", Colour: "Black" },
  },
  {
    id: "galaxy-s24-fe-8-128",
    title: "Samsung Galaxy S24 FE 5G (8 GB RAM, 128 GB) – Graphite",
    brand: "Samsung",
    model: "SM-S721B",
    category: "mobiles",
    mrp: 59999,
    rating: 4.4,
    reviews: 18934,
    prices: { amazon: 35999, flipkart: 34999, croma: 36490 },
    attributes: { RAM: "8 GB", Storage: "128 GB", Display: '6.7" Dynamic AMOLED 2X, 120Hz', Processor: "Exynos 2400e", Battery: "4700 mAh" },
  },
  {
    id: "pixel-9a-128",
    title: "Google Pixel 9a (8 GB RAM, 128 GB) – Obsidian",
    brand: "Google",
    model: "GA05774-IN",
    category: "mobiles",
    mrp: 49999,
    rating: 4.5,
    reviews: 6120,
    prices: { flipkart: 44999, croma: 46999, amazon: 45999 },
    attributes: { RAM: "8 GB", Storage: "128 GB", Display: '6.3" Actua pOLED, 120Hz', Chip: "Google Tensor G4", Battery: "5100 mAh" },
  },
  {
    id: "nord-ce4-lite-8-128",
    title: "OnePlus Nord CE4 Lite 5G (8 GB RAM, 128 GB) – Super Silver",
    brand: "OnePlus",
    model: "CPH2619",
    category: "mobiles",
    mrp: 20999,
    rating: 4.3,
    reviews: 31255,
    prices: { amazon: 17999, flipkart: 18499, croma: 18299 },
    attributes: { RAM: "8 GB", Storage: "128 GB", Display: '6.67" AMOLED, 120Hz', Processor: "Snapdragon 695", Battery: "5500 mAh" },
  },
  {
    id: "sony-wh1000xm5",
    title: "Sony WH-1000XM5 Wireless Noise Cancelling Headphones – Black",
    brand: "Sony",
    model: "WH-1000XM5/B",
    ean: "4548736132610",
    category: "audio",
    mrp: 34990,
    rating: 4.5,
    reviews: 12877,
    prices: { amazon: 26990, flipkart: 27490, croma: 25990, tatacliq: 27990 },
    attributes: { Type: "Over-ear", "Noise cancellation": "Active (ANC)", Battery: "Up to 30 hours", Connectivity: "Bluetooth 5.2, multipoint" },
  },
  {
    id: "airpods-pro-2-usbc",
    title: "Apple AirPods Pro (2nd generation) with MagSafe Case (USB-C)",
    brand: "Apple",
    model: "MTJV3HN/A",
    category: "audio",
    mrp: 24900,
    rating: 4.6,
    reviews: 22410,
    prices: { amazon: 19990, flipkart: 19499, croma: 20490 },
    attributes: { Type: "In-ear (TWS)", "Noise cancellation": "Active (ANC)", Chip: "H2", Battery: "Up to 30 hours with case" },
  },
  {
    id: "boat-airdopes-141-anc",
    title: "boAt Airdopes 141 ANC TWS Earbuds with 42H Playtime",
    brand: "boAt",
    model: "Airdopes 141 ANC",
    category: "audio",
    mrp: 4490,
    rating: 4.0,
    reviews: 95412,
    prices: { amazon: 1299, flipkart: 1199, myntra: 1349 },
    attributes: { Type: "In-ear (TWS)", "Noise cancellation": "ANC up to 32 dB", Battery: "Up to 42 hours", "Water resistance": "IPX5" },
  },
  {
    id: "jbl-flip-6",
    title: "JBL Flip 6 Portable Waterproof Bluetooth Speaker – Blue",
    brand: "JBL",
    model: "JBLFLIP6BLU",
    category: "audio",
    mrp: 13999,
    rating: 4.5,
    reviews: 14023,
    prices: { amazon: 8999, flipkart: 9499, croma: 9299 },
    outOfStock: ["croma"],
    attributes: { Type: "Portable speaker", Output: "30 W", Battery: "Up to 12 hours", "Water resistance": "IP67" },
  },
  {
    id: "noise-colorfit-pro-6-max",
    title: "Noise ColorFit Pro 6 Max Smartwatch with 1.96\" AMOLED Display",
    brand: "Noise",
    category: "wearables",
    mrp: 9999,
    rating: 4.1,
    reviews: 8840,
    prices: { amazon: 4999, flipkart: 4799, myntra: 5199 },
    attributes: { Display: '1.96" AMOLED', Calling: "Bluetooth calling", Battery: "Up to 7 days", "Water resistance": "IP68" },
  },
  {
    id: "apple-watch-se-2-40",
    title: "Apple Watch SE (2nd Gen, GPS, 40mm) – Midnight Aluminium",
    brand: "Apple",
    model: "MR9X3HN/A",
    category: "wearables",
    mrp: 29900,
    rating: 4.6,
    reviews: 9310,
    prices: { amazon: 22900, flipkart: 21999, croma: 23490 },
    attributes: { Size: "40 mm", Connectivity: "GPS", Sensors: "Heart rate, crash detection", "Water resistance": "50 m" },
  },
  {
    id: "macbook-air-m3-13",
    title: "Apple MacBook Air 13\" M3 (8 GB RAM, 256 GB SSD) – Midnight",
    brand: "Apple",
    model: "MRXV3HN/A",
    category: "laptops",
    mrp: 114900,
    rating: 4.7,
    reviews: 5122,
    prices: { amazon: 94990, flipkart: 92990, croma: 96990, tatacliq: 95490 },
    attributes: { Chip: "Apple M3 (8-core CPU)", RAM: "8 GB", Storage: "256 GB SSD", Display: '13.6" Liquid Retina', Weight: "1.24 kg" },
  },
  {
    id: "nike-air-max-sc",
    title: "Nike Air Max SC Men's Sneakers – White/Black",
    brand: "Nike",
    model: "CW4555-102",
    category: "footwear",
    mrp: 6495,
    rating: 4.4,
    reviews: 3219,
    prices: { myntra: 4871, ajio: 5196, amazon: 5099, tatacliq: 4999 },
    attributes: { Gender: "Men", Material: "Leather & mesh", Sole: "Rubber", Closure: "Lace-up" },
  },
  {
    id: "adidas-ultraboost-light",
    title: "Adidas Ultraboost Light Men's Running Shoes – Core Black",
    brand: "Adidas",
    model: "GY9351",
    category: "footwear",
    mrp: 18999,
    rating: 4.5,
    reviews: 2210,
    prices: { myntra: 11399, ajio: 12349, amazon: 11999 },
    attributes: { Gender: "Men", Use: "Running", Midsole: "Light BOOST", Upper: "Primeknit+" },
  },
  {
    id: "puma-smash-v2",
    title: "Puma Smash v2 Unisex Sneakers – White",
    brand: "Puma",
    model: "365215-01",
    category: "footwear",
    mrp: 4999,
    rating: 4.2,
    reviews: 17602,
    prices: { myntra: 1999, ajio: 2249, amazon: 2099, flipkart: 2149 },
    attributes: { Gender: "Unisex", Material: "Synthetic leather", Sole: "Rubber", Closure: "Lace-up" },
  },
  {
    id: "levis-511-slim",
    title: "Levi's Men's 511 Slim Fit Mid-Rise Jeans – Dark Indigo",
    brand: "Levi's",
    model: "18298-1080",
    category: "clothing",
    mrp: 3599,
    rating: 4.3,
    reviews: 11054,
    prices: { myntra: 1799, ajio: 1979, amazon: 1899, flipkart: 1849 },
    attributes: { Fit: "Slim", Rise: "Mid-rise", Fabric: "Cotton blend with stretch", Wash: "Dark" },
  },
  {
    id: "allen-solly-polo",
    title: "Allen Solly Men's Regular Fit Solid Polo T-Shirt – Navy",
    brand: "Allen Solly",
    category: "clothing",
    mrp: 1499,
    rating: 4.1,
    reviews: 24871,
    prices: { myntra: 749, ajio: 824, amazon: 779, flipkart: 799 },
    attributes: { Fit: "Regular", Fabric: "100% cotton pique", Sleeve: "Short", Neck: "Polo collar" },
  },
  {
    id: "uspa-cotton-shirt",
    title: "U.S. Polo Assn. Men's Slim Fit Cotton Casual Shirt – Sky Blue",
    brand: "U.S. Polo Assn.",
    category: "clothing",
    mrp: 2299,
    rating: 4.2,
    reviews: 6402,
    prices: { myntra: 1149, ajio: 1092, amazon: 1199 },
    attributes: { Fit: "Slim", Fabric: "100% cotton", Sleeve: "Full", Pattern: "Solid" },
  },
  {
    id: "american-tourister-valex-28l",
    title: "American Tourister Valex 28L Laptop Backpack – Black",
    brand: "American Tourister",
    category: "bags",
    mrp: 3850,
    rating: 4.3,
    reviews: 52317,
    prices: { amazon: 1599, flipkart: 1649, myntra: 1699, ajio: 1729 },
    attributes: { Capacity: "28 L", "Laptop sleeve": 'Up to 15.6"', Material: "Polyester", "Water resistant": true },
  },
  {
    id: "wildcraft-trailblazer-45l",
    title: "Wildcraft Trailblazer 45L Rucksack – Olive",
    brand: "Wildcraft",
    category: "bags",
    mrp: 3999,
    rating: 4.2,
    reviews: 4580,
    prices: { amazon: 2399, flipkart: 2299, myntra: 2499 },
    attributes: { Capacity: "45 L", Use: "Trekking & travel", "Rain cover": true, Material: "Polyester" },
  },
  {
    id: "safari-pentagon-65",
    title: "Safari Pentagon 65 cm Medium Hard-Sided Trolley Bag – Midnight Blue",
    brand: "Safari",
    category: "bags",
    mrp: 8800,
    rating: 4.1,
    reviews: 13208,
    prices: { amazon: 3299, flipkart: 3199, ajio: 3499 },
    attributes: { Size: "65 cm (Medium)", Shell: "Polypropylene", Wheels: "4 spinner", Lock: "TSA number lock" },
  },
];

const BANK_OFFERS: Record<Slug, Offer[]> = {
  amazon: [
    { type: "bank", title: "10% instant discount on HDFC Bank cards", description: "Up to ₹1,500 on orders above ₹5,000" },
    { type: "cashback", title: "5% cashback with Amazon Pay ICICI card", description: "Unlimited cashback for Prime members" },
    { type: "emi", title: "No-cost EMI from ₹2,083/month" },
  ],
  flipkart: [
    { type: "bank", title: "5% unlimited cashback on Flipkart Axis Bank card" },
    { type: "bank", title: "₹1,000 off on SBI credit card EMI" },
    { type: "exchange", title: "Up to ₹15,000 off on exchange" },
  ],
  myntra: [
    { type: "coupon", title: "Extra 10% off with code MYNTRA10", description: "On orders above ₹1,499" },
    { type: "bank", title: "10% instant discount on Kotak cards" },
  ],
  ajio: [
    { type: "coupon", title: "Flat ₹300 off with code AJIO300", description: "On orders above ₹1,990" },
    { type: "bank", title: "10% off on IDFC FIRST Bank cards" },
  ],
  croma: [
    { type: "bank", title: "₹2,000 instant discount on ICICI Bank cards" },
    { type: "emi", title: "No-cost EMI up to 9 months" },
  ],
  tatacliq: [
    { type: "coupon", title: "Extra 5% off on first order with code CLIQ5" },
    { type: "bank", title: "7.5% off on RBL Bank cards" },
  ],
};

const DELIVERY: Record<Slug, string> = {
  amazon: "Free delivery tomorrow",
  flipkart: "Free delivery in 2 days",
  myntra: "Delivery in 3–5 days",
  ajio: "Delivery in 4–6 days",
  croma: "Store pickup today · Delivery in 2 days",
  tatacliq: "Delivery in 3–4 days",
};

const NOW = Date.now();
const paise = (rupees: number) => Math.round(rupees * 100);

function storeSearchUrl(slug: Slug, title: string): string {
  const q = encodeURIComponent(title.split("–")[0]!.trim());
  const base = platform(slug).base_url;
  const paths: Record<Slug, string> = {
    amazon: `/s?k=${q}`,
    flipkart: `/search?q=${q}`,
    myntra: `/${q}`,
    ajio: `/search/?text=${q}`,
    croma: `/searchB?q=${q}`,
    tatacliq: `/search/?searchCategory=all&text=${q}`,
  };
  return base + paths[slug];
}

function buildListings(seed: Seed): Listing[] {
  const entries = Object.entries(seed.prices) as [Slug, number][];
  const listings = entries.map(([slug, price], i): Listing => {
    const url = storeSearchUrl(slug, seed.title);
    const rating = Math.min(5, Math.max(3.5, seed.rating + ((i % 3) - 1) * 0.1));
    return {
      id: `${seed.id}--${slug}`,
      platform: platform(slug),
      title: seed.title,
      url,
      affiliate_url: url,
      current_price: paise(price),
      mrp: paise(seed.mrp),
      discount_percent: Math.round((1 - price / seed.mrp) * 100),
      offers: BANK_OFFERS[slug],
      rating: Math.round(rating * 10) / 10,
      review_count: Math.round(seed.reviews * (0.25 + ((i * 37) % 60) / 100)),
      in_stock: !seed.outOfStock?.includes(slug),
      delivery_info: DELIVERY[slug],
      last_checked_at: new Date(NOW - (i + 1) * 7 * 60_000).toISOString(),
      is_best_deal: false,
    };
  });
  listings.sort((a, b) => Number(b.in_stock) - Number(a.in_stock) || a.current_price - b.current_price);
  const best = listings.find((l) => l.in_stock);
  if (best) best.is_best_deal = true;
  return listings;
}

function buildProduct(seed: Seed): ProductDetail {
  const listings = buildListings(seed);
  const inStock = listings.filter((l) => l.in_stock);
  const best = inStock[0] ?? listings[0]!;
  const prices = listings.map((l) => l.current_price);
  return {
    id: seed.id,
    canonical_title: seed.title,
    brand: seed.brand,
    category: category(seed.category),
    image_url: null,
    best_price: best.current_price,
    highest_price: Math.max(...prices),
    mrp: paise(seed.mrp),
    max_discount_percent: Math.max(...listings.map((l) => l.discount_percent ?? 0)),
    rating: seed.rating,
    review_count: seed.reviews,
    store_count: listings.length,
    best_platform: best.platform,
    model_number: seed.model ?? null,
    ean: seed.ean ?? null,
    attributes: seed.attributes,
    listings,
  };
}

export const PRODUCTS: ProductDetail[] = SEEDS.map(buildProduct);

export function toSummary(p: ProductDetail): ProductSummary {
  const { model_number: _m, ean: _e, attributes: _a, listings: _l, ...summary } = p;
  return summary;
}
