"""Persist scraped products into the canonical catalog + price history.

For the catalog-seeding source (sumashtech) brand/model/variant come clean
from JSON-LD, so listings are stored already matched. Fuzzy cross-source
matching for the other sites is handled separately (Step 3).
"""
from __future__ import annotations

from decimal import Decimal

from psycopg.types.json import Json
from rapidfuzz import fuzz

from app.models import ScrapedProduct
from app.pipeline.normalize import (
    clean_model_display,
    is_phone,
    model_signature,
    normalize_color,
    normalize_model,
    slugify,
    variant_key,
)

# Fuzzy thresholds (token_sort_ratio on normalized model strings)
FUZZY_REVIEW_MIN = 84   # >= this (and < exact) -> flag for human review



def get_source_id(conn, slug: str) -> int:
    row = conn.execute("SELECT id FROM sources WHERE slug = %s", (slug,)).fetchone()
    if not row:
        raise ValueError(f"Unknown source slug: {slug}")
    return row["id"]


def get_category_id(conn, slug: str = "mobile") -> int | None:
    row = conn.execute("SELECT id FROM categories WHERE slug = %s", (slug,)).fetchone()
    return row["id"] if row else None


def upsert_brand(conn, name: str) -> int:
    name = (name or "Unknown").strip()
    slug = slugify(name)
    row = conn.execute(
        """INSERT INTO brands (name, slug) VALUES (%s, %s)
           ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
           RETURNING id""",
        (name, slug),
    ).fetchone()
    return row["id"]


def _merge_colors(old: list, new: list) -> list:
    """Union colour lists across sources, dedup by name; prefer a real image."""
    out, by_name = [], {}
    for c in list(old) + list(new):
        if not isinstance(c, dict) or not c.get("name"):
            continue
        key = c["name"].strip().lower()
        if key not in by_name:
            entry = {"name": c["name"].strip(), "image": c.get("image")}
            by_name[key] = entry
            out.append(entry)
        elif not by_name[key].get("image") and c.get("image"):
            by_name[key]["image"] = c["image"]
    return out


def _flag_review(conn, new_product_id: int, candidate_product_id: int,
                 confidence: float, reason: str) -> None:
    conn.execute(
        """INSERT INTO match_queue
             (new_product_id, candidate_product_id, confidence, reason)
           VALUES (%s, %s, %s, %s)""",
        (new_product_id, candidate_product_id, confidence, reason),
    )


def upsert_product(conn, brand_id: int, category_id: int | None,
                   model_name: str, spec: dict, image_url: str | None,
                   brand_name: str) -> int:
    """Find-or-create the canonical product.

    Matching policy:
      * exact normalized_model  -> same product (safe auto-merge across sources)
      * fuzzy-similar (>=84,<100) -> create new product but flag for human review
        (4G/5G and adjacent model numbers are too close to auto-merge)
    """
    display = clean_model_display(brand_name, model_name)
    norm = normalize_model(brand_name, model_name)

    # 1) exact normalized match -> reuse (merge colours across sources)
    existing = conn.execute(
        "SELECT id, spec FROM products WHERE brand_id = %s AND normalized_model = %s",
        (brand_id, norm),
    ).fetchone()
    if existing:
        merged = dict(spec)
        old_colors = (existing["spec"] or {}).get("colors", [])
        if old_colors or spec.get("colors"):
            merged["colors"] = _merge_colors(old_colors, spec.get("colors", []))
        conn.execute(
            """UPDATE products
                 SET spec = spec || %s::jsonb,
                     image_url = COALESCE(image_url, %s),
                     updated_at = now()
               WHERE id = %s""",
            (Json(merged), image_url, existing["id"]),
        )
        return existing["id"]

    # 2) look for a fuzzy-similar same-brand product (for review only)
    candidates = conn.execute(
        "SELECT id, normalized_model FROM products WHERE brand_id = %s",
        (brand_id,),
    ).fetchall()
    sig = model_signature(norm)
    best_id, best_score = None, 0.0
    for c in candidates:
        # only consider candidates that share the same identity tokens (a17/4g);
        # different model numbers => different phone => never a merge candidate.
        if model_signature(c["normalized_model"]) != sig:
            continue
        score = fuzz.token_sort_ratio(norm, c["normalized_model"])
        if score > best_score:
            best_id, best_score = c["id"], score

    # 3) create the new product (unique slug)
    base_slug = slugify(f"{brand_name} {norm}")
    slug = base_slug
    n = 1
    while conn.execute("SELECT 1 FROM products WHERE slug = %s", (slug,)).fetchone():
        n += 1
        slug = f"{base_slug}-{n}"

    new_id = conn.execute(
        """INSERT INTO products
             (brand_id, category_id, model_name, normalized_model, slug, spec, image_url)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           RETURNING id""",
        (brand_id, category_id, display, norm, slug, Json(spec), image_url),
    ).fetchone()["id"]

    if best_id and FUZZY_REVIEW_MIN <= best_score < 100:
        _flag_review(conn, new_id, best_id, best_score,
                     reason=f"similar normalized_model ({best_score:.0f}%)")

    return new_id


