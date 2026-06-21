# JP Research Agent

Turn Japanese public-company disclosures into traceable, investor-oriented research — financials, history, peer comparison, management, and an LLM memo — from the command line.

> **Runs with zero setup.** `docker compose up` opens a web UI at `localhost:8000`; `docker run --rm jp-research-agent` prints a memo from a bundled sample — **both work with no API keys**. Add keys (in the UI or `.env`) for real EDINET data and LLM analysis.

---

## Why this exists

I have a friend who's originally from Japan and actively researches and invests in equities. During a conversation about companies in the semiconductor supply chain, she said something that surprised me:

> Even as a native Japanese speaker, researching Japanese public companies is often frustrating. The information exists, but it is fragmented across EDINET filings, annual reports, earnings presentations, and company investor-relations websites.

At first I assumed this was mainly a language barrier for international investors. But the more I looked, the broader the problem got: the information is public yet **fragmented and buried** in hundreds of pages, historical trends aren't easily accessible, and understanding *what actually changed* between reporting periods takes real manual effort. It's harder still for non-Japanese investors.

And it matters today: semiconductor-supply-chain names — Tokyo Electron, Advantest, SCREEN, Lasertec, Disco — are increasingly important to investors worldwide, yet understanding these businesses means navigating hundreds of pages of disclosures.

**The question this explores:** can a system automatically turn raw Japanese disclosures into an analyst-style first read — *without* fabricating the numbers?

---

## Core principle: structured data over LLM extraction

The defining design choice. Financial figures are pulled **deterministically from XBRL**, never guessed by an LLM. LLMs are used only for what they're good at — summarizing narrative, writing theses, polishing bios. Every number in a memo is **traceable** to the exact XBRL element it came from.

```python
# Bad:  llm.extract_revenue(pdf)
# Good: xbrl_parser.extract()   ->   revenue = jppfs_cor:NetSales @ CurrentYearDuration
```

This makes the output verifiable, and it's why the benchmark below can cross-check the system against itself.

---

## What it does

The commands below use `8035` (Tokyo Electron) as a concrete, copy-pasteable example — it's the bundled sample, so they run with **no keys**. Swap in any 4-digit TSE ticker (with an `EDINET_API_KEY` set) to run against real filings.

| Capability | Command | Source |
|---|---|---|
| **Research memo** (summary, highlights, risks, bull/bear) | `python main.py --ticker 8035` | EDINET XBRL + LLM |
| **5-year financial history + interactive charts** | (included in the memo run) | EDINET XBRL |
| **Long history (10–15 yr) + cash flow** — multi-filing merge with restatement/split detection | `python -m src.longhistory 8035 --years 4` | EDINET XBRL |
| **Valuation metrics** — PER, EPS, BPS, ROE, payout | (in history/charts) | EDINET XBRL |
| **Peer / sector comparison** — ranked table + dashboard | `python -m src.comparison semiconductors` | EDINET XBRL + LLM |
| **Management / board profile** — name, title, age, tenure, shareholding (English) | `python -m src.management 8035 --bio` | EDINET XBRL (+ LLM bio) |
| **Quarterly trend tracking** | `python -m src.quarterly 8035` | J-Quants API |
| **IR-deck analysis** — reads an earnings PDF, cross-checks vs the filing | `python -m src.presentation IR/8035.pdf --ticker 8035` | your PDF + Claude (PDF) |
| **Research benchmark** — extraction accuracy + cross-source consistency + LLM judge | `python -m src.evaluation.benchmark 8035 6857 6920 7735 6146` | EDINET + LLM |

Outputs (memo, JSON, interactive `*.html` charts) are written under `data/output/<ticker>/`. Everything is also available through a **minimal web UI** (`docker compose up` → `localhost:8000`): enter a ticker, optionally paste API keys (kept in memory only, never written to disk) and upload an IR-deck PDF, and view the memo, charts, comparison, management, quarterly, and IR analysis in the browser.

