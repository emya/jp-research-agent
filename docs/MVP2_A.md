# MVP2 Track A — Peer / Sector Comparison

Status: **DONE** (2026-06-18) — verified live across the 5 semiconductor names.

## Goal

Compare companies within a sector side by side, so an investor can see relative
positioning at a glance: who grows fastest, who's most profitable, who trades at
the lowest earnings multiple. Builds directly on the per-company extraction +
history from MVP1.

## In scope

* Peer-set config (`sectors.json`) — named sectors → ticker lists.
* Comparison engine — run extraction across a peer set, align the latest-year
  metrics, and rank companies per metric.
* Metrics: revenue, revenue growth (YoY), operating margin, net margin, ROE,
  EPS, PER (filing-reported), payout ratio.
* Interactive sector dashboard (`comparison.html`) — latest-year snapshot bars
  + multi-company trend lines (revenue / PER / ROE over the 5-year history).
* Comparison memo — LLM relative-analysis (offline deterministic fallback).
  **Relative observations only — not recommendations** (Non-Goals unchanged).

## Out of scope (here)

* PBR / dividend yield / live valuation — need a price source (Track B / decision layer).
* Cross-sector or factor analysis.

## Components

* `sectors.json`
* `src/models/comparison.py` — `PeerMetric`, `PeerRow`, `PeerComparison`
* `src/comparison.py` — engine + CLI (`python -m src.comparison semiconductors`)
* `src/charts_compare.py` — `build_comparison_html`
* `src/evaluation/benchmark.py` — (later) extend to validate comparison metrics

## Milestones

* [x] M1.1 — models + `sectors.json`
* [x] M1.2 — comparison engine (assemble + rank) with offline tests
* [x] M1.3 — sector dashboard (Plotly) — `src/charts_compare.py`
* [x] M1.4 — comparison memo (LLM + offline fallback)
* [x] M1.5 — CLI + JSON/markdown artifacts (`python -m src.comparison <sector>`)
* [x] M1.6 — run live across the semiconductor set; verified (also surfaced &
  fixed the `Prior1Year*` prior-context bug → YoY now extracts on real filings)

## Success criteria

* `python -m src.comparison semiconductors` produces a ranked table, a
  `comparison.html`, and a `comparison.json` for the 5 semi names.
* Every comparison number is traceable to the per-company extraction.
* Tests pass offline (synthetic ranking + single-company fixture path).

## Risks / notes

* Mixed accounting bases (JGAAP vs IFRS) across peers — metrics must be
  comparable; ordinary income (JGAAP) vs pre-tax (IFRS) differ, so the
  comparison favors revenue/margins/ROE/PER which are consistently available.
* Different fiscal year-ends would make a "latest FY" comparison apples-to-oranges;
  the semi names are all March year-end. Flag when they differ.
