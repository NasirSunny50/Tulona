"""Tulona public API (FastAPI).

Endpoints:
  GET /api/health
  GET /api/search?q=...           -> products matching the query (with price range)
  GET /api/products/{slug}        -> one product + per-source/variant price comparison
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.db import get_conn

app = FastAPI(title="Tulona API", version="0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Most-recent price per listing, reused by several queries.
LATEST_CTE = """
WITH latest AS (
    SELECT DISTINCT ON (listing_id)
           listing_id, price, currency, warranty, in_stock, scraped_at
    FROM price_history
    ORDER BY listing_id, scraped_at DESC
)
"""


@app.get("/api/health")
def health():
    with get_conn() as conn:
        n = conn.execute("SELECT count(*) AS c FROM products").fetchone()["c"]
    return {"status": "ok", "products": n}


_SORT_SQL = {
    "relevant": "source_count DESC, min_price ASC NULLS LAST, p.model_name",
    "low": "min_price ASC NULLS LAST, p.model_name",
    "high": "min_price DESC NULLS LAST, p.model_name",
    "shops": "source_count DESC, min_price ASC NULLS LAST",
}


@app.get("/api/brands")
def brands():
    """Brands that have phones, with counts — for the brand filter."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT b.name, b.slug, COUNT(DISTINCT p.id) AS n
               FROM brands b JOIN products p ON p.brand_id = b.id
               GROUP BY b.id ORDER BY n DESC, b.name"""
        ).fetchall()
    return {"brands": [dict(r) for r in rows]}


@app.get("/api/suggest")
def suggest(q: str = "", limit: int = 8):
    """Lightweight typeahead suggestions."""
    q = q.strip()
    if len(q) < 1:
        return {"suggestions": []}
    like = f"%{q}%"
    starts = f"{q}%"
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT p.slug, p.model_name, b.name AS brand, p.image_url
               FROM products p JOIN brands b ON b.id = p.brand_id
               WHERE p.model_name ILIKE %(like)s OR b.name ILIKE %(like)s
               ORDER BY (p.model_name ILIKE %(starts)s) DESC, length(p.model_name), p.model_name
               LIMIT %(limit)s""",
            {"like": like, "starts": starts, "limit": max(1, min(limit, 12))},
        ).fetchall()
    return {"suggestions": [dict(r) for r in rows]}


@app.get("/api/search")
def search(q: str = "", brand: str = "", sort: str = "relevant",
           limit: int = 24, offset: int = 0):
    like = f"%{q.strip()}%"
    limit = max(1, min(limit, 60))
    order = _SORT_SQL.get(sort, _SORT_SQL["relevant"])
    brand = brand.strip()
    brand_clause = "AND b.slug = %(brand)s" if brand else ""
    params = {"like": like, "limit": limit, "offset": offset, "brand": brand}

    with get_conn() as conn:
        total = conn.execute(
            f"""SELECT count(*) AS c FROM products p JOIN brands b ON b.id = p.brand_id
                WHERE (p.model_name ILIKE %(like)s OR b.name ILIKE %(like)s) {brand_clause}""",
            params,
        ).fetchone()["c"]

        rows = conn.execute(
            LATEST_CTE + f"""
            SELECT p.slug, p.model_name, b.name AS brand, p.image_url,
                   MIN(latest.price) AS min_price,
                   MAX(latest.price) AS max_price,
                   COUNT(DISTINCT l.source_id) AS source_count,
                   array_remove(array_agg(DISTINCT s.slug), NULL) AS sources
            FROM products p
            JOIN brands b ON b.id = p.brand_id
            LEFT JOIN variants v ON v.product_id = p.id
            LEFT JOIN listings l ON l.variant_id = v.id
            LEFT JOIN sources s ON s.id = l.source_id
            LEFT JOIN latest ON latest.listing_id = l.id
            WHERE (p.model_name ILIKE %(like)s OR b.name ILIKE %(like)s) {brand_clause}
            GROUP BY p.id, b.name
            ORDER BY {order}
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            params,
        ).fetchall()

    return {
        "query": q, "brand": brand, "sort": sort, "total": total,
        "offset": offset, "limit": limit, "count": len(rows),
        "results": [dict(r) for r in rows],
    }


@app.get("/api/products/{slug}")
def product_detail(slug: str):
    with get_conn() as conn:
        prod = conn.execute(
            """SELECT p.id, p.slug, p.model_name, b.name AS brand,
                      p.image_url, p.spec
               FROM products p JOIN brands b ON b.id = p.brand_id
               WHERE p.slug = %s""",
            (slug,),
        ).fetchone()
        if not prod:
            raise HTTPException(404, "product not found")

        offers = conn.execute(
            LATEST_CTE + """
            SELECT s.slug AS source, s.name AS source_name, l.url,
                   v.ram_gb, v.rom_gb, v.color,
                   latest.price, latest.currency, latest.warranty,
                   latest.in_stock, latest.scraped_at
            FROM listings l
            JOIN sources s ON s.id = l.source_id
            JOIN variants v ON v.id = l.variant_id
            JOIN latest ON latest.listing_id = l.id
            WHERE v.product_id = %s
            ORDER BY v.rom_gb NULLS LAST, latest.price NULLS LAST
            """,
            (prod["id"],),
        ).fetchall()

    return {
        "product": dict(prod),
        "offers": [dict(o) for o in offers],
        "source_count": len({o["source"] for o in offers}),
    }
