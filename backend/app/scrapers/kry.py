"""KRY International scraper (platform: Next.js + Node API).

KRY exposes a clean paginated JSON API that returns products WITH their
variations (price per ram/rom) and colors (with stock). So this is a "bulk"
scraper: one API walk yields full ScrapedProduct objects — no page rendering.

Warranty is not exposed by this API (TODO: locate a detail endpoint).
"""
from __future__ import annotations

import httpx

from app.config import settings
from app.models import ScrapedProduct, ScrapedVariant
from app.pipeline.normalize import parse_price, parse_ram_rom

SOURCE_SLUG = "kry"
BULK = True  # yields ScrapedProduct directly via fetch_products()

API = "https://api.kryinternational.com/api/v1/product/get-category-wise-products/phone"
PRODUCT_URL = "https://kryinternational.com/products/{link}"


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": settings.scrape_user_agent},
                        timeout=30, follow_redirects=True)


def _parse_product(p: dict) -> ScrapedProduct | None:
    name = p.get("productName")
    link = p.get("productLink")
    if not name or not link:
        return None
    brand = (p.get("brand") or {}).get("brand")
    images = p.get("ProductImage") or []
    image_url = images[0].get("imageUrl") if images else None

    variants: list[ScrapedVariant] = []
    for vp in p.get("VariationProduct") or []:
        ram, rom = parse_ram_rom(f"{vp.get('ram')}/{vp.get('rom')}")
        # KRY's `discountPrice` is the discount AMOUNT, not the final price.
        # Final selling price = price - discountPrice (0 < discount < price).
        base = vp.get("price") or 0
        disc = vp.get("discountPrice") or 0
        final = base - disc if (disc and 0 < disc < base) else base
        price = parse_price(str(final)) if final and final > 0 else None
        colors = vp.get("ProductColor") or []
        if colors:
            for pc in colors:
                cname = ((pc.get("color") or {}) or {}).get("color")
                variants.append(ScrapedVariant(
                    raw_label=f"{vp.get('ram')}/{vp.get('rom')} | {cname}" if cname
                              else f"{vp.get('ram')}/{vp.get('rom')}",
                    ram_gb=ram, rom_gb=rom, color=cname,
                    price=price, warranty=None, in_stock=bool(pc.get("inStock")),
                ))
        else:
            variants.append(ScrapedVariant(
                raw_label=f"{vp.get('ram')}/{vp.get('rom')}",
                ram_gb=ram, rom_gb=rom, color=None,
                price=price, warranty=None, in_stock=None,
            ))

    if not variants:
        return None

    # colours from ProductColor (KRY has no per-colour image -> use product image)
    colors, seen = [], set()
    for vp in p.get("VariationProduct") or []:
        for pc in vp.get("ProductColor") or []:
            cname = ((pc.get("color") or {}) or {}).get("color")
            if cname and cname.lower() not in seen:
                seen.add(cname.lower())
                colors.append({"name": cname, "image": image_url})

    return ScrapedProduct(
        source_slug=SOURCE_SLUG,
        url=PRODUCT_URL.format(link=link),
        model_name=name,
        brand=brand,
        source_product_id=str(p.get("id")) if p.get("id") else None,
        category_path=["Phone"],
        image_url=image_url,
        spec={"colors": colors} if colors else {},
        variants=variants,
    )


def fetch_products(limit: int | None = None) -> list[ScrapedProduct]:
    """Walk the category API and return ScrapedProduct objects."""
    out: list[ScrapedProduct] = []
    page, size = 1, 50
    with _client() as c:
        while True:
            r = c.get(API, params={"page": page, "size": size,
                                   "sortOrder": "desc", "search": ""})
            if r.status_code != 200:
                break
            body = r.json()
            rows = body.get("data") or []
            for p in rows:
                sp = _parse_product(p)
                if sp:
                    out.append(sp)
                    if limit and len(out) >= limit:
                        return out
            meta = body.get("meta") or {}
            if page >= (meta.get("totalPage") or page):
                break
            page += 1
    return out
