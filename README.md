# Vendor Intelligence — prototype

One **Vendor-360** fact layer, two consumers:

| Persona | What they get |
|---|---|
| **Buyer** | Ranked vendor recommendations with reason codes · pre-publish participation forecast · vendor scorecard (90d / 365d / all, delivery trend) · discovery slot for never-invited vendors |
| **Vendor** | **Chat assistant** over their own record · "Why did I lose?" post-mortem per event · my winning price band (own history only) · participation habits · technical weak spots · counter-offer coaching · profile completeness |

Everything runs on **synthetic, Procol-shaped data** with seven planted vendor stories (see below).
No external systems. Works offline.

## The one rule

> **A vendor never sees a competitor's absolute price, name, or rank.**

Vendor-facing output is only *relative* ("4% above L1", "rank 3 of 7"), *own* (your history, your scores),
or *aggregated with k ≥ 3 contributors*. Buyers opt in per tenant with `vendor_feedback_policy ∈ {none,
relative_only, relative_plus_technical}`. `vi/guard.py` (`ConfidentialityGuard`) enforces this on every
vendor-facing payload and returns an audit of what it removed. `tests/test_guard.py` and the API-level test
in `tests/test_postmortem_and_api.py` prove it. **If those tests fail, the product cannot ship.**

## Quick start

```bash
pip install -r requirements.txt      # Flask, numpy, scikit-learn, requests (pytest optional)
./run.sh demo                         # seed → build-facts → train → serve on http://127.0.0.1:8000
./run.sh test                         # 50 tests (pytest if installed, else unittest)
```

`make demo` / `make test` do the same if you prefer make (the Makefile is in the git bundle — see below).
Individual steps: `./run.sh seed`, `build-facts`, `train`, `serve`. Then open `DEMO.md`.

Git history: `git clone vendor-intelligence.bundle vendor-intelligence-git` gives you the six step commits.

Optional: set `ANTHROPIC_API_KEY` and the post-mortem narration is written by Claude — it receives **only**
the guarded payload. Without a key, a deterministic template narrator is used and the demo is identical
in structure.

## Configuration (`.env`)

`cp .env.example .env` and edit it. `vi/env.py` loads it at package import — about forty lines of plain
Python, no dependency. A real shell variable always wins over the file, so
`ANTHROPIC_API_KEY=... ./run.sh serve` still overrides it for one run. `.env` is gitignored; `.env.example`
is committed. A key pasted into the chat panel's **connect Claude** form beats both and lives in server
memory only.

| Variable | Default | Effect |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | unset | Chat + narration run on Claude; blank means the offline engine |
| `VI_ANTHROPIC_MODEL` | `claude-sonnet-4-5` | Model for chat and narration |
| `VI_PORT` | `8000` | Port for `python -m vi.api` (`--port` still wins) |
| `VI_DB` | `data/vendor_intelligence.db` | SQLite file |
| `ANTHROPIC_API_URL` | Anthropic Messages API | Only for a proxy or a mock |
| `VI_ENV_FILE` | `./.env` | Load a different env file |

Changes to `.env` are read at process start, so restart the server after editing it.

## The vendor chat assistant

Vendors talk to **Claude** about their own record in plain language — *"why did I lose the Steel RFQ in July?"*,
*"what did I quote on that event and what did the buyer ask for?"*, *"am I improving this quarter?"*,
*"how am I doing with Apex Steelworks?"* — and get answers built only from their own guarded data.

**Connect Claude**: in the Vendor view click **connect Claude**, paste an Anthropic API key (held in server
memory only; or set `ANTHROPIC_API_KEY` before `./run.sh serve`). The badge turns green and the conversation is
free-form. Without a key a deterministic fallback engine answers a fixed set of questions — it is there so the
demo never dead-ends, not as the product.

- **Tools, not free access.** Claude can only call twelve scoped functions (`vi/chat/tools.py`): `my_events`,
  `event_detail`, `why_did_i_lose`, `price_band`, `habits`, `delivery`, `technical`, `profile`, `buyer_summary`,
  `my_buyers`, `category_summary`, `compare_periods`. Each returns guarded data. There is no other path to the DB.
- **Guard twice.** Tool results are guarded before Claude sees them; the final reply is scanned again so a
  paraphrase can never surface another vendor's name. Asking "who won / L1's price" gets a one-line refusal plus
  the relative view.
- **Policy at row level.** Technical scores come only from buyers whose `vendor_feedback_policy` allows it; a
  `none` buyer's events are answered with "this buyer has not enabled vendor feedback".
- **Persisted + audited.** `chat_messages` keeps each session (scoped to the vendor); every turn is written to
  `audit_log` with the tools called and the guard's decisions.
- **Tested without a key.** `tests/test_chat_llm.py` runs the full tool-use loop against a mock Anthropic server:
  tool_use → tool_result → answer, bad tool args, API failure fallback, bad-key rejection, and a model that names
  a competitor being redacted by the final guard.

