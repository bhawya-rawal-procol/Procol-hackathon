# DEMO — a four-minute click path (vendor)

Run `make demo`, open http://127.0.0.1:8010. One page, one persona: the **vendor**.
The vendor picker is top-right; archetypes are labelled so you know what each one's story is.

The product answers a question vendors on Procol have never been able to ask: *why did I lose, and
what do I change next time?* Everything on the page is the vendor's own record or a relative
position. A competitor's price, name or rank never reaches this page.

---

### 1. The habit that costs the money (60 s)

- Choose **Rathi Metallurgicals Pvt Ltd · V-LATE**.
- Left panel, **My habits**: *"Counter-offer windows missed: 82%"* in red. That is the whole story in
  one number, and it is a number no vendor can see today.
- Around it: invites, bid rate, mail open rate, first-bid response time, average gap to L1, extensions
  they caused, on-time delivery with a 90d-vs-365d trend, and the reasons they gave for declining.
- Under it, **profile completeness** — missing documents and pending onboardings.

### 2. Why did I lose? (90 s)

- Centre column is **My events** — won, lost, or no bid, tagged **MISSED WINDOW** where it applies and
  **NO FEEDBACK** where the buyer does not share any.
- Click any **LOST · MISSED WINDOW** event from **Apex Steelworks** or **Bharat Packaging**.
- Read the post-mortem: *"The main factor was timing. The buyer sent a counter-offer with a 24h window;
  your reply arrived 49h after it closed."* Then **Next time:** a same-day rule for counter-offers.
- Point out the four check cards — timing, price, technical, terms — each with a severity and the
  evidence behind it. Price is stated only as a gap: *"2.0% above L1, rank 2 of 4"*.
- Footer: *"Confidentiality guard removed N item(s). Nothing about other vendors is shown here."*

### 3. My winning price band (30 s)

- Right column: per category, win rate by **% gap to L1** bucket, computed from this vendor's own bids only.
- Switch to **Omkar Industrial Supplies · V-HIGH**: Steel shows **0 wins in the 6–10% and >10% buckets
  across 9 bids**, while inside 3% it wins half. The vendor learns exactly where its price has to be
  without ever seeing a competitor's number.

### 4. Just ask it (90 s)

- Top-right panel, **Ask about my record**. The badge shows the live engine (Groq by default, set in
  `.env`). With no key it answers deterministically instead — the demo never breaks.
- Click **"Which events did I lose recently?"** — a list with buyers and dates.
- Type **"why did I lose the steel rfq in july?"** — it finds the event, gives the timing story and a
  next step, and shows `used: my_events, why_did_i_lose` under the answer.
- Type **"who won it and what was the L1 price?"** — a flat refusal: *"I don't have the other vendor's
  name or quoted price."* followed by the relative view it is allowed to give.
- Type **"how am I doing with Coastal Chemicals?"** — numbers, plus a note that this buyer shares no
  event feedback.

### 5. The guard, live (30 s)

- Still on V-LATE, click a **LOST** event from **Coastal Chemicals**, tagged **NO FEEDBACK**.
  The card is blocked: *"This buyer's feedback policy is none."* and names the guard action that did it.
- That policy is the buyer's switch, per tenant, with three settings. `none` blanks the card entirely.
  `relative_only` keeps price, timing and terms but drops the technical card. `relative_plus_technical`
  shows everything you just read. Flip it in the database and reload to show all three.

---

**Closing line:** one SQL fact table, one guard, one vendor lens. The guard is a pure function with
tests that prove a competitor's price, name or rank cannot appear in any vendor-facing payload. The
only model is the optional narrator behind the chat, and it only ever sees data the guard already passed.
