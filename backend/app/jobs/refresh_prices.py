"""Price refresh job: re-scrape ALREADY-KNOWN product pages to snapshot current
price/warranty/stock. Run 4x/day (12/3/6/9). Does NOT discover new products.

Usage:
    python -m app.jobs.refresh_prices --source sumashtech
    python -m app.jobs.refresh_prices --all
"""
from __future__ import annotations

import argparse
import sys

from app.db import get_conn
from app.jobs.common import scrape_and_store, store_scraped_list
from app.scrapers import dazzle, kry, rio, sumashtech

sys.stdout.reconfigure(encoding="utf-8")

SCRAPERS = {
    "sumashtech": sumashtech,
    "rio": rio,
    "kry": kry,
    "dazzle": dazzle,
}


def known_urls(source_slug: str) -> list[str]:
    """Distinct product URLs we already have listings for, for one source."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT l.url
               FROM listings l JOIN sources s ON s.id = l.source_id
               WHERE s.slug = %s
               ORDER BY l.url""",
            (source_slug,),
        ).fetchall()
    return [r["url"] for r in rows]


def run(source: str, headful: bool = False) -> dict:
    scraper = SCRAPERS[source]
    if getattr(scraper, "BULK", False):
        # bulk API source: refresh == re-fetch the API (no per-URL crawl)
        products = scraper.fetch_products()
        print(f"[{source}] refreshing {len(products)} products from API")
        stats = store_scraped_list(products, label=f"refresh:{source}", verbose=False)
    else:
        urls = known_urls(source)
        print(f"[{source}] refreshing {len(urls)} known product pages")
        stats = scrape_and_store(scraper, urls, headful=headful,
                                 label=f"refresh:{source}", verbose=False)
    print(f"[{source}] done. ok={stats['ok']} fail={stats['fail']} prices_snapshotted={stats['variants']}")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--source", choices=list(SCRAPERS))
    g.add_argument("--all", action="store_true")
    ap.add_argument("--headful", action="store_true")
    args = ap.parse_args()

    sources = list(SCRAPERS) if args.all else [args.source]
    for src in sources:
        run(src, args.headful)


if __name__ == "__main__":
    main()
