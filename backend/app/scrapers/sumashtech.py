"""Sumash Tech scraper (platform: Nuxt + Django API).

Discovery : product sitemap (filtered to phones).
Extraction: JSON-LD for name/brand/image/category/warranty/stock/default price,
            plus clicking each storage option to read per-variant price.
"""
from __future__ import annotations

import re

import httpx

from app.config import settings
from app.models import ScrapedProduct, ScrapedVariant
from app.pipeline.normalize import parse_price, parse_ram_rom, parse_variant_string
from app.scrapers.base import extract_jsonld, find_type

SOURCE_SLUG = "sumashtech"
USES_BROWSER = True  # Nuxt app; needs Playwright for variant interaction
SITEMAP_URL = "https://www.sumashtech.com/__sitemap__/product.xml"

# Heuristic prefilter so we only render phone pages (sitemap holds ~3400 items).
# TODO(refine): replace with category-page crawl of /category/phone.
_PHONE_SLUG_RE = re.compile(
    r"/product/[a-z0-9-]*("
    r"galaxy-(a|s|m|z|f)\d|iphone-1\d|redmi|poco|realme-\d|narzo|infinix|tecno|"
    r"vivo-|oppo-|nokia-|motorola|moto-|honor-|nothing-phone|pixel-\d"
    r")[a-z0-9-]*",
    re.I,
)
_NOT_PHONE_RE = re.compile(
    r"case|cover|glass|charger|cable|protector|skin|holder|stand|strap|band|"
    r"earbud|headphone|adapter|powerbank|power-bank|laptop|watch",
    re.I,
)

# Storage button labels look like "8/256GB", "12/512GB", "6/128GB"
_STORAGE_LABEL_RE = re.compile(r"^\d{1,2}\s*/\s*\d{2,4}\s*(GB|TB)$", re.I)


def discover(limit: int | None = None) -> list[str]:
    """Return phone product URLs from the sitemap."""
    resp = httpx.get(SITEMAP_URL, headers={"User-Agent": settings.scrape_user_agent}, timeout=30)
    resp.raise_for_status()
    urls = re.findall(r"<loc>([^<]+)</loc>", resp.text)
    phones = [
        u for u in urls
        if _PHONE_SLUG_RE.search(u) and not _NOT_PHONE_RE.search(u)
    ]
    # de-dup, stable order
    seen: set[str] = set()
    out: list[str] = []
    for u in phones:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:limit] if limit else out


def _additional_props(product_ld: dict) -> dict[str, str]:
    props = {}
    for p in product_ld.get("additionalProperty", []) or []:
        name = p.get("name")
        val = p.get("value")
        if name:
            props[name] = val
    return props


def _all_price_texts(page) -> list[str]:
    """All non-strikethrough taka-leaf texts, in document order."""
    return page.eval_on_selector_all(
        "*",
        """els => els
            .filter(e => e.children.length===0 && /৳/.test(e.textContent)
                         && !(e.className||'').toString().includes('old-price'))
            .map(e => e.textContent.trim())""",
    )


def _read_idx_price(page, idx, fallback):
    if idx is None:
        return fallback
    texts = _all_price_texts(page)
    if 0 <= idx < len(texts):
        return parse_price(texts[idx]) or fallback
    return fallback


def _detect_reactive_idx(page, storage_btns, default_price) -> int | None:
    """Find the taka-leaf index whose value actually reacts to variant clicks.

    Probe by clicking a non-active storage option and seeing which default-priced
    leaf changes. This pins the *variant-reactive* price element, ignoring decoy
    '.new-price' nodes elsewhere on the page.
    """
    before = _all_price_texts(page)
    candidates = [i for i, t in enumerate(before) if parse_price(t) == default_price]
    if not candidates or len(storage_btns) < 2:
        return candidates[0] if candidates else None

    # click the last option (likely different from the active/default one)
    try:
        storage_btns[-1].click()
        page.wait_for_timeout(450)
    except Exception:
        return candidates[0]

    after = _all_price_texts(page)
    for i in candidates:
        if i < len(after) and parse_price(after[i]) != default_price:
            return i           # this leaf reacted -> it's the real price
    return candidates[0]


def _storage_buttons(page):
    btns = page.query_selector_all("button")
    return [b for b in btns if _STORAGE_LABEL_RE.match(b.inner_text().strip())]


_COLOR_SKIP = {"5g", "4g", "official", "ultra", "plus", "pro", "max", "lite", "fe"}


