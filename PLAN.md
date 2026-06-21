# Tulona — Price Comparison Platform (Phase 1: Mobile)

## Goal
Bibhinno BD mobile retailer site theke phone product scrape kore ekta canonical
catalog banano, ar din e koyekbar price/warranty refresh kore ekta price-comparison
website chalano. User search korbe → ek product → kon site e koto dam dekhbe.

## Stack
- Scraping: Python + Playwright (network-intercept for Next.js sites, DOM parse for SSR)
- Backend/API: Python (FastAPI)
- DB: PostgreSQL (Docker)
- Frontend: Next.js
- Scheduler: cron / APScheduler

## Sources (Phase 1 = Mobile only)
| Site | Platform | Discovery | Extraction |
|------|----------|-----------|------------|
| sumashtech.com | Next.js + Django API | product sitemap | Playwright (page JSON) |
| riointernational.com.bd | getCommerce (SSR) | /shop pagination | HTML DOM parse |
| kryinternational.com | Next.js + Node API | n/a | Playwright XHR intercept |
| dazzle.com.bd | Next.js + Laravel API | n/a | Playwright XHR intercept |

## Data model
- categories (self-referencing for sub-category)
- brands
- products (canonical): brand + model + shared spec
- variants: product + RAM + ROM + color  ← price-bearing unit
- sources
- listings: variant <-> source mapping (one buyable item)
- price_history: listing price/warranty/stock snapshots over time
- match_queue: low-confidence listing→variant matches for manual review

## Two separate jobs
- Catalog discovery: 1x/day → find new products/variants, match, store
- Price refresh: 4x/day (12,3,6,9) → update price+warranty+stock on known listings

## Variant handling (critical)
- RAM/ROM differ => different price => SEPARATE variant
- Color tracked as variant attribute (usually same price)
- WooCommerce/SPA "variable products": one page can hold many variations — must
  extract each variation's own price.

## Steps
- [x] Step 0: Recon (platforms, APIs, sitemaps identified)
- [x] Step 1: Scaffold (docker postgres, schema, config) DONE
- [x] Step 2: First scraper end-to-end (sumashtech) DONE
      - discovery via product sitemap (phone-filtered)
      - extraction: JSON-LD (name/brand/image/category/warranty/stock/price)
        + storage-button interaction for per-variant price (reactive-index detection)
      - faithful: reactive pages -> per-variant price; non-reactive pages ->
        site's single displayed price (the site itself shows one price there)
      - stored: products/variants/listings/price_history, idempotent upserts
- [x] Step 3: Matcher DONE
      - normalize-on-insert: brand-stripped, lowercased canonical model key
      - EXACT normalized match -> auto-merge across sources (safe)
      - fuzzy similar -> review queue ONLY (never auto-merge: A17 vs A15 too close)
      - model_signature gate (digit tokens a17/4g must match) kills review noise
      - verified: Galaxy A17 4G & A07 collapse rio+sumashtech onto one product
- [x] Step 4: All 4 sources DONE
      - sumashtech (Nuxt): Playwright + JSON-LD + variant-click pricing
      - rio (getCommerce SSR): httpx + JSON-LD + warranty (representative price)
      - kry (Node API): BULK httpx API — per ram/rom/color price+stock (no warranty in API)
      - dazzle (Laravel JSON:API): BULK httpx — per-variant price + warranty + colors
      - BULK scrapers expose fetch_products(); job framework branches on scraper.BULK
      - verified: 18 products matched across 2+ sites, 4 across 3 sites (e.g. S25 Ultra)
- [x] Step 5: Scheduler DONE
      - APScheduler: price refresh 4x/day (12/15/18/21), discovery 1x/day (3am), tz Asia/Dhaka
      - refresh job = re-scrape KNOWN urls only -> appends price_history snapshots (time series)
      - discovery job = full discover + scrape (finds new products)
      - run: python -m app.jobs.scheduler  (blocking; --now refresh|discovery for one-shot)
- [x] Step 6: API + frontend MVP DONE
      - FastAPI: /api/health, /api/search?q=, /api/products/{slug}
      - Next.js: search page + product price-comparison table (shop/variant/price/
        warranty/stock/visit link), lowest-price highlighting, "compare N shops" badge
      - price=0 treated as "unavailable" (stored NULL, shown gracefully)
      - run: API uvicorn :8000, frontend npm run dev :3000
- [ ] Step 7: Polish (price-history graph, full-catalog scale, kry+dazzle, refinements)

## Known refinements (backlog)
- Rio per-variant pricing (currently 1 representative price/product; sumashtech has per-variant)
- sumashtech: some product pages show one price for all storage (site itself does this)
- Discovery currently phone-slug heuristic; could use category pages for fuller coverage

## Environment notes (Windows dev machine)
- BIOS virtualization was off -> enabled "Virtual Machine Platform" + WSL2; Docker now works.
- Python 3.14: use >= version floors (older pins lacked cp314 wheels). Lock in requirements.lock.txt.
- Run jobs from backend/:  .venv/Scripts/python -m app.jobs.run_discovery --source sumashtech --limit N
- Postgres: docker compose up -d  (creds in .env)
