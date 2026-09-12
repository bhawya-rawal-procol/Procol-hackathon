# PORTING — prototype → Procol

Every prototype table mirrors a real Procol table. Column names were kept where Procol's are known;
where the prototype simplified, the difference is listed.

## Tables

| Prototype table | Procol table | Notes for the port |
|---|---|---|
| `companies` | `companies` | Procol has `category`/`recommendation_identifier`; prototype adds `archetype` (drop). |
| `buyer_seller_company_mappings` | `buyer_seller_company_mappings` | Same name. Procol: `client_company_id`, `dealing_with_company_id`, `vendor_code`, onboarding `status`. Vendor codes are zero-padded inconsistently in Procol — join on `LPAD(vendor_code,10,'0')` as `trade_tools/handler.rb:172` does. |
| `product_categories`, `products` | same | Category resolved via `products.product_category_id`. |
| `event_groups` | `event_groups` | `vendor_feedback_policy` is **new** — add as a column or, better, as a key in `clara_company_policies` (per-tenant) so it sits beside the other Clara policies. |
| `trade_requests` | `trade_requests` | `rfx_mode`, `bid_start_time`, `bid_end_time`, `closed_at` exist. Procol's `bid_end_time` may move on extension — the prototype keeps the *original* deadline here and extensions in `trade_schedules`; confirm which Procol column is authoritative. |
| `trade_products` | `trade_products` | Buyer reference price lives in `meta_data->savings_configuration->reference_prices`, not a column. `asked_payment_terms_days`/`asked_delivery_days` map to template widgets. |
| `audiences` | `audiences` | `mail_opened_at` comes from `ahoy_messages` (open tracking) joined on the invite mail — see `vendor_participation_data_worker.rb`. |
| `bids` | `bids` | Procol statuses are richer (`revised`, `selected`, `requested`, `anomaly_detected`…). "Latest bid per vendor" = `MAX(created_at)`; Procol also tags bids in `event_snapshots.snapshot_data_v1` (`initial/final/negotiation/best_offer_revision`) which is the better source once available. |
| `bid_trade_products` | `bid_trade_products` | `price`, `quantity`; total landed amount is in `price_breakup_json` in Procol — use TLA rather than `price*quantity` where it exists. |
| `additional_requests` | `additional_requests` | `change_type = 'counter_offer_for_bid'` is the real value. Best-offer rounds are `trade_schedules.schedule_type='response_review_time_for_participant'` in Procol, not an `additional_request`. |
| `trade_schedules` | `trade_schedules` | `schedule_type` values differ slightly; extensions are `extra_closing_time` in Procol too. |
| `evaluation_scores` | `evaluation_scores` | `score_type restricted/unrestricted` is real. `section_key` maps to the form section / EGLITM. |
| `proposals` | `proposals` | `status='selected'` = awarded. Lot-split events have several. |
| `orders` | `orders` + `delivery_trackings` | `delivered_at` / `qc_passed` come from `delivery_trackings` and `quality_approvals`. **Verify capture consistency first** — this is the weakest real-data assumption in the prototype. |
| `user_intents` | `user_intents` | Same: `intent_type trade_reject`, `reason` (jsonb), `remarks`. |
| `purchase_price_records` | `purchase_price_records` | Same columns; `item_code` ↔ product via the item master. |
| `company_rating_logs` | `company_rating_logs` | Same columns. Its worker cron is commented out in `config/sidekiq.yml:72-75` — re-enable, and fix the `+ 0` hardcodes for delivery/payment columns in `scripts/company_rating.rb`. |
| `vendor_profiles` | **new** | Nightly job (Sidekiq) writing to Postgres. Grain: buyer × vendor × category × window, plus buyer=0 / category=0 rows. |
| `post_mortems` | **new** | Cache + audit of vendor-facing narratives. |
| `audit_log` | `activity_logs` (DynamoDB) or new | Procol's activity log carries `mcp_client_data`; a recommendation log fits the same stream. |

## Queries

| Prototype | Procol equivalent / home |
|---|---|
| `vi/facts/sql/vendor_profile.sql` | New service `VendorProfiles::BuildService`; run nightly, parameterised identically. The `:until` parameter is what makes point-in-time features safe for training. |
| `POSITION_SQL` in `checks.py` (own total, L1, rank) | `BidRankHelper` / `EventIndicators::LineItemBased` already compute rank; reuse rather than re-derive. |
| `discovery_vendors` | Cross-tenant — needs the governance decisions in README before it leaves a prototype. Within-tenant category adjacency is safe immediately. |
| `event_suggested_vendors` output | Extend the existing MCP tool's `output_schema` with `score` and `reasons[]`; Clara picks it up without a new surface. |
| `forecast` | Reuse `clara_company_policies.bid_sufficiency_rules` (Dentaku) as the threshold instead of the constant 3. |
| `AiAuditor` | Generalise `ai_auditor/counter_offer_auditor.rb` to record buyer accept/reject of ranked suggestions — that is the ranker's feedback loop. |

## What changes in Rails

1. Add `vendor_feedback_policy` to `clara_company_policies` (allowed values as in `vi/guard.py`).
2. Port `ConfidentialityGuard` as a PORO with the same tests; wire it into every vendor-facing serializer.
3. `VendorProfiles::BuildService` + Sidekiq cron; table as above.
4. Post-mortem: a service object per check, a narrator strategy (template default; LLM via `ExternalApi::AiService`).
5. Ranker: train offline in the Python AI service (`PROCOL_AI_BASE_URL`), serve scores back through the MCP tool; features come from `vendor_profiles`.
6. UI: buyer side in the existing event-publish flow; vendor side in Supplier Suite.
