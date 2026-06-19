# MVP2 Track B — Deeper Data & Longer History

Status: **planned** (starts after Track A)

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

* [ ] M2.1 — multi-filing fetch + cache
* [ ] M2.2 — history merge + restatement/split policy (+ tests with a known restatement)
* [ ] M2.3 — cash-flow + capex extraction
* [ ] M2.4 — segments
* [ ] M2.5 — extend benchmark consistency checks to new fields
* [ ] M2.6 (stretch) — IR/earnings multimodal

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
