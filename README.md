# Tulona — Phone Price Comparison (BD)

Scrapes phones from Bangladeshi retailer sites into a canonical catalog and serves
a search + price-comparison website. Phase 1 = mobiles.

See **[PLAN.md](PLAN.md)** for architecture and progress.

## Stack
- Scraping + API: Python 3.14, Playwright, FastAPI
- DB: PostgreSQL (Docker)
- Frontend: Next.js

## Prerequisites
- Docker Desktop (WSL2 backend enabled)
- Python 3.x, Node 18+

## Setup

```bash
# 1. Database
cp .env.example .env
docker compose up -d            # Postgres on :5432, schema auto-applied

# 2. Backend (from backend/)
cd backend
py -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m playwright install chromium
```

## Scrape some data

```bash
# from backend/  — discover + scrape + store (1x/day catalog job)
.venv/Scripts/python -m app.jobs.run_discovery --source sumashtech --limit 25
.venv/Scripts/python -m app.jobs.run_discovery --source rio        --limit 25
```

Sources: `sumashtech`, `rio` (kry, dazzle coming).

## Run the API

```bash
# from backend/
.venv/Scripts/python -m uvicorn app.api.main:app --port 8000
# GET /api/health  /api/search?q=a17  /api/products/{slug}
```

## Automated scraping (scheduler)

```bash
# from backend/  — long-lived process
.venv/Scripts/python -m app.jobs.scheduler         # price refresh 4x/day + discovery 1x/day
# one-shot (no scheduling):
.venv/Scripts/python -m app.jobs.refresh_prices --all
.venv/Scripts/python -m app.jobs.run_discovery --source sumashtech
```
Schedule is configurable in `.env` (REFRESH_HOURS, DISCOVERY_HOUR, TIMEZONE).

## Run the frontend

```bash
# from frontend/
npm install
npm run dev          # http://localhost:3000  (talks to API on :8000)
```

## Project layout
```
backend/
  app/
    config.py  db.py  models.py
    scrapers/   sumashtech.py  rio.py  base.py
    pipeline/   normalize.py   store.py        # parsing + matcher + persistence
    jobs/       run_discovery.py
    api/        main.py                         # FastAPI
  db/           schema.sql  seed.sql
frontend/       app/ (Next.js: search + product compare)
```