---

## Quickstart

### Option A — Docker (recommended; nothing to install)

**Web UI** — `docker compose up`, then open **http://localhost:8000**. A single page where you:

- enter a **ticker** and pick which sections to run — memo, financial history, management, quarterly, IR deck, peer comparison;
- optionally **paste API keys** in the browser (collapsible section; kept **in memory only**, never written to disk) and **upload an IR-deck PDF**;
- give a **custom peer list** for the comparison (e.g. `7201, 7267`).

The bundled sample (`8035`) runs with **no keys**. With keys set, the memo and management bios are LLM-written **in English** and any ticker works (the first live fetch per ticker takes ~1–2 min).

```bash
docker compose up            # -> http://localhost:8000   (offline sample needs no keys)
docker compose up --build    # IMPORTANT: rebuild after changing/pulling code (otherwise the old image is reused)
docker compose down          # stop
```

**CLI**:

```bash
docker build -t jp-research-agent .

# Offline sample memo — zero keys, zero setup:
docker run --rm jp-research-agent

# Write the memo + interactive chart to your machine:
docker run --rm -v "$PWD/data/output:/app/data/output" jp-research-agent main.py --ticker 8035 --no-llm

# Run the test suite:
docker run --rm jp-research-agent -m unittest discover -s tests

# Real data + LLM memo (needs keys — see "External systems" below):
docker run --rm --env-file .env -v "$PWD/data/output:/app/data/output" \
  jp-research-agent main.py --ticker 8035
```

### Option B — Native (Python 3.10+)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python main.py --ticker 8035 --no-llm        # offline sample
python -m unittest discover -s tests          # tests
```

Put API keys in a `.env` file (`cp .env.example .env`) to enable live data and LLM features.

---

## External systems & data

The repo **stands on its own** — with **no keys**, it runs against a bundled sample and produces a memo with deterministic (template) text. Everything below is *optional* and unlocks more:

| System | Unlocks | Env var | Notes |
|---|---|---|---|
| **EDINET API v2** (JPX/FSA) | Real filings (live XBRL) for any ticker | `EDINET_API_KEY` | No search API → first live fetch scans the daily index (~1–2 min); downloads are cached. |
| **Anthropic** *or* **OpenAI** | LLM-written memos, comparison/benchmark judge, IR-deck reading | `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Without a key, memos fall back to deterministic templates. PDF analysis needs **Anthropic** (native PDF). |
| **J-Quants API v2** (JPX) | Quarterly fundamentals | `JQUANTS_API_KEY` | EDINET dropped ongoing quarterly disclosure in 2024; J-Quants is the structured source. Free tier has a data delay. |
| **An IR-deck PDF** | IR-presentation analysis | — (local file) | Bring your own; IR decks aren't in EDINET. The `IR/` folder is gitignored. |

> **About the bundled sample:** `data/fixtures/8035/` is a **synthetic, illustrative** filing so the project runs with zero setup. Its element names and structure mirror real EDINET filings, but the figures are not authoritative — the output clearly labels it `SAMPLE`. Set `EDINET_API_KEY` for real data.

See the bottom of this README for how to obtain the keys.

---

## Success criteria & how it's measured

The project ships its own **benchmark** (`src/evaluation/benchmark.py`) across companies, on three dimensions:

1. **Extraction accuracy (objective, no LLM)** — coverage of the core metrics, plus a **cross-source consistency check**: each figure appears in *two independent places* in the XBRL (the main statements and the 5-year summary), and the benchmark verifies they agree. A **cash-flow reconciliation** (Δcash ≈ operating + investing + financing CF) further validates the cash-flow extraction.
2. **Research quality (LLM-as-judge)** — does the memo explain the earnings change, identify the real risks, ground its theses, and stay **faithful to the figures** (hallucination check)?
3. **Utility** — reduce the time to a first-pass understanding of a company.

