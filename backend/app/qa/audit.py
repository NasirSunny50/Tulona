"""End-to-end QA audit.

1. DB sanity   — absurd prices, stock distribution, price/TBA leaks.
2. Re-verify   — re-fetch each source's live data and diff against the DB
                 (the sources render from this same data, so matching it == site).

Usage:  python -m app.qa.audit
Exit code is non-zero if any hard check FAILS.
"""
from __future__ import annotations

import sys
from decimal import Decimal

from app.db import get_conn
from app.scrapers import dazzle, kry, rio

sys.stdout.reconfigure(encoding="utf-8")

LATEST = """
WITH latest AS (
    SELECT DISTINCT ON (listing_id) listing_id, price, in_stock, warranty
    FROM price_history ORDER BY listing_id, scraped_at DESC)
"""

PRICE_FLOOR = Decimal("1500")     # cheapest real phone is ~৳1500+
PRICE_CEIL = Decimal("700000")

ok = []
fail = []
warn = []


def check(cond, label, detail=""):
    (ok if cond else fail).append(label)
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail and not cond else ""))


def expected_price(p):
    """Apply the same transform the store does: price <= 0 -> None."""
    if p is None:
        return None
    p = Decimal(str(p))
    return None if p <= 0 else p


# ---------------------------------------------------------------------------
def db_sanity(conn):
    print("\n== 1. DB sanity ==")
    # absurd prices
    rows = conn.execute(LATEST + f"""
        SELECT s.slug, p.model_name, latest.price
        FROM latest JOIN listings l ON l.id=latest.listing_id
        JOIN sources s ON s.id=l.source_id
        JOIN variants v ON v.id=l.variant_id JOIN products p ON p.id=v.product_id
        WHERE latest.price IS NOT NULL AND (latest.price < {PRICE_FLOOR} OR latest.price > {PRICE_CEIL})
        ORDER BY latest.price LIMIT 20""").fetchall()
    check(len(rows) == 0, "no absurd prices (<৳1500 or >৳700k)",
          detail=", ".join(f"{r['slug']}:{r['model_name']}={r['price']}" for r in rows[:6]))

    # stock distribution per source — flag a source that is 100% one value
    dist = conn.execute(LATEST + """
        SELECT s.slug,
               count(*) FILTER (WHERE latest.in_stock IS TRUE) AS in_s,
               count(*) FILTER (WHERE latest.in_stock IS FALSE) AS out_s,
               count(*) FILTER (WHERE latest.in_stock IS NULL) AS unk
        FROM latest JOIN listings l ON l.id=latest.listing_id JOIN sources s ON s.id=l.source_id
        GROUP BY s.slug ORDER BY s.slug""").fetchall()
    print("  stock distribution (in / out / unknown):")
    for d in dist:
        print(f"     {d['slug']:11} {d['in_s']:5} / {d['out_s']:5} / {d['unk']:5}")
        # a source that claims 100% in-stock with >20 items is suspicious
        tot = d["in_s"] + d["out_s"] + d["unk"]
        if tot > 20 and d["out_s"] == 0 and d["unk"] == 0:
            warn.append(f"{d['slug']} reports 100% in-stock ({tot}) — verify stock signal")

    # products that are matched across >1 source — spot table size
    matched = conn.execute("""
        SELECT count(*) AS c FROM (
          SELECT p.id FROM products p JOIN variants v ON v.product_id=p.id
          JOIN listings l ON l.variant_id=v.id JOIN sources s ON s.id=l.source_id
          GROUP BY p.id HAVING count(DISTINCT s.slug) > 1) x""").fetchone()["c"]
    print(f"  products matched across 2+ sources: {matched}")

    # products with missing image
    noimg = conn.execute("SELECT count(*) AS c FROM products WHERE image_url IS NULL").fetchone()["c"]
    check(noimg == 0, "all products have an image", detail=f"{noimg} missing")


# ---------------------------------------------------------------------------
def reverify_bulk(conn, scraper, slug, sample=200):
    """Re-fetch a bulk-API source and diff prices/stock against the DB."""
    print(f"\n== 2. Re-verify {slug} against live API ==")
    products = scraper.fetch_products()
    expected = {}
    for sp in products:
        for v in sp.variants:
            expected[(sp.url, v.raw_label)] = (expected_price(v.price), v.in_stock)

    db_rows = conn.execute(LATEST + """
        SELECT l.url, l.source_variant_label AS label, latest.price, latest.in_stock
        FROM latest JOIN listings l ON l.id=latest.listing_id JOIN sources s ON s.id=l.source_id
        WHERE s.slug = %s""", (slug,)).fetchall()

    checked = price_mism = stock_mism = missing = 0
    examples = []
    for r in db_rows:
        key = (r["url"], r["label"])
        if key not in expected:
            missing += 1
            continue
        exp_price, exp_stock = expected[key]
        checked += 1
        db_price = Decimal(str(r["price"])) if r["price"] is not None else None
        if db_price != exp_price:
            price_mism += 1
            if len(examples) < 6:
                examples.append(f"{r['url'].split('/')[-1]} [{r['label']}] db={db_price} live={exp_price}")
        if bool(r["in_stock"]) != bool(exp_stock) and not (r["in_stock"] is None and exp_stock is None):
            stock_mism += 1

    print(f"  checked={checked} priceMismatch={price_mism} stockMismatch={stock_mism} notInLiveAnymore={missing}")
    for e in examples:
        print("     price diff:", e)
    check(price_mism == 0, f"{slug}: all live-matched prices correct", detail=f"{price_mism} mismatches")
    check(stock_mism == 0, f"{slug}: all live-matched stock correct", detail=f"{stock_mism} mismatches")


def reverify_rio(conn, sample=15):
    print("\n== 2. Re-verify rio (sampled live pages) ==")
    rows = conn.execute(LATEST + """
        SELECT url, price FROM (
          SELECT DISTINCT l.url AS url, latest.price AS price FROM latest
          JOIN listings l ON l.id=latest.listing_id JOIN sources s ON s.id=l.source_id
          WHERE s.slug='rio' AND latest.price IS NOT NULL
        ) sub ORDER BY random() LIMIT %s""", (sample,)).fetchall()
    mism = 0
    for r in rows:
        sp = rio.scrape_product(r["url"])
        live = expected_price(sp.variants[0].price) if sp and sp.variants else None
        db = Decimal(str(r["price"]))
        if live != db:
            mism += 1
            print(f"     price diff: {r['url'].split('/')[-1]} db={db} live={live}")
    check(mism == 0, f"rio: sampled prices correct ({len(rows)} checked)", detail=f"{mism} mismatches")


def main():
    print("=" * 60)
    print("TULONA QA AUDIT")
    print("=" * 60)
    with get_conn() as conn:
        db_sanity(conn)
        reverify_bulk(conn, kry, "kry")
        reverify_bulk(conn, dazzle, "dazzle")
        reverify_rio(conn)

    print("\n" + "=" * 60)
    print(f"RESULT: {len(ok)} passed, {len(fail)} failed, {len(warn)} warnings")
    for w in warn:
        print(f"  WARN: {w}")
    for f in fail:
        print(f"  FAIL: {f}")
    print("=" * 60)
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
