"""Sumash Tech scraper (platform: Nuxt + Django API).

Discovery : product sitemap (filtered to phones).
Extraction: plain httpx + the page's JSON-LD (name/brand/image/category/warranty/
            stock/price) and colour swatches. No browser — the static HTML already
            carries everything we need, so this is fast and hang-free.

Note: per-storage prices need clicking the variant buttons (JS), which httpx can't
do; we record the JSON-LD default-variant price (one representative price per
product). Reliability + coverage win out over per-storage pricing here.
"""
from __future__ import annotations

import html as html_lib
import json
import re

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.models import ScrapedProduct, ScrapedVariant
from app.pipeline.normalize import is_phone, parse_price, parse_ram_rom, parse_variant_string

SOURCE_SLUG = "sumashtech"
USES_BROWSER = False  # static HTML has JSON-LD + colours -> plain httpx
SITEMAP_URL = "https://www.sumashtech.com/__sitemap__/product.xml"

_PHONE_SLUG_RE = re.compile(
    r"/product/[a-z0-9-]*("
    r"galaxy|iphone|redmi|poco|xiaomi|\bmi-|realme|narzo|"
    r"oppo|reno|find-x|vivo|iqoo|infinix|tecno|spark|camon|pova|phantom|"
    r"honor|magic|nokia|motorola|moto-|edge-|oneplus|nord|itel|pixel|"
    r"nothing-phone|huawei|nova-|mate-|lava|symphony|walton|samsung"
    r")[a-z0-9-]*",
    re.I,
)
_NOT_PHONE_RE = re.compile(
    r"case|cover|glass|charger|cable|protector|skin|holder|stand|strap|band|"
    r"earbud|headphone|adapter|powerbank|power-bank|laptop|watch",
    re.I,
)

_COLOR_SKIP = {"5g", "4g", "official", "ultra", "plus", "pro", "max", "lite", "fe"}
_COLOR_IMG_RE = re.compile(r'https?://[^"\']+?/color/[^"\']+?\.(?:webp|jpg|jpeg|png)', re.I)


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": settings.scrape_user_agent},
                        timeout=30, follow_redirects=True)


def discover(limit: int | None = None) -> list[str]:
    """Return phone product URLs from the sitemap."""
    resp = httpx.get(SITEMAP_URL, headers={"User-Agent": settings.scrape_user_agent}, timeout=30)
    resp.raise_for_status()
    urls = re.findall(r"<loc>([^<]+)</loc>", resp.text)
    phones = [
        u for u in urls
        if _PHONE_SLUG_RE.search(u) and not _NOT_PHONE_RE.search(u) and is_phone(u)
    ]
    seen: set[str] = set()
    out: list[str] = []
    for u in phones:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:limit] if limit else out


def _jsonld(soup: BeautifulSoup) -> list[dict]:
    out = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        out.extend(data if isinstance(data, list) else [data])
    return [d for d in out if isinstance(d, dict)]


def _find_type(blocks: list[dict], typ: str) -> dict | None:
    for b in blocks:
        t = b.get("@type")
        if t == typ or (isinstance(t, list) and typ in t):
            return b
    return None


def _extract_colors(html: str, slug: str, brand: str | None) -> list[dict]:
    slug_alnum = re.sub(r"[^a-z0-9]", "", slug.lower())
    brand_toks = {re.sub(r"[^a-z0-9]", "", t) for t in (brand or "").lower().split()}
    out, seen = [], set()
    for src in dict.fromkeys(_COLOR_IMG_RE.findall(html)):
        fn = src.split("/")[-1].rsplit(".", 1)[0]
        keep = []
        for t in re.split(r"[_\-\s]", fn):
            tl = re.sub(r"[^a-z0-9]", "", t.lower())
            if not tl or t.isdigit() or tl in _COLOR_SKIP or tl in brand_toks:
                continue
            if re.fullmatch(r"[0-9a-f]{6}", tl) or tl in slug_alnum:
                continue
            keep.append(t)
        name = " ".join(keep).title().strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append({"name": name, "image": src})
    return out


def _parse_variant_props(s: str | None) -> tuple[int | None, int | None, str | None]:
    """Parse the JSON-LD "Variants" value, e.g. "Gold | 6/128GB | Stock: …".
    Segments arrive in any order; pick the storage and colour ones."""
    if not s:
        return None, None, None
    ram = rom = color = None
    for seg in (x.strip() for x in s.split("|")):
        if re.match(r"(stock|warranty)\s*:", seg, re.I):
            continue
        if re.search(r"\d+\s*/\s*\d+\s*(GB|TB)|\d+\s*(GB|TB)", seg, re.I):
            ram, rom = parse_ram_rom(seg)
        elif not color:
            color = seg or None
    return ram, rom, color


def scrape_product(page_or_url, url: str | None = None) -> ScrapedProduct | None:
    """Signature mirrors the browser scrapers; the page arg is ignored (httpx)."""
    target = url or page_or_url
    if not isinstance(target, str):
        raise ValueError("sumashtech.scrape_product needs a URL string")

    with _client() as c:
        r = c.get(target)
    if r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, "lxml")
    blocks = _jsonld(soup)
    product_ld = _find_type(blocks, "Product")
    if not product_ld:
        return None
    webpage_ld = _find_type(blocks, "WebPage")

    name = product_ld.get("name")
    brand = product_ld.get("brand")
    brand = brand.get("name") if isinstance(brand, dict) else brand
    images = product_ld.get("image") or []
    image_url = images[0] if isinstance(images, list) and images else (images or None)
    source_product_id = str(product_ld.get("productID") or product_ld.get("sku") or "") or None

    category_path: list[str] = []
    if webpage_ld:
        crumbs = (webpage_ld.get("breadcrumb") or {}).get("itemListElement", [])
        names = [c.get("name") for c in crumbs if c.get("name")]
        category_path = [n for n in names if n and n.lower() != "home"][:-1]

    props = {p.get("name"): p.get("value") for p in product_ld.get("additionalProperty", []) or []}
    warranty = props.get("Warranty")
    variants_str = props.get("Variants")                 # e.g. "Gold | 6/128GB | Stock: …"
    stock_str = (props.get("Stock") or "").strip()
    in_stock = (stock_str.lower() == "available") if stock_str else None

    offers = product_ld.get("offers") or {}
    # The JSON-LD price is reliable only when the item is actually available; for
    # out-of-stock / pre-order items it can be a booking deposit, so don't trust it.
    price = parse_price(offers.get("price")) if in_stock else None

    ram, rom, color = _parse_variant_props(variants_str)
    variant = ScrapedVariant(
        raw_label=variants_str or name,
        ram_gb=ram, rom_gb=rom, color=color,
        price=price, warranty=warranty, in_stock=in_stock,
    )

    colors = _extract_colors(r.text, target.rstrip("/").split("/")[-1], brand)

    return ScrapedProduct(
        source_slug=SOURCE_SLUG,
        url=target,
        model_name=name,
        brand=brand,
        source_product_id=source_product_id,
        category_path=category_path,
        image_url=image_url,
        spec={"colors": colors} if colors else {},
        variants=[variant],
    )
