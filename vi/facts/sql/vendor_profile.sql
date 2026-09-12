-- Vendor-360 profile for ONE (buyer, vendor) pair, optionally one category, over [since, until).
-- No AI. Every metric is a plain aggregate over Procol-shaped tables.
-- Parameters: :buyer (0 = all buyers) :vendor :category (0 = all) :since (NULL = open) :until (NULL = now)
--
-- Point-in-time safety: an event is in scope only if its bidding STARTED before :until, and an
-- order counts only if it was delivered before :until. The ranker calls this with
-- :until = the event's own bid_start_time so training features never see the future.

WITH params AS (
  SELECT :buyer AS buyer, :vendor AS vendor, :category AS category, :since AS since, :until AS until
),
ev AS (                                       -- this buyer's closed events in scope
  SELECT tr.id AS tr_id, tr.bid_start_time, tr.bid_end_time, tr.rfx_mode, tr.closed_at, c.cat_id
  FROM trade_requests tr
  JOIN event_groups eg ON eg.id = tr.event_group_id
  JOIN (SELECT tp.trade_request_id, MIN(p.product_category_id) AS cat_id
        FROM trade_products tp JOIN products p ON p.id = tp.product_id GROUP BY 1) c
    ON c.trade_request_id = tr.id
  CROSS JOIN params
  WHERE (params.buyer = 0 OR eg.company_id = params.buyer) AND tr.status = 'closed'
    AND (params.since IS NULL OR tr.bid_start_time >= params.since)
    AND (params.until IS NULL OR tr.bid_start_time <  params.until)
    AND (params.category = 0 OR c.cat_id = params.category)
),
inv AS (                                      -- invitations to THIS vendor
  SELECT ev.*, a.invited_at, a.mail_opened_at
  FROM ev JOIN audiences a ON a.trade_request_id = ev.tr_id CROSS JOIN params
  WHERE a.vendor_company_id = params.vendor
),
latest AS (                                   -- latest bid per (event, vendor) — ALL vendors, for L1/rank
  SELECT b.trade_request_id AS tr_id, b.vendor_company_id AS v, b.id AS bid_id
  FROM bids b JOIN ev ON ev.tr_id = b.trade_request_id
  WHERE b.created_at = (SELECT MAX(b2.created_at) FROM bids b2
                        WHERE b2.trade_request_id = b.trade_request_id
                          AND b2.vendor_company_id = b.vendor_company_id)
),
tot AS (
  SELECT l.tr_id, l.v, SUM(btp.price * btp.quantity) AS total
  FROM latest l JOIN bid_trade_products btp ON btp.bid_id = l.bid_id GROUP BY 1, 2
),
ranked AS (
  SELECT tr_id, v, total,
         RANK() OVER (PARTITION BY tr_id ORDER BY total) AS rnk,
         MIN(total) OVER (PARTITION BY tr_id)             AS l1,
         COUNT(*)   OVER (PARTITION BY tr_id)             AS n_bidders
  FROM tot
),
mine AS (                                     -- THIS vendor's final position per event
  SELECT r.*, (r.total - r.l1) / r.l1 * 100.0 AS gap_pct
  FROM ranked r CROSS JOIN params WHERE r.v = params.vendor
),
first_bid AS (
  SELECT b.trade_request_id AS tr_id, MIN(b.created_at) AS first_at
  FROM bids b JOIN ev ON ev.tr_id = b.trade_request_id CROSS JOIN params
  WHERE b.vendor_company_id = params.vendor GROUP BY 1
),
wins AS (
  SELECT p.trade_request_id AS tr_id
  FROM proposals p JOIN ev ON ev.tr_id = p.trade_request_id CROSS JOIN params
  WHERE p.vendor_company_id = params.vendor AND p.status = 'selected'
),
co AS (                                       -- counter-offers sent to THIS vendor
  SELECT ar.*
  FROM additional_requests ar JOIN ev ON ev.tr_id = ar.trade_request_id CROSS JOIN params
  WHERE ar.vendor_company_id = params.vendor AND ar.change_type = 'counter_offer_for_bid'
),
ext AS (                                      -- extensions on events where this vendor bid AFTER the original deadline
  SELECT COUNT(*) AS n
  FROM trade_schedules ts
  JOIN inv        ON inv.tr_id = ts.trade_request_id
  JOIN first_bid fb ON fb.tr_id = inv.tr_id
  WHERE ts.schedule_type = 'extra_closing_time' AND fb.first_at > inv.bid_end_time
),
deliv AS (
  SELECT o.*
  FROM orders o JOIN proposals p ON p.id = o.proposal_id JOIN ev ON ev.tr_id = p.trade_request_id
  CROSS JOIN params
  WHERE o.vendor_company_id = params.vendor AND o.delivered_at IS NOT NULL
    AND (params.until IS NULL OR o.delivered_at < params.until)
),
tech AS (
  SELECT e.section_key, AVG(e.score / e.max_score) * 100.0 AS pct
  FROM evaluation_scores e JOIN ev ON ev.tr_id = e.trade_request_id CROSS JOIN params
  WHERE e.vendor_company_id = params.vendor GROUP BY 1
),
intents AS (
  SELECT u.reason, COUNT(*) AS n
  FROM user_intents u JOIN ev ON ev.tr_id = u.trade_request_id CROSS JOIN params
  WHERE u.vendor_company_id = params.vendor AND u.intent_type = 'trade_reject' GROUP BY 1
)
SELECT
  (SELECT COUNT(*) FROM inv)                                                          AS invites,
  (SELECT AVG(mail_opened_at IS NOT NULL) FROM inv)                                  AS mail_open_rate,
  (SELECT AVG(EXISTS (SELECT 1 FROM first_bid fb WHERE fb.tr_id = inv.tr_id)) FROM inv) AS bid_rate,
  (SELECT AVG((julianday(fb.first_at) - julianday(inv.invited_at)) * 24)
     FROM inv JOIN first_bid fb ON fb.tr_id = inv.tr_id)                             AS avg_response_hours,
  (SELECT AVG(EXISTS (SELECT 1 FROM wins w WHERE w.tr_id = m.tr_id)) FROM mine m)   AS win_rate,
  (SELECT AVG(rnk) FROM mine)                                                        AS avg_rank,
  (SELECT AVG(gap_pct) FROM mine)                                                    AS avg_gap_to_l1_pct,
  (SELECT COUNT(*) FROM mine)                                                        AS events_bid,
  (SELECT COUNT(*) FROM co)                                                          AS counter_offers,
  (SELECT AVG(resolution IN ('accepted', 'rejected')) FROM co)                       AS counter_offer_response_rate,
  (SELECT AVG(resolution = 'accepted') FROM co WHERE resolution IN ('accepted', 'rejected'))
                                                                                     AS counter_offer_accept_rate,
  (SELECT AVG((julianday(resolved_at) - julianday(created_at)) * 24) FROM co WHERE resolved_at IS NOT NULL)
                                                                                     AS avg_counter_offer_response_hours,
  (SELECT AVG(resolution = 'expired') FROM co)                                       AS late_counter_offer_rate,
  (SELECT n FROM ext)                                                                AS extensions_caused,
  (SELECT AVG(delivered_at <= delivery_date) FROM deliv)                             AS on_time_delivery_rate,
  (SELECT AVG(qc_passed) FROM deliv WHERE qc_passed IS NOT NULL)                     AS qc_pass_rate,
  (SELECT COUNT(*) FROM deliv)                                                       AS deliveries,
  (SELECT AVG(pct) FROM tech)                                                        AS avg_technical_pct,
  (SELECT section_key FROM tech ORDER BY pct LIMIT 1)                                AS weakest_technical_section,
  (SELECT MIN(pct) FROM tech)                                                        AS weakest_technical_pct,
  (SELECT json_group_object(reason, n) FROM intents)                                 AS decline_reasons,
  (SELECT MAX(b.created_at) FROM bids b JOIN ev ON ev.tr_id = b.trade_request_id CROSS JOIN params
     WHERE b.vendor_company_id = params.vendor)                                      AS last_active_at
;