def upsert_variant(conn, product_id: int, ram_gb, rom_gb, color) -> int:
    color = normalize_color(color)
    key = variant_key(ram_gb, rom_gb, color)
    row = conn.execute(
        """INSERT INTO variants (product_id, ram_gb, rom_gb, color, variant_key)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (product_id, variant_key) DO UPDATE
             SET ram_gb = COALESCE(variants.ram_gb, EXCLUDED.ram_gb),
                 rom_gb = COALESCE(variants.rom_gb, EXCLUDED.rom_gb),
                 color  = COALESCE(variants.color, EXCLUDED.color)
           RETURNING id""",
        (product_id, ram_gb, rom_gb, color, key),
    ).fetchone()
    return row["id"]


def upsert_listing(conn, source_id: int, variant_id: int, url: str,
                   source_product_id, source_variant_label, raw_title,
                   raw_attributes: dict, match_status: str = "matched") -> int:
    row = conn.execute(
        """INSERT INTO listings
             (source_id, variant_id, source_product_id, source_variant_label,
              url, raw_title, raw_attributes, match_status, last_seen)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
           ON CONFLICT (source_id, url, COALESCE(source_variant_label, ''))
           DO UPDATE SET variant_id = EXCLUDED.variant_id,
                         raw_title = EXCLUDED.raw_title,
                         raw_attributes = EXCLUDED.raw_attributes,
                         match_status = EXCLUDED.match_status,
                         last_seen = now()
           RETURNING id""",
        (source_id, variant_id, source_product_id, source_variant_label,
         url, raw_title, Json(raw_attributes), match_status),
    ).fetchone()
    return row["id"]


def insert_price(conn, listing_id: int, price: Decimal | None, currency: str,
                 warranty: str | None, in_stock: bool | None) -> None:
    # A price of 0 means "not listed / unavailable" on these sites -> store NULL.
    if price is not None and price <= 0:
        price = None
    conn.execute(
        """INSERT INTO price_history (listing_id, price, currency, warranty, in_stock)
           VALUES (%s, %s, %s, %s, %s)""",
        (listing_id, price, currency, warranty, in_stock),
    )


def store_product(conn, sp: ScrapedProduct) -> dict:
    """Persist one scraped product + all its variants. Returns a small summary."""
    if not is_phone(sp.model_name):
        return {"product_id": None, "brand": sp.brand, "model": sp.model_name,
                "variants": 0, "skipped": "non-phone"}

    source_id = get_source_id(conn, sp.source_slug)
    category_id = get_category_id(conn, "mobile")
    brand_name = sp.brand or "Unknown"
    brand_id = upsert_brand(conn, brand_name)

    spec = dict(sp.spec)
    if sp.category_path:
        spec["category_path"] = sp.category_path
    product_id = upsert_product(conn, brand_id, category_id, sp.model_name,
                                spec, sp.image_url, brand_name)

    n_variants = 0
    for v in sp.variants:
        variant_id = upsert_variant(conn, product_id, v.ram_gb, v.rom_gb, v.color)
        listing_id = upsert_listing(
            conn, source_id, variant_id, sp.url,
            source_product_id=sp.source_product_id,
            source_variant_label=v.raw_label,
            raw_title=sp.model_name,
            raw_attributes={"ram_gb": v.ram_gb, "rom_gb": v.rom_gb,
                            "color": v.color, "label": v.raw_label},
        )
        insert_price(conn, listing_id, v.price, v.currency, v.warranty, v.in_stock)
        n_variants += 1

    return {"product_id": product_id, "brand": brand_name,
            "model": sp.model_name, "variants": n_variants}
