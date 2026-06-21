-- Tulona schema (Phase 1: Mobile)
-- Canonical catalog + per-source listings + price history.

CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- fuzzy text matching for the matcher

-- ---------------------------------------------------------------------------
-- Taxonomy
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS categories (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    parent_id   INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS brands (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Canonical product (brand + model). Shared spec lives here.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
    id               SERIAL PRIMARY KEY,
    brand_id         INTEGER NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    category_id      INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    model_name       TEXT NOT NULL,                -- clean display name, e.g. "Galaxy A17 4G"
    normalized_model TEXT NOT NULL,                -- match key, e.g. "galaxy a17 4g"
    slug             TEXT NOT NULL UNIQUE,
    spec             JSONB NOT NULL DEFAULT '{}',  -- chipset, display, battery, camera...
    image_url        TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- canonical identity: same brand + same normalized model => same product,
    -- so listings from different sources collapse onto one product.
    UNIQUE (brand_id, normalized_model)
);

-- ---------------------------------------------------------------------------
-- Variant = the price-bearing unit. RAM/ROM differ => different price.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS variants (
    id          SERIAL PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    ram_gb      INTEGER,               -- normalized integer GB (nullable if unknown)
    rom_gb      INTEGER,               -- normalized integer GB
    color       TEXT,                  -- normalized color (nullable)
    variant_key TEXT NOT NULL,         -- e.g. "8-256-navy" for dedup
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_id, variant_key)
);

-- ---------------------------------------------------------------------------
-- Sources (the retailer sites)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sources (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    base_url    TEXT NOT NULL,
    platform    TEXT,                  -- nextjs-django, getcommerce, nextjs-laravel...
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Listing = one buyable item on one source. May be unmatched (variant_id NULL)
-- until the matcher links it to a canonical variant.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS listings (
    id                   SERIAL PRIMARY KEY,
    source_id            INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    variant_id           INTEGER REFERENCES variants(id) ON DELETE SET NULL,
    source_product_id    TEXT,           -- the site's own id/slug, for stable re-fetch
    source_variant_label TEXT,           -- the site's variant label, e.g. "8/256GB | Black"
    url                  TEXT NOT NULL,
    raw_title            TEXT,
    raw_attributes       JSONB NOT NULL DEFAULT '{}', -- raw ram/rom/color/spec as scraped
    match_status         TEXT NOT NULL DEFAULT 'pending', -- pending|matched|review|rejected
    first_seen           TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One buyable item = (source, product url, variant label). COALESCE handles NULLs.
CREATE UNIQUE INDEX IF NOT EXISTS uq_listing_identity
    ON listings (source_id, url, COALESCE(source_variant_label, ''));

-- ---------------------------------------------------------------------------
-- Price history: snapshot per scrape (4x/day). Warranty also snapshotted here
-- since it can change over time.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS price_history (
    id          BIGSERIAL PRIMARY KEY,
    listing_id  INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    price       NUMERIC(12,2),
    currency    TEXT NOT NULL DEFAULT 'BDT',
    warranty    TEXT,
    in_stock    BOOLEAN,
    scraped_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_price_history_listing_time
    ON price_history (listing_id, scraped_at DESC);

-- ---------------------------------------------------------------------------
-- Match review queue: low-confidence listing -> variant suggestions
-- ---------------------------------------------------------------------------
-- Product-merge review: a newly created product looked similar (but not exactly
-- equal after normalization) to an existing one. A human decides if they are the
-- same phone. We never auto-merge on fuzzy similarity (4G vs 5G etc. are too close).
CREATE TABLE IF NOT EXISTS match_queue (
    id                   SERIAL PRIMARY KEY,
    new_product_id       INTEGER REFERENCES products(id) ON DELETE CASCADE,
    candidate_product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    confidence           REAL,
    reason               TEXT,
    status               TEXT NOT NULL DEFAULT 'open',  -- open|merged|rejected
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_listings_match_status ON listings (match_status);
CREATE INDEX IF NOT EXISTS idx_products_model_trgm ON products USING gin (model_name gin_trgm_ops);
