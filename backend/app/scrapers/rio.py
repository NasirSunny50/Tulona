"""Rio International scraper (platform: getCommerce, server-rendered HTML).

Discovery : phone-brand listing pages (?page=N).
Extraction: JSON-LD Product (name/brand/image/price/availability) + warranty
            parsed from the page text. SSR HTML -> plain httpx, no browser needed.

Per-variant pricing is a later refinement; for now one product-level listing
with the site's representative price (enough to power cross-source matching).
"""
from __future__ import annotations

import html as html_lib
import json
import re

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.models import ScrapedProduct, ScrapedVariant
from app.pipeline.normalize import parse_price, parse_ram_rom

SOURCE_SLUG = "rio"
USES_BROWSER = False  # SSR HTML; plain httpx is enough
BASE = "https://riointernational.com.bd"

# Rio exposes brand pages; these are the phone brands it carries.
PHONE_BRANDS = ["samsung", "apple", "xiaomi", "realme"]

_PHONE_SLUG_RE = re.compile(
    r"/product/[a-z0-9-]*("
    r"galaxy-(a|s|m|z|f)\d|iphone-1\d|redmi|poco|realme-\d|narzo|infinix|tecno|"
    r"vivo-|oppo-|nokia-|motorola|moto-|honor-|nothing-phone|pixel-\d"
    r")[a-z0-9-]*",
    re.I,
)
_NOT_PHONE_RE = re.compile(
    r"buds|watch|fit|case|cover|glass|charger|cable|protector|airpod|"
    r"earbud|headphone|adapter|powerbank|power-bank|laptop|band|strap",
    re.I,
)

_WARRANTY_RE = re.compile(
    r"(\d+\s*(?:year|yr|month|day)s?[^.<\n]{0,40}warranty"
    r"|warranty[^.<\n]{0,40}\d+\s*(?:year|yr|month|day)s?"
    r"|official\s+warranty|service\s+warranty)",
    re.I,
)


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": settings.scrape_user_agent},
        timeout=30, follow_redirects=True,
    )


# Rio's phone listings live under these categories (brand pages only covered 4
# brands -> we were missing ~75% of phones). store_product drops any non-phone
# that slips through, so we can crawl broadly.
RIO_PHONE_CATEGORIES = [
    "mobile", "samsung-mobile", "iphone", "apple", "Xiaomi", "realme", "honor",
    "infinix", "google", "oppo", "vivo", "tecno", "nokia", "oneplus", "itel",
    "motorola", "huawei", "nothing", "walton", "symphony",
]


def discover(limit: int | None = None) -> list[str]:
    """Collect phone product URLs from Rio's phone-category listing pages."""
    seen: set[str] = set()
    out: list[str] = []
    with _client() as c:
        for cat in RIO_PHONE_CATEGORIES:
            page = 1
            while page <= 12:  # safety cap
                try:
                    r = c.get(f"{BASE}/category/{cat}?page={page}")
                except httpx.HTTPError:
                    break
                if r.status_code != 200:
                    break
                links = re.findall(r"/product/[a-z0-9-]+", r.text)
                added = 0
                for l in links:
                    u = f"{BASE}{l}"
                    if u not in seen and not _NOT_PHONE_RE.search(l):
                        seen.add(u)
                        out.append(u)
                        added += 1
                if added == 0 and page > 1:   # page yielded nothing new -> next category
                    break
                page += 1
                if limit and len(out) >= limit:
                    return out[:limit]
    return out[:limit] if limit else out


def _extract_jsonld_product(soup: BeautifulSoup) -> dict | None:
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for d in items:
            if isinstance(d, dict) and "Product" in str(d.get("@type", "")):
                return d
    return None


def _extract_warranty(page_text: str) -> str | None:
    m = _WARRANTY_RE.search(page_text)
    if m:
        return re.sub(r"\s+", " ", m.group(0)).strip()[:80]
    return None


def _extract_storage_options(page_text: str) -> list[str]:
    # e.g. "8GB RAM, 128GB" / "8/256GB"
    opts = re.findall(r"\d{1,2}\s*GB\s*RAM[, ]+\d{2,4}\s*GB|\d{1,2}\s*/\s*\d{2,4}\s*GB",
                      page_text, re.I)
    seen, out = set(), []
    for o in opts:
        o = re.sub(r"\s+", " ", o).strip()
        if o.lower() not in seen:
            seen.add(o.lower())
            out.append(o)
    return out


def scrape_product(page_or_url, url: str | None = None) -> ScrapedProduct | None:
    """Signature mirrors other scrapers; Rio ignores the browser page and uses httpx.

    Callable as scrape_product(url) or scrape_product(page, url).
    """
    target = url or page_or_url
    if not isinstance(target, str):
        raise ValueError("rio.scrape_product needs a URL string")

    with _client() as c:
        r = c.get(target)
    if r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, "lxml")
    product_ld = _extract_jsonld_product(soup)
    if not product_ld:
        return None

    name = product_ld.get("name")
    brand = product_ld.get("brand", {})
    brand = brand.get("name") if isinstance(brand, dict) else brand
    image = product_ld.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    offers = product_ld.get("offers") or {}
    price = parse_price(str(offers.get("price"))) if offers.get("price") is not None else None
    # Rio's JSON-LD reports "InStock" for EVERY product (even ones the live site
    # shows as "Stock Out"), and the SSR HTML has no reliable stock field. Rather
    # than assert a stock status we can't trust, mark it unknown.
    in_stock = None
    sku = product_ld.get("sku")

    page_text = html_lib.unescape(soup.get_text(" ", strip=True))
    warranty = _extract_warranty(page_text)
    storage_opts = _extract_storage_options(page_text)

    # representative variant: parse RAM/ROM from the first storage option if any
    ram = rom = None
    label = name
    if storage_opts:
        ram, rom = parse_ram_rom(storage_opts[0])
        label = storage_opts[0]

    variant = ScrapedVariant(
        raw_label=label or name,
        ram_gb=ram, rom_gb=rom, color=None,
        price=price, warranty=warranty, in_stock=in_stock,
    )

    return ScrapedProduct(
        source_slug=SOURCE_SLUG,
        url=target,
        model_name=name,
        brand=brand,
        source_product_id=str(sku) if sku else None,
        category_path=["Phone"],
        image_url=image,
        spec={"storage_options": storage_opts},
        variants=[variant],
    )
