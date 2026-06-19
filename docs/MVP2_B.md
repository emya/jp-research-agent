# MVP2 Track B — Deeper Data & Longer History

Status: **in progress** (started 2026-06-18) — M2.1 + M2.2 built & offline-tested

## Goal

Enrich per-company understanding: extend history to 10–15 years, add cash-flow
and segment data, and (stretch) ingest earnings-call / IR-deck material.

## In scope

* **Long history (10–15 yr)** — chain multiple annual reports' 5-year summaries.
  * `client.fetch_annual_reports(ticker, years=N)` — find & download several past filings.
  * `HistoryMerger` — merge per-year, dedupe overlaps, apply a **restatement policy**
    (prefer the most recent filing's value; flag discrepancies) and split-adjust per-share.
  * Cache downloaded XBRL to avoid refetching.
* **Cash flow & capex** — operating / investing / financing cash flow, free cash flow.
* **Segment data** (phase 2) — revenue/profit by segment (dimensional XBRL).

## Stretch

* **Earnings-call / IR-deck analysis (multimodal)** — ⚠️ data lives *outside*
  EDINET (company IR sites / TDnet). Needs a separate fetcher + a vision LLM.
  Revisit only after confirming a viable, ToS-compliant data source.

## Components

* `src/edinet/client.py` — `fetch_annual_reports`
* `src/parser/history_merger.py` — merge + restatement policy
* `src/parser/xbrl_parser.py` — cash-flow candidate elements; segment handling
* `src/models/financial_history.py` — long-history + cash-flow series
* `src/models/segment.py` — `SegmentData`

## Milestones

* [x] M2.1 — multi-filing fetch + download cache (`client.fetch_annual_reports`,
  jump-scan). Verified live: TEL → 4 filings, 8-yr span (2018–2025).
* [x] M2.2 — history merge + restatement/split policy (`src/parser/history_merger.py`,
  `src/longhistory.py`). Verified live: correctly reconciled TEL's 3:1 split
  (April 2024) — per-share restatements flagged at exactly ×3, split boundaries marked.
* [x] M2.3 — cash-flow + capex. Operating/investing/financing CF + cash +
  FCF proxy (= OCF + investing CF) are in the 5-year summary → flow into
  history, long-history, and a new "Cash flow" chart panel automatically.
  Capex (`PurchaseOfPropertyPlantAndEquipmentInvCF`) extracted as a single-period
  `FinancialMetrics.capex` field (not in the 5 coverage metrics). Verified live on TEL.
* [~] M2.4 — segments — **ATTEMPTED & PARKED** (2026-06-19). Built business-segment
  extraction (`OperatingSegmentsAxis`) + label resolution from the `_lab-en.xml`
  linkbase. Spike findings: structured segment data is **unreliable** — works
  cleanly for some filers (Advantest: 3 named segments) but (a) coverage is
  inconsistent across filers *and years* (TEL tags segments in its FY2022 `.xbrl`
  but **not** FY2025 — moved to inline-XBRL `.htm`, which we don't parse), and
  (b) label quality varies (SCREEN → abbreviations / empty). Reliable coverage
  would need a new iXBRL `.htm` parser + per-filer label normalization, with
  residual gaps. Not worth it vs. the standardized summary data. Experimental
  code removed. Geographic segments: not dimensionally tagged at all (earlier finding).
* [x] M2.5 — benchmark extended: cash-flow coverage, capex presence, and a
  **cash-flow reconciliation** (Δcash ≈ operating+investing+financing CF;
  residual ≈ FX effect, tolerance 25%). New `CF`/`CF-rec` table columns +
  `mean_cash_flow_coverage` aggregate. Verified: real TEL FY2025 reconciles at 1.1% residual.
* [~] M2.6 (stretch) — IR/earnings multimodal. **Built** (`src/presentation.py`,
  `src/models/presentation.py`, `llm.analyze_pdf_json`). Scope = **bring-your-own-PDF**
  (no scraping — IR decks aren't in EDINET). Uses **Claude native PDF input**
  (requires `ANTHROPIC_API_KEY`; OpenAI would need page-image conversion).
  Cross-references the deck against the XBRL-extracted financials. `IR/` gitignored.
  `python -m src.presentation IR/8035.pdf --ticker 8035`. **DONE — live-verified on
  TEL's FY2026 deck:** extracted forward guidance (H1 FY2027 +33% sales; medium-term
  ¥3T revenue / 35% OP margin / 30% ROE targets) the *filing* doesn't emphasize, and
  the consistency check correctly identified that our XBRL was the prior year (FY2025),
  matched the deck's prior-year column exactly, and **caught a real basis difference**
  (our parent payout 64.1% vs the deck's consolidated 50.1%, reconciled via DPS/EPS).

## Success criteria

* 10–15 yr revenue/EPS/PER history for a company from chained filings, with
  overlaps reconciled and any restatements flagged.
* Cash-flow series extracted and cross-checked.

## Risks / notes

* **Restatements** are the core correctness problem — a later filing may revise an
  earlier year (accounting change, IFRS transition). Policy + discrepancy flag required.
* **Per-share splits** — EDINET restates EPS/BPS for splits but not raw dividends;
  handle consistently across the chained window.
* **Segments** = dimensional XBRL (member contexts); meaningfully harder.
* **Multimodal IR** is the biggest unknown (non-EDINET source) — kept as stretch.
