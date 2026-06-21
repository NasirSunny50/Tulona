-- Seed: Phase 1 taxonomy + the 4 mobile sources.

INSERT INTO categories (name, slug, parent_id) VALUES
    ('Mobile', 'mobile', NULL)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO sources (name, slug, base_url, platform) VALUES
    ('Sumash Tech',        'sumashtech', 'https://www.sumashtech.com',     'nextjs-django'),
    ('Rio International',   'rio',        'https://riointernational.com.bd','getcommerce'),
    ('KRY International',   'kry',        'https://kryinternational.com',   'nextjs-node'),
    ('Dazzle',             'dazzle',     'https://dazzle.com.bd',          'nextjs-laravel')
ON CONFLICT (slug) DO NOTHING;
