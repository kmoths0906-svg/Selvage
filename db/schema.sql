-- Selvage database schema
-- Run this in Supabase SQL Editor to create the core tables.

-- one row per garment listing, per retailer
CREATE TABLE products (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  brand               TEXT NOT NULL,
  title               TEXT NOT NULL,
  source              TEXT NOT NULL,        -- 'amazon' | 'impact' | 'direct:quince' ...
  source_product_id   TEXT NOT NULL,
  category            TEXT,                 -- tops | pants | dresses | skirts | outerwear | activewear
  image_url           TEXT,
  buy_url             TEXT NOT NULL,
  price_cents         INTEGER,
  currency            TEXT DEFAULT 'USD',
  first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_checked_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  is_active           BOOLEAN NOT NULL DEFAULT true,
  UNIQUE (source, source_product_id)
);

-- one row per material component; %s across a product should sum to 100
CREATE TABLE fiber_compositions (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id          UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  fiber               TEXT NOT NULL,        -- canonical: 'cotton' | 'linen' | 'hemp' | 'wool' | 'silk' | 'polyester' | 'elastane' ...
  percentage          NUMERIC(5,2) NOT NULL CHECK (percentage > 0 AND percentage <= 100),
  garment_part        TEXT DEFAULT 'shell'  -- 'shell' | 'lining' | 'trim'
);

-- audit trail: exactly what the extraction saw
CREATE TABLE extraction_records (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id          UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  raw_material_text   TEXT NOT NULL,        -- verbatim string as found on the source
  extracted_json      JSONB NOT NULL,       -- LLM structured output before normalization
  confidence          NUMERIC(3,2) NOT NULL,
  screenshot_url       TEXT,
  verified_by         TEXT,                  -- 'human:kristal' | 'human_qa_sample' | null
  verified_at         TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email               TEXT UNIQUE NOT NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE saved_searches (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name                TEXT NOT NULL,
  filters_json        JSONB NOT NULL,       -- { fibers: ['cotton'], exclude: ['elastane'], category: 'dresses' }
  alert_enabled       BOOLEAN NOT NULL DEFAULT false,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE alert_events (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  saved_search_id     UUID NOT NULL REFERENCES saved_searches(id) ON DELETE CASCADE,
  product_id          UUID NOT NULL REFERENCES products(id),
  sent_at             TIMESTAMPTZ
);

-- Indexes for the core "100% X" query pattern
CREATE INDEX idx_fiber_lookup ON fiber_compositions (fiber, percentage);
CREATE INDEX idx_products_active ON products (is_active) WHERE is_active = true;
