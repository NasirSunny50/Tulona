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


def _csv_ints(s: str) -> list[int]:
    return [int(x) for x in s.split(",") if x.strip().lstrip("-").isdigit()]


# Display-type buckets -> SQL condition on a Display "Type" value (no user input
# in the patterns, so these are safe to inline).
_DISPLAY_COND = {
    "amoled":  "dd->>'value' ILIKE '%amoled%'",
    "oled":    "(dd->>'value' ILIKE '%oled%' AND dd->>'value' NOT ILIKE '%amoled%')",
    "ips lcd": "dd->>'value' ILIKE '%ips%'",
    "lcd":     "(dd->>'value' ILIKE '%lcd%' AND dd->>'value' NOT ILIKE '%ips%')",
    "tft":     "dd->>'value' ILIKE '%tft%'",
}


def _display_bucket(val: str) -> str | None:
    v = (val or "").lower()
    if "amoled" in v: return "AMOLED"
    if "oled" in v:   return "OLED"
    if "ips" in v:    return "IPS LCD"
    if "lcd" in v:    return "LCD"
    if "tft" in v:    return "TFT"
    return None


@app.get("/api/facets")
def facets():
    """Available filter option values (for the sidebar)."""
    with get_conn() as conn:
        pr = conn.execute(LATEST_CTE + """
            SELECT MIN(mp) AS lo, MAX(mp) AS hi FROM (
              SELECT MIN(latest.price) AS mp FROM products p
              LEFT JOIN variants v ON v.product_id = p.id
              LEFT JOIN listings l ON l.variant_id = v.id
              LEFT JOIN latest ON latest.listing_id = l.id
              GROUP BY p.id HAVING MIN(latest.price) IS NOT NULL) x
        """).fetchone()
        rams = conn.execute("SELECT DISTINCT ram_gb FROM variants WHERE ram_gb IS NOT NULL ORDER BY ram_gb").fetchall()
        roms = conn.execute("SELECT DISTINCT rom_gb FROM variants WHERE rom_gb IS NOT NULL ORDER BY rom_gb").fetchall()
        disp = conn.execute("""
            SELECT DISTINCT dd->>'value' AS v FROM products p,
              jsonb_array_elements(COALESCE(p.spec->'specs'->'Display','[]'::jsonb)) dd
            WHERE dd->>'name' ILIKE 'Type'""").fetchall()
    have = {_display_bucket(r["v"]) for r in disp}
    display = [b for b in ("AMOLED", "OLED", "IPS LCD", "LCD", "TFT") if b in have]
    return {
        "price": {"min": int(pr["lo"] or 0), "max": int(pr["hi"] or 0)},
        "ram": [r["ram_gb"] for r in rams],
        "rom": [r["rom_gb"] for r in roms],
        "display": display,
        "network": ["5G", "4G"],
    }


@app.get("/api/search")
def search(q: str = "", brand: str = "", sort: str = "relevant",
           limit: int = 24, offset: int = 0,
           in_stock: int = 0, price_min: int = 0, price_max: int = 0,
           ram: str = "", rom: str = "", network: str = "", display: str = ""):
    like = f"%{q.strip()}%"
    limit = max(1, min(limit, 60))
    order = _SORT_SQL.get(sort, _SORT_SQL["relevant"])
    params = {"like": like, "limit": limit, "offset": offset}

    where = ["(p.model_name ILIKE %(like)s OR b.name ILIKE %(like)s)"]
    if brand.strip():
        where.append("b.slug = %(brand)s"); params["brand"] = brand.strip()
    ram_l, rom_l = _csv_ints(ram), _csv_ints(rom)
    if ram_l:
        where.append("EXISTS (SELECT 1 FROM variants vv WHERE vv.product_id=p.id AND vv.ram_gb = ANY(%(ram)s))")
        params["ram"] = ram_l
    if rom_l:
        where.append("EXISTS (SELECT 1 FROM variants vv WHERE vv.product_id=p.id AND vv.rom_gb = ANY(%(rom)s))")
        params["rom"] = rom_l
    if network.lower() == "5g":
        where.append(r"p.model_name ~* '\m5g\M'")
    elif network.lower() == "4g":
        where.append(r"p.model_name !~* '\m5g\M'")
    disp_sel = [d.strip().lower() for d in display.split(",") if d.strip().lower() in _DISPLAY_COND]
    if disp_sel:
        conds = " OR ".join(_DISPLAY_COND[d] for d in disp_sel)
        where.append(
            "EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(p.spec->'specs'->'Display','[]'::jsonb)) dd "
            f"WHERE dd->>'name' ILIKE 'Type' AND ({conds}))")

    having = []
    if in_stock:
        having.append("bool_or(latest.in_stock IS TRUE)")
    if price_min:
        having.append("MIN(latest.price) >= %(pmin)s"); params["pmin"] = price_min
    if price_max:
        having.append("MIN(latest.price) <= %(pmax)s"); params["pmax"] = price_max

    core = f"""
        FROM products p
        JOIN brands b ON b.id = p.brand_id
        LEFT JOIN variants v ON v.product_id = p.id
        LEFT JOIN listings l ON l.variant_id = v.id
        LEFT JOIN sources s ON s.id = l.source_id
        LEFT JOIN latest ON latest.listing_id = l.id
        WHERE {' AND '.join(where)}
        GROUP BY p.id, b.name
        {('HAVING ' + ' AND '.join(having)) if having else ''}
    """

    with get_conn() as conn:
        total = conn.execute(LATEST_CTE + f"SELECT count(*) AS c FROM (SELECT p.id {core}) t", params).fetchone()["c"]
        rows = conn.execute(LATEST_CTE + f"""
            SELECT p.slug, p.model_name, b.name AS brand, p.image_url,
                   MIN(latest.price) AS min_price, MAX(latest.price) AS max_price,
                   COUNT(DISTINCT l.source_id) AS source_count,
                   array_remove(array_agg(DISTINCT s.slug), NULL) AS sources
            {core}
            ORDER BY {order}
            LIMIT %(limit)s OFFSET %(offset)s
        """, params).fetchall()

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