## What is AI and what is not

| Component | AI? | Where |
|---|---|---|
| Vendor-360 fact table | **No** — one SQL query, parameterised by buyer / vendor / category / window / as-of | `vi/facts/sql/vendor_profile.sql`, `vi/facts/build.py` |
| ConfidentialityGuard | **No** — deterministic, pure | `vi/guard.py` |
| Post-mortem checks (price / timing / technical / terms) | **No** | `vi/postmortem/checks.py` |
| Post-mortem narration | **Yes (LLM, optional)** — template fallback | `vi/postmortem/narrator.py` |
| Winning price band | **No** — bucketed win rates over own bids | `vi/priceband.py` |
| Buyer ranker `P(bid & top-3)` and forecast `P(bid)` | **Yes (ML)** — logistic regression / GBM, time-split validated | `vi/ranker/` |
| Reason codes | **No** — feature attribution templated with real numbers | `vi/ranker/reasons.py` |
| Discovery slot | **No** — SQL over category activity with other buyers | `vi/ranker/serve.py` |
| Participation forecast | **No** — Σ P(bid) vs threshold | `vi/forecast.py` |
| Vendor chat — tools | **No** — scoped SQL, guarded | `vi/chat/tools.py` |
| Vendor chat — Claude engine | **Yes (LLM)** — tool-use over the scoped tools; the product path | `vi/chat/llm.py` |
| Vendor chat — fallback engine | **No** — intent router, only when no key is set | `vi/chat/offline.py` |

Honest model numbers on the synthetic data (out-of-time test, last 30% of events):
`P(bid)` AUC ≈ 0.71, `P(bid & top-3)` AUC ≈ 0.76. See `data/models/metrics.json` after `make train`.
These describe the prototype, not Procol.

## Planted stories (`vi/seed/archetypes.py`)

| Vendor | Story | Where it shows |
|---|---|---|
| **V-LATE** Rathi Metallurgicals | competitive prices, replies to counter-offers after the window ~80% of the time | vendor post-mortem "timing: high", habits "windows missed 82%" |
| **V-HIGH** Omkar Industrial | 7–10% above L1 in Steel, competitive in Packaging | ranker reason "avg 10% above L1 in Steel"; price band 0 wins above 6% |
| **V-TECHWEAK** Kaveri Chem & Spares | L1 on price, `quality_certifications` < 40% | post-mortem "technical: high", habits weakest section |
| **V-GHOST** Vidyut Traders | opens 30% of mails, rarely bids, declines for "insufficient lead time" | habits, forecast P(bid) low |
| **V-STAR** Shakti Enterprises | high participation, 95% on-time | ranker #1 with reasons |
| **V-SLIPPING** Meridian Freight & Pack | strong a year ago, delivery sliding | scorecard trend −30 pp |
| **V-NEVERINVITED** Sagar Speciality Chemicals | supplies Chemicals to buyers A & B, never invited by C | buyer C discovery slot |

Buyers: Apex Steelworks (policy `relative_plus_technical`), Bharat Packaging (`relative_plus_technical`),
Coastal Chemicals (`none` — demonstrates the guard blanking everything).

## Layout

```
vi/schema.sql                Procol-shaped tables + 3 prototype-only tables (vendor_profiles, post_mortems, audit_log)
vi/seed/                     world.py (companies, categories, mappings) · archetypes.py · events.py · generate.py
vi/facts/                    the Vendor-360 SQL and its idempotent builder
vi/guard.py                  ConfidentialityGuard
vi/postmortem/               checks.py · narrator.py · service.py
vi/priceband.py              own-history price band, buyer purchase band (k-anonymised)
vi/ranker/                   features.py · train.py · reasons.py · serve.py
vi/forecast.py               participation forecast
vi/chat/                     tools.py · offline.py · llm.py · service.py — the vendor assistant
vi/api.py, vi/vendor_views.py, ui/     Flask API + single-page demo UI
tests/                       50 tests; conftest_db.py seeds a fresh DB once per run
PORTING.md                   prototype table/query → real Procol table
DEMO.md                      6-minute click path
```

## Rules the prototype follows

- **Deterministic first.** AI only where interpretation or prediction is needed. Every other component is labelled "no AI".
- **Nothing autonomous.** Recommendations only. Every output is written to `audit_log` with inputs and the guard's decisions.
- **Procol-shaped.** Table and column names mirror Procol so the port is mechanical (`PORTING.md`).
- **Point-in-time safe.** The fact SQL takes an `:until` parameter; the ranker trains on features computed as of each event's `bid_start_time`, so it never sees the future.

## Stack note

Default spec was FastAPI + pytest. The build environment could not reach PyPI, so the prototype uses **Flask**
(same shape, already present) and stdlib **unittest** (pytest runs the same files unchanged). Swapping to
FastAPI is a routing-layer change only — all logic is in plain functions and SQL.
