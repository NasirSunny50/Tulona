"""Shared Playwright session + JSON-LD helpers used by source scrapers."""
from __future__ import annotations

import json
from contextlib import contextmanager

from playwright.sync_api import sync_playwright

from app.config import settings


@contextmanager
def browser_page(headless: bool = True):
    """Yield a ready Playwright page; cleans up the browser afterward."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(user_agent=settings.scrape_user_agent)
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()


def extract_jsonld(page) -> list[dict]:
    """Return all parsed JSON-LD blocks on the current page."""
    raw_blocks = page.eval_on_selector_all(
        'script[type="application/ld+json"]',
        "els => els.map(e => e.textContent)",
    )
    out: list[dict] = []
    for raw in raw_blocks:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, list):
            out.extend(d for d in data if isinstance(d, dict))
        elif isinstance(data, dict):
            out.append(data)
    return out


def find_type(blocks: list[dict], typ: str) -> dict | None:
    for b in blocks:
        t = b.get("@type")
        if t == typ or (isinstance(t, list) and typ in t):
            return b
    return None
