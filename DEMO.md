# DEMO — a six-minute click path

Run `make demo`, open http://127.0.0.1:8000. The page opens in the **Buyer** persona on
**Apex Steelworks Ltd** with the draft **"Steel RFQ — Q4 structural requirement"** already selected.

---

### 1. Buyer: who should I invite? (90 s)

- The table is the ranked recommendation for this Steel RFQ. **Shakti Enterprises (V-STAR) is #1** —
  read the reasons out loud: *"bid on 10 of last 10 Steel invites · avg 1.3% above L1 in Steel · first bid in ~5h"*.
- Scroll to **Omkar Industrial Supplies (V-HIGH)** near the bottom — its red reason says
  *"avg 10% above L1 in Steel"*. Same vendor is competitive in Packaging; the model knows the difference.
- Point at the **Score** bar vs **P(bid)** column: score is *P(bid AND top-3 on price)*; P(bid) alone feeds the forecast.
- Footer line: the ranker's honest out-of-time AUC. Say the number. Say it is synthetic.

### 2. Buyer: will enough vendors show up? (60 s)

- Untick the top five, tick the **bottom three**, press **Forecast for selected**.
- Red message: *"1.5 bids expected from 3 vendors — below the 3-bid rule. Add 2 more to reach ~3.3."*
- Click the two suggested **+ vendor** buttons — they tick themselves and the forecast turns green.
- This is what Clara's `bid_sufficiency_rules` check *after* the event closes; here it runs *before* publish.

### 3. Buyer: vendor scorecard (30 s)

- Click **Meridian Freight & Pack (V-SLIPPING)** in any Packaging/Logistics event, or search it in another
  buyer's event. The drawer shows 90d / 365d / all, and **Delivery trend: −30 pp** in red.

### 4. Buyer: discovery (30 s)

- Switch buyer to **Coastal Chemicals Pvt Ltd**, pick its draft **"Chemicals RFQ"**.
- The **Discovery** box lists **Sagar Speciality Chemicals (V-NEVERINVITED)**:
  *"Active in Chemicals with 2 other buyers (9 events). Never invited by you."*
  No buyer names, no prices — just the fact that a qualified vendor exists outside this tenant's network.

### 5. Vendor: why did I lose? (90 s)

- Toggle to **Vendor**, choose **Rathi Metallurgicals Pvt Ltd · V-LATE**.
- Left panel, **My habits**: *"Counter-offer windows missed: 82%"* in red. That is the whole story in one number.
- Click any **LOST · MISSED WINDOW** event from **Apex Steelworks** or **Bharat Packaging**.
- Read the post-mortem: *"The main factor was timing. The buyer sent a counter-offer with a 24h window;
  your reply arrived 10h after it closed."* Then **Next time:** a same-day rule for counter-offers.
- Point out the four check cards (timing / price / technical / terms) with severities, and the footer:
  *"Confidentiality guard removed N item(s). Nothing about other vendors is shown here."*

### 5b. Vendor: just ask (90 s)

- Top-right panel **Ask about my record**. Click **connect Claude**, paste your Anthropic API key, **Connect** —
  the badge turns green. (Skip this and a fixed-answer fallback engine responds instead.)
- Now ask anything about the vendor's own record, in your own words — e.g. *"what did I quote on the Steel RFQ in
  July and what did the buyer ask for?"*, *"am I getting better this quarter?"*, *"which category should I focus on?"*.
- Click **"Which events did I lose recently?"** — a list with buyers and dates.
- Type **"why did I lose the steel rfq in july?"** — it finds the event and gives the timing story plus a next step,
  and shows `used: my_events, why_did_i_lose` under the answer.
- Type **"who won it and what was the L1 price?"** — explicit refusal: it will never show other vendors' prices or names.
- Type **"how am I doing with Coastal Chemicals?"** — it answers with numbers and notes that this buyer shares no event feedback.
- Footer of the panel says which engine is running: *offline engine* (deterministic) or *Claude* (with an API key).

### 6. Vendor: my winning price band (30 s)

- Right panel: per category, win rate by **% gap to L1** bucket — computed only from this vendor's own bids.
- Switch vendor to **Omkar Industrial Supplies · V-HIGH**: Steel shows **0% wins in the 6–10% and >10% buckets**
  with n≥5. The vendor learns where its price needs to be without ever seeing a competitor's number.

### 7. The guard, live (45 s)

- Still on V-LATE, click a **LOST** event from **Coastal Chemicals** (tagged **NO FEEDBACK**).
  The card is blocked: *"This buyer's feedback policy is none."*
- Go back to **Buyer → Apex Steelworks**, change **Vendor feedback policy** to **none**.
- Return to **Vendor → V-LATE**, click the same Apex event you read in step 5. It is now blocked too.
  Set the policy back to **relative + technical** and it returns.
- Set it to **relative only**: the technical card disappears, price/timing/terms stay.

---

**Closing line:** everything in the buyer view and the vendor view is one fact table with two lenses.
The fact table is SQL. The guard is a pure function with tests. The only models are the ranker and the
optional narrator — and both are labelled as such.