def _extract_colors(page, slug: str) -> list[dict]:
    """All colour swatches (name + per-colour image) from the product page.

    Swatch images live at .../color/<id>/<Color_Name>_<model>.webp — we parse the
    colour out of the filename and drop tokens that belong to the model.
    """
    data = page.eval_on_selector_all(
        "img", "els => els.map(e => ({src: e.src})).filter(d => d.src.includes('/color/'))"
    )
    slug_alnum = re.sub(r"[^a-z0-9]", "", slug.lower())
    out, seen = [], set()
    for d in data:
        fn = d["src"].split("/")[-1].rsplit(".", 1)[0]
        toks = [t for t in re.split(r"[_\-\s]", fn) if t]
        keep = []
        for t in toks:
            tl = re.sub(r"[^a-z0-9]", "", t.lower())
            if not tl or t.isdigit() or tl in _COLOR_SKIP:
                continue
            if re.fullmatch(r"[0-9a-f]{6}", tl):       # hex code in filename
                continue
            if tl and tl in slug_alnum:                # part of the model name
                continue
            keep.append(t)
        name = " ".join(keep).title().strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            out.append({"name": name, "image": d["src"]})
    return out


def scrape_product(page, url: str) -> ScrapedProduct | None:
    page.goto(url, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(800)

    blocks = extract_jsonld(page)
    product_ld = find_type(blocks, "Product")
    webpage_ld = find_type(blocks, "WebPage")
    if not product_ld:
        return None

    name = product_ld.get("name") or page.title()
    brand = (product_ld.get("brand") or {}).get("name") if isinstance(product_ld.get("brand"), dict) else product_ld.get("brand")
    images = product_ld.get("image") or []
    image_url = images[0] if isinstance(images, list) and images else (images or None)
    source_product_id = str(product_ld.get("productID") or product_ld.get("sku") or "")

    # category breadcrumb (skip Home + the product itself)
    category_path: list[str] = []
    if webpage_ld:
        crumbs = (webpage_ld.get("breadcrumb") or {}).get("itemListElement", [])
        names = [c.get("name") for c in crumbs if c.get("name")]
        category_path = [n for n in names if n and n.lower() != "home"][:-1]

    props = _additional_props(product_ld)
    warranty = props.get("Warranty")
    default_variant_str = props.get("Variants")  # e.g. "8/128GB | Black"
    stock_str = props.get("Stock")
    offers = product_ld.get("offers") or {}
    # JSON-LD `availability` is always "InStock" here (unreliable). The real
    # status is the additionalProperty "Stock" = "Available" / "Out".
    in_stock = (stock_str.strip().lower() == "available") if stock_str else None
    default_price = parse_price(offers.get("price"))

    # When a product is NOT in stock, the JSON-LD price is unreliable on this site
    # — pre-order/upcoming phones show a booking DEPOSIT (e.g. ৳10,000) rather than
    # the real price. Only trust the price when Stock = "Available".
    is_booking = in_stock is False
    if is_booking:
        default_price = None

    _, _, default_color = parse_variant_string(default_variant_str or "")

    variants: list[ScrapedVariant] = []
    storage_btns = _storage_buttons(page)
    reactive_idx = _detect_reactive_idx(page, storage_btns, default_price) if storage_btns else None

    if storage_btns:
        for btn in storage_btns:
            label = btn.inner_text().strip()
            try:
                btn.click()
                page.wait_for_timeout(450)
            except Exception:
                continue
            ram, rom = parse_ram_rom(label)
            price = None if is_booking else _read_idx_price(page, reactive_idx, default_price)
            variants.append(ScrapedVariant(
                raw_label=f"{label} | {default_color}" if default_color else label,
                ram_gb=ram, rom_gb=rom, color=default_color,
                price=price, warranty=warranty, in_stock=in_stock,
            ))
    else:
        # no storage selector -> single variant from JSON-LD
        ram, rom, color = parse_variant_string(default_variant_str or "")
        variants.append(ScrapedVariant(
            raw_label=default_variant_str or name,
            ram_gb=ram, rom_gb=rom, color=color,
            price=default_price, warranty=warranty, in_stock=in_stock,
        ))

    colors = _extract_colors(page, url.rstrip("/").split("/")[-1])

    return ScrapedProduct(
        source_slug=SOURCE_SLUG,
        url=url,
        model_name=name,
        brand=brand,
        source_product_id=source_product_id or None,
        category_path=category_path,
        image_url=image_url,
        spec={"colors": colors} if colors else {},
        variants=variants,
    )