Verified live across the 5 semiconductor names: **100% extraction coverage, 100% cross-source consistency**. Running it against real data is also what surfaced real gaps — an IFRS filer (Advantest) using different element names, and Tokyo Electron's 3-for-1 stock split — which were then fixed/flagged. The benchmark is the mechanism for extending coverage to new sectors.

```bash
python -m src.evaluation.benchmark 8035 6857 6920 7735 6146 --no-judge   # free, objective only
python -m src.evaluation.benchmark 8035 6857 6920 7735 6146              # + LLM judge
```

---

## Architecture

```
EDINET API ──► FilingDocument ──┬──► XBRL Parser ──► FinancialMetrics + FinancialHistory
  (or sample fixture)           └──► Filing Parser ─► FilingSections (MD&A, risks, outlook)
                                                          │
   J-Quants API ──► QuarterlySeries                       ▼
   IR PDF ──► PresentationAnalysis                  Research layer (context + LLM/offline)
   EDINET officers ──► ManagementProfile                  │
                                                          ▼
                                          ResearchMemo · charts.html · comparison · benchmark
```

Typed **Pydantic** models for every intermediate artifact; components are kept independent (EDINET ingestion has no LLM dependency; the research layer has no EDINET dependency). Module map:

```
src/
  edinet/client.py        EDINET v2 ingestion (live + offline fixture), multi-filing fetch
  parser/                 xbrl_parser, filing_parser, history_merger, officer_parser
  models/                 financial_metrics, financial_history, filing, research_memo,
                          comparison, quarterly, management, presentation
  research/               summarizer, thesis_generator, context, llm (Anthropic/OpenAI)
  jquants/client.py       J-Quants v2 (quarterly)
  comparison.py · longhistory.py · management.py · quarterly.py · presentation.py · charts*.py
  evaluation/benchmark.py the success-criteria harness
main.py                   single-company memo CLI
```

---

## Testing & CI

- **41 offline tests** (stdlib `unittest`, no network, no keys) cover extraction, history merge, cash flow, valuation, comparison, quarterly parsing, management, and the benchmark logic.
- **GitHub Actions** runs the suite on every push/PR (Python 3.11 & 3.12), with all keys forced empty so CI never makes live calls.

```bash
python -m unittest discover -s tests
```

---

## Scope & limitations

- **Not investment advice.** A research starting point, not a recommendation engine. No trading signals, no forecasting.
- **Sample data is synthetic.** Zero-key runs use an illustrative fixture (labeled `SAMPLE`); real numbers need `EDINET_API_KEY`.
- **Live fetch is slow.** EDINET has no search-by-company endpoint, so the first live fetch scans the daily index (~1–2 min); results/downloads are cached.
- **Segments: deliberately parked.** Business-segment extraction was attempted and removed — structured segment data proved unreliable (coverage varies by filer *and year*; some lives only in inline-XBRL HTML; labels are inconsistent). Documented in `docs/MVP2_B.md`. This was a judgment call to not ship something untrustworthy.
- **Quarterly** requires a J-Quants key (free tier is delayed). **IR analysis** requires you to supply a PDF and an Anthropic key.

---

## Getting the API keys

- **EDINET v2** — register at the [EDINET API key page](https://api.edinet-fsa.go.jp/api/auth/index.aspx?mode=1). It's old-fashioned: the key appears in a pop-up after email + SMS verification, so use Microsoft Edge or allow pop-ups in Chrome.
- **J-Quants v2** — register (free tier available) at [jpx-jquants.com](https://jpx-jquants.com/en); the dashboard issues an `x-api-key`.
- **Anthropic / OpenAI** — standard API keys from their consoles.

Put them in `.env` (see `.env.example`).

---

_Built as a from-scratch, end-to-end system. Data: EDINET (FSA/JPX) and J-Quants (JPX), both public. LLMs: Anthropic / OpenAI._
