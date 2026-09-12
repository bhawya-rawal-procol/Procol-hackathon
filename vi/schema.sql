-- Vendor Intelligence — prototype schema.
-- Tables mirror Procol's real names/columns (see PORTING.md). Three tables are
-- prototype-only and marked as such: vendor_profiles, post_mortems, audit_log.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
  id        INTEGER PRIMARY KEY,
  name      TEXT NOT NULL,
  category  TEXT NOT NULL CHECK (category IN ('buyer','vendor')),
  gst_no    TEXT,
  archetype TEXT                         -- prototype-only: which planted story this vendor is
);

CREATE TABLE IF NOT EXISTS buyer_seller_company_mappings (
  id                      INTEGER PRIMARY KEY,
  client_company_id       INTEGER NOT NULL REFERENCES companies(id),
  dealing_with_company_id INTEGER NOT NULL REFERENCES companies(id),
  vendor_code             TEXT NOT NULL,
  status                  TEXT NOT NULL CHECK (status IN ('invited','onboarding','approved','blacklisted')),
  UNIQUE (client_company_id, dealing_with_company_id)
);

CREATE TABLE IF NOT EXISTS product_categories (
  id   INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS products (
  id                  INTEGER PRIMARY KEY,
  name                TEXT NOT NULL,
  product_category_id INTEGER NOT NULL REFERENCES product_categories(id),
  unit                TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_groups (
  id                     INTEGER PRIMARY KEY,
  company_id             INTEGER NOT NULL REFERENCES companies(id),
  title                  TEXT NOT NULL,
  status                 TEXT NOT NULL CHECK (status IN ('draft','active','closed')),
  created_at             TEXT NOT NULL,
  closed_at              TEXT,
  vendor_feedback_policy TEXT NOT NULL DEFAULT 'relative_only'
                         CHECK (vendor_feedback_policy IN ('none','relative_only','relative_plus_technical'))
);

CREATE TABLE IF NOT EXISTS trade_requests (
  id             INTEGER PRIMARY KEY,
  event_group_id INTEGER NOT NULL REFERENCES event_groups(id),
  rfx_mode       TEXT NOT NULL CHECK (rfx_mode IN ('rfq','rfp','auction')),
  status         TEXT NOT NULL CHECK (status IN ('draft','active','closed')),
  bid_start_time TEXT NOT NULL,
  bid_end_time   TEXT NOT NULL,           -- ORIGINAL deadline; extensions live in trade_schedules
  closed_at      TEXT
);

CREATE TABLE IF NOT EXISTS trade_products (
  id               INTEGER PRIMARY KEY,
  trade_request_id INTEGER NOT NULL REFERENCES trade_requests(id),
  product_id       INTEGER NOT NULL REFERENCES products(id),
  quantity         REAL NOT NULL,
  target_price     REAL NOT NULL,          -- buyer's reference price per unit
  asked_payment_terms_days INTEGER NOT NULL DEFAULT 45,
  asked_delivery_days      INTEGER NOT NULL DEFAULT 30
);

CREATE TABLE IF NOT EXISTS audiences (
  id                INTEGER PRIMARY KEY,
  trade_request_id  INTEGER NOT NULL REFERENCES trade_requests(id),
  vendor_company_id INTEGER NOT NULL REFERENCES companies(id),
  invited_at        TEXT NOT NULL,
  mail_opened_at    TEXT,
  UNIQUE (trade_request_id, vendor_company_id)
);

CREATE TABLE IF NOT EXISTS bids (
  id                INTEGER PRIMARY KEY,
  trade_request_id  INTEGER NOT NULL REFERENCES trade_requests(id),
  vendor_company_id INTEGER NOT NULL REFERENCES companies(id),
  status            TEXT NOT NULL CHECK (status IN ('active','revised','selected','rejected','draft')),
  created_at        TEXT NOT NULL,
  bid_tag           TEXT NOT NULL CHECK (bid_tag IN ('initial','negotiation','best_offer','final'))
);

CREATE TABLE IF NOT EXISTS bid_trade_products (
  id                 INTEGER PRIMARY KEY,
  bid_id             INTEGER NOT NULL REFERENCES bids(id),
  trade_product_id   INTEGER NOT NULL REFERENCES trade_products(id),
  price              REAL NOT NULL,
  quantity           REAL NOT NULL,
  payment_terms_days INTEGER NOT NULL,
  delivery_days      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS additional_requests (
  id                INTEGER PRIMARY KEY,
  trade_request_id  INTEGER NOT NULL REFERENCES trade_requests(id),
  vendor_company_id INTEGER NOT NULL REFERENCES companies(id),
  change_type       TEXT NOT NULL CHECK (change_type IN ('counter_offer_for_bid','best_offer')),
  target_price      REAL,
  created_at        TEXT NOT NULL,
  ends_at           TEXT NOT NULL,
  resolution        TEXT CHECK (resolution IN ('accepted','rejected','expired') OR resolution IS NULL),
  resolved_at       TEXT
);

CREATE TABLE IF NOT EXISTS trade_schedules (
  id               INTEGER PRIMARY KEY,
  trade_request_id INTEGER NOT NULL REFERENCES trade_requests(id),
  schedule_type    TEXT NOT NULL CHECK (schedule_type IN ('rfq','auction','extra_closing_time','response_review_time')),
  created_at       TEXT NOT NULL,
  new_end_time     TEXT
);

CREATE TABLE IF NOT EXISTS evaluation_scores (
  id                INTEGER PRIMARY KEY,
  trade_request_id  INTEGER NOT NULL REFERENCES trade_requests(id),
  vendor_company_id INTEGER NOT NULL REFERENCES companies(id),
  section_key       TEXT NOT NULL,
  score             REAL NOT NULL,
  max_score         REAL NOT NULL,
  score_type        TEXT NOT NULL CHECK (score_type IN ('restricted','unrestricted'))
);

CREATE TABLE IF NOT EXISTS proposals (
  id                INTEGER PRIMARY KEY,
  trade_request_id  INTEGER NOT NULL REFERENCES trade_requests(id),
  vendor_company_id INTEGER NOT NULL REFERENCES companies(id),
  status            TEXT NOT NULL CHECK (status IN ('selected','rejected')),
  created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
  id                INTEGER PRIMARY KEY,
  proposal_id       INTEGER NOT NULL REFERENCES proposals(id),
  vendor_company_id INTEGER NOT NULL REFERENCES companies(id),
  created_at        TEXT NOT NULL,
  delivery_date     TEXT NOT NULL,
  delivered_at      TEXT,
  qc_passed         INTEGER                 -- 1/0/NULL
);

CREATE TABLE IF NOT EXISTS user_intents (
  id                INTEGER PRIMARY KEY,
  vendor_company_id INTEGER NOT NULL REFERENCES companies(id),
  trade_request_id  INTEGER NOT NULL REFERENCES trade_requests(id),
  intent_type       TEXT NOT NULL CHECK (intent_type IN ('trade_reject','trade_accept')),
  reason            TEXT,
  remarks           TEXT
);

CREATE TABLE IF NOT EXISTS purchase_price_records (
  id            INTEGER PRIMARY KEY,
  company_id    INTEGER NOT NULL REFERENCES companies(id),
  item_code     TEXT NOT NULL,
  vendor_code   TEXT NOT NULL,
  price         REAL NOT NULL,
  purchase_date TEXT NOT NULL,
  plant_code    TEXT
);

CREATE TABLE IF NOT EXISTS company_rating_logs (
  id                    INTEGER PRIMARY KEY,
  company_id            INTEGER NOT NULL REFERENCES companies(id),
  profiling_date        TEXT NOT NULL,
  bids                  INTEGER DEFAULT 0,
  selected_bids         INTEGER DEFAULT 0,
  revised_bids          INTEGER DEFAULT 0,
  deliveries            INTEGER DEFAULT 0,
  delayed_deliveries    INTEGER DEFAULT 0,
  passed_quality_checks INTEGER DEFAULT 0,
  failed_quality_checks INTEGER DEFAULT 0,
  total_requests        INTEGER DEFAULT 0
);

-- ---------------------------------------------------------------- prototype-only

-- Vendor-360 fact table. Grain: buyer (0 = all buyers) × vendor × category (0 = all) × window.
CREATE TABLE IF NOT EXISTS vendor_profiles (
  buyer_company_id                 INTEGER NOT NULL,
  vendor_company_id                INTEGER NOT NULL,
  category_id                      INTEGER NOT NULL,      -- 0 = all categories
  window                           TEXT NOT NULL CHECK (window IN ('90d','365d','all')),
  invites                          INTEGER,
  events_bid                       INTEGER,
  counter_offers                   INTEGER,
  deliveries                       INTEGER,
  mail_open_rate                   REAL,
  bid_rate                         REAL,
  avg_response_hours               REAL,
  win_rate                         REAL,
  avg_rank                         REAL,
  avg_gap_to_l1_pct                REAL,
  counter_offer_response_rate      REAL,
  counter_offer_accept_rate        REAL,
  avg_counter_offer_response_hours REAL,
  late_counter_offer_rate          REAL,
  extensions_caused                INTEGER,
  on_time_delivery_rate            REAL,
  qc_pass_rate                     REAL,
  avg_technical_pct                REAL,
  weakest_technical_section        TEXT,
  weakest_technical_pct            REAL,
  decline_reasons                  TEXT,                  -- JSON {reason: count}
  last_active_at                   TEXT,
  trend_90d_vs_365d                REAL,                  -- delivery on-time delta (pp)
  built_at                         TEXT NOT NULL,
  PRIMARY KEY (buyer_company_id, vendor_company_id, category_id, window)
);

CREATE TABLE IF NOT EXISTS post_mortems (
  id                INTEGER PRIMARY KEY,
  vendor_company_id INTEGER NOT NULL,
  trade_request_id  INTEGER NOT NULL,
  policy            TEXT NOT NULL,
  checks_json       TEXT NOT NULL,        -- guarded output shown to the vendor
  narration         TEXT,
  next_action       TEXT,
  narrator          TEXT NOT NULL,        -- 'template' | 'anthropic'
  guard_audit_json  TEXT NOT NULL,        -- what the guard stripped and why
  created_at        TEXT NOT NULL,
  UNIQUE (vendor_company_id, trade_request_id)
);

-- Vendor chat (prototype-only). One session per vendor per browser tab; every turn is guarded + audited.
CREATE TABLE IF NOT EXISTS chat_messages (
  id                INTEGER PRIMARY KEY,
  session_id        TEXT NOT NULL,
  vendor_company_id INTEGER NOT NULL,
  role              TEXT NOT NULL CHECK (role IN ('user','assistant')),
  content           TEXT NOT NULL,
  tools_json        TEXT,                  -- tools the engine called to answer
  engine            TEXT,                  -- 'offline' | 'anthropic'
  guard_audit_json  TEXT,
  created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_messages(session_id, id);

CREATE TABLE IF NOT EXISTS audit_log (
  id          INTEGER PRIMARY KEY,
  at          TEXT NOT NULL,
  persona     TEXT NOT NULL,              -- buyer | vendor | system
  actor_id    INTEGER,
  action      TEXT NOT NULL,
  inputs_json TEXT,
  guard_json  TEXT,
  output_hash TEXT
);

CREATE INDEX IF NOT EXISTS idx_bids_tr_vendor      ON bids(trade_request_id, vendor_company_id);
CREATE INDEX IF NOT EXISTS idx_btp_bid             ON bid_trade_products(bid_id);
CREATE INDEX IF NOT EXISTS idx_aud_tr              ON audiences(trade_request_id);
CREATE INDEX IF NOT EXISTS idx_aud_vendor          ON audiences(vendor_company_id);
CREATE INDEX IF NOT EXISTS idx_ar_tr_vendor        ON additional_requests(trade_request_id, vendor_company_id);
CREATE INDEX IF NOT EXISTS idx_eval_tr_vendor      ON evaluation_scores(trade_request_id, vendor_company_id);
CREATE INDEX IF NOT EXISTS idx_prop_tr             ON proposals(trade_request_id);
CREATE INDEX IF NOT EXISTS idx_tp_tr               ON trade_products(trade_request_id);
CREATE INDEX IF NOT EXISTS idx_tr_eg               ON trade_requests(event_group_id);
CREATE INDEX IF NOT EXISTS idx_sched_tr            ON trade_schedules(trade_request_id);
CREATE INDEX IF NOT EXISTS idx_orders_vendor       ON orders(vendor_company_id);
