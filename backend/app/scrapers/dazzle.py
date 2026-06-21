"""Dazzle scraper (platform: Next.js + Laravel JSON:API).

Clean bulk API with per-variant pricing AND warranty:
  /api/v2/categories/phones/products?include=price,brand,variants.price,stock
Each variant name encodes ram/storage + color, e.g.
  "Oppo Find N3 ram & storage-12/256GB color-Red".
"""
from __future__ import annotations

import re
import time

import httpx


def _get_retry(client: httpx.Client, url: str, params: dict, tries: int = 4):
    """GET with retries — transient network drops shouldn't abort a bulk crawl."""
    for attempt in range(tries):
        try:
            return client.get(url, params=params)
        except httpx.HTTPError:
            if attempt == tries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))

from app.config import settings
from app.models import ScrapedProduct, ScrapedVariant
from app.pipeline.normalize import parse_price, parse_ram_rom

SOURCE_SLUG = "dazzle"
BULK = True

API = "https://api.dazzle.com.bd/api/v2/categories/phones/products"
PRODUCT_URL = "https://dazzle.com.bd/product/{slug}"

_STORAGE_RE = re.compile(r"(\d+)\s*/\s*(\d+)\s*(?:GB|TB)|(\d+)\s*(?:GB|TB)", re.I)

# Dazzle variant names pack several attributes as "<key>-<value>" segments in
# any order, e.g. "Galaxy S26 color-Cobalt Violet sim/network-Single Sim
# region/variant-India ram & storage-12/256GB". Parse each cleanly.
_DAZZLE_KEYS = [
    ("storage", r"ram\s*&\s*storage"),
    ("color", r"colou?r"),
    ("sim", r"sim\s*[&/]?\s*network"),
    ("region", r"region(?:\s*/\s*variant)?"),
    ("version", r"version"),
    ("warranty", r"warranty"),
]


def _parse_dazzle_attrs(name: str) -> dict:
    markers = []
    for attr, pat in _DAZZLE_KEYS:
        for m in re.finditer(pat + r"\s*-\s*", name, re.I):
            markers.append((m.start(), m.end(), attr))
    markers.sort()
    out = {}
    for i, (s, e, attr) in enumerate(markers):
        nxt = markers[i + 1][0] if i + 1 < len(markers) else len(name)
        val = name[e:nxt].strip(" -|")
        if val and attr not in out:
            out[attr] = val
    return out


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": settings.scrape_user_agent},
                        timeout=30, follow_redirects=True)


def _parse_variant_name(name: str) -> tuple[int | None, int | None, str | None]:
    attrs = _parse_dazzle_attrs(name)
    ram = rom = None
    if attrs.get("storage"):
        ram, rom = parse_ram_rom(attrs["storage"])
    elif _STORAGE_RE.search(name):           # storage sometimes lacks the key prefix
        ram, rom = parse_ram_rom(_STORAGE_RE.search(name).group(0))
    color = attrs.get("color")
    # guard: if a storage/size token leaked into colour, drop it
    if color and _STORAGE_RE.search(color):
        color = None
    return ram, rom, color


def _price_amount(price_obj) -> "object":
    if isinstance(price_obj, dict):
        return parse_price(str(price_obj.get("price")))
    return None


def _parse_product(p: dict) -> ScrapedProduct | None:
    name = p.get("name")
    slug = p.get("slug")
    if not name or not slug:
        return None
    brand = (p.get("brand") or {}).get("name")
    # Dazzle bakes a "dazzle Care+" promo sticker into its images -> don't store
    # them (copyright/branding risk). Clean images come from the other sources.
    image_url = None
    warranty = p.get("warranty")
    base_price = _price_amount(p.get("price"))

    variants: list[ScrapedVariant] = []
    for v in p.get("variants") or []:
        vname = v.get("name") or ""
        ram, rom, color = _parse_variant_name(vname)
        # Use ONLY the variant's own price. No fall back to the product base price:
        # upcoming/TBA phones carry a base "expected" price but have no priced
        # variants — the live site shows "TBA", so we must not invent a price.
        price = _price_amount(v.get("price"))
        status = (v.get("status") or "").lower()
        in_stock = (status == "stock") if status else None
        variants.append(ScrapedVariant(
            raw_label=vname or name,
            ram_gb=ram, rom_gb=rom, color=color,
            price=price, warranty=warranty, in_stock=in_stock,
        ))

    if not variants:
        # simple product with no variant list -> the base price is its price
        in_stock = (str(p.get("status") or "").lower() == "stock") or None
        variants.append(ScrapedVariant(
            raw_label=name, ram_gb=None, rom_gb=None, color=None,
            price=base_price, warranty=warranty, in_stock=in_stock,
        ))

    # Dazzle ships full GSMArena-style specs grouped by section (Body, Display…)
    specifications = p.get("specifications")
    spec = {"specs": specifications} if isinstance(specifications, dict) and specifications else {}

    # colours (name + per-colour image) from the variants
    colors, seen = [], set()
    for v in p.get("variants") or []:
        _, _, cname = _parse_variant_name(v.get("name") or "")
        if cname and cname.lower() not in seen:
            seen.add(cname.lower())
            colors.append({"name": cname, "image": None})  # Dazzle images are watermarked
    if colors:
        spec["colors"] = colors

    return ScrapedProduct(
        source_slug=SOURCE_SLUG,
        url=PRODUCT_URL.format(slug=slug),
        model_name=name,
        brand=brand,
        source_product_id=str(p.get("id")) if p.get("id") else None,
        category_path=["Phone"],
        image_url=image_url,
        spec=spec,
        variants=variants,
    )


def fetch_products(limit: int | None = None) -> list[ScrapedProduct]:
    out: list[ScrapedProduct] = []
    page = 1
    with _client() as c:
        while True:
            params = {
                "sort": "-hot",
                "page[size]": 50,
                "page[number]": page,
                "include": "price,brand,stock,variants.price",
            }
            try:
                r = _get_retry(c, API, params)
            except httpx.HTTPError:
                break  # persistent failure -> return what we have so far (partial)
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
            last_page = (body.get("meta") or {}).get("last_page") or page
            if page >= last_page:
                break
            page += 1
    return out
