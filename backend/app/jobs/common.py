"""Shared scrape→store loop used by both the discovery and refresh jobs."""
from __future__ import annotations

import time
from contextlib import nullcontext

from app.config import settings
from app.db import get_conn
from app.pipeline.store import store_product
from app.scrapers.base import browser_page


def scrape_and_store(scraper, urls: list[str], *, headful: bool = False,
                     label: str = "", verbose: bool = True) -> dict:
    """Scrape each URL with `scraper` and persist. Returns run stats.

    Used for both jobs: discovery passes freshly-discovered URLs; price refresh
    passes already-known product URLs from the DB. store_product is idempotent
    and appends a fresh price_history snapshot each run -> builds the time series.
    """
    uses_browser = getattr(scraper, "USES_BROWSER", True)
    stats = {"ok": 0, "fail": 0, "variants": 0}

    def handle(conn, page, i, url):
        try:
            sp = scraper.scrape_product(page, url)
            if not sp or not sp.variants:
                stats["fail"] += 1
                if verbose:
                    print(f"  [{i}/{len(urls)}] SKIP (no data): {url}")
                return
            summary = store_product(conn, sp)
            conn.commit()
            stats["variants"] += summary["variants"]
            stats["ok"] += 1
            if verbose:
                print(f"  [{i}/{len(urls)}] OK {summary['brand']} | "
                      f"{summary['model']} | {summary['variants']} variant(s)")
        except Exception as e:
            conn.rollback()
            stats["fail"] += 1
            if verbose:
                print(f"  [{i}/{len(urls)}] ERROR {url} -> {e}")

    with get_conn() as conn:
        if uses_browser:
            # Restart the browser every BATCH products: a single long-lived
            # context over hundreds of pages tends to leak/hang.
            BATCH = 40
            for start in range(0, len(urls), BATCH):
                chunk = urls[start:start + BATCH]
                with browser_page(headless=not headful) as page:
                    for j, url in enumerate(chunk):
                        handle(conn, page, start + j + 1, url)
                        time.sleep(settings.scrape_delay_seconds)
        else:
            for i, url in enumerate(urls, 1):
                handle(conn, None, i, url)
                time.sleep(settings.scrape_delay_seconds)

    return {"label": label, **stats}


def store_scraped_list(products, *, label: str = "", verbose: bool = True) -> dict:
    """Persist a list of already-scraped ScrapedProduct objects (bulk API sources)."""
    ok = fail = total_variants = 0
    with get_conn() as conn:
        for i, sp in enumerate(products, 1):
            try:
                if not sp or not sp.variants:
                    fail += 1
                    continue
                summary = store_product(conn, sp)
                conn.commit()
                total_variants += summary["variants"]
                ok += 1
                if verbose:
                    print(f"  [{i}/{len(products)}] OK {summary['brand']} | "
                          f"{summary['model']} | {summary['variants']} variant(s)")
            except Exception as e:
                conn.rollback()
                fail += 1
                if verbose:
                    print(f"  [{i}/{len(products)}] ERROR {getattr(sp,'model_name','?')} -> {e}")
    return {"label": label, "ok": ok, "fail": fail, "variants": total_variants}
