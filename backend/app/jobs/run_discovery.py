"""Catalog discovery job: discover product URLs for a source, scrape + persist.
Run 1x/day per source.

Usage:
    python -m app.jobs.run_discovery --source sumashtech --limit 5
"""
from __future__ import annotations

import argparse
import sys

from app.jobs.common import scrape_and_store, store_scraped_list
from app.scrapers import dazzle, kry, rio, sumashtech

sys.stdout.reconfigure(encoding="utf-8")

SCRAPERS = {
    "sumashtech": sumashtech,
    "rio": rio,
    "kry": kry,
    "dazzle": dazzle,
}


def run(source: str, limit: int | None = None, headful: bool = False) -> dict:
    scraper = SCRAPERS[source]
    if getattr(scraper, "BULK", False):
        products = scraper.fetch_products(limit=limit)
        print(f"[{source}] fetched {len(products)} products from API")
        stats = store_scraped_list(products, label=f"discover:{source}")
    else:
        urls = scraper.discover(limit=limit)
        print(f"[{source}] discovered {len(urls)} product URLs"
              + (f" (limited to {limit})" if limit else ""))
        stats = scrape_and_store(scraper, urls, headful=headful, label=f"discover:{source}")
    print(f"\nDone. ok={stats['ok']} fail={stats['fail']} variants_stored={stats['variants']}")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, choices=list(SCRAPERS))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--headful", action="store_true")
    args = ap.parse_args()
    run(args.source, args.limit, args.headful)


if __name__ == "__main__":
    main()
