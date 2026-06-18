# JP Research Agent

An AI research agent that transforms Japanese public company disclosures into investor-oriented research memos.

---

## Motivation

I have a friend who's originally from Japan and actively researches and invests in equities.

During a conversation about companies involved in the semiconductor supply chain, she mentioned something that surprised me:

> Even as a native Japanese speaker, researching Japanese public companies is often frustrating. The information exists, but it is fragmented across EDINET filings, annual reports, earnings presentations, and company investor-relations websites.

At first, I assumed this was primarily a language problem for international investors.

However, the more I looked into it, the more I realized the challenge is broader:

* Japanese company information is highly fragmented.
* Important business context is often buried in lengthy disclosures.
* Historical financial trends are not always easily accessible.
* Understanding what actually changed between reporting periods requires significant manual effort.

The challenge becomes even greater for non-Japanese investors.

This is particularly relevant today because Japanese companies play critical roles in global semiconductor supply chains. Companies such as Tokyo Electron, Advantest, SCREEN Holdings, Lasertec, and Disco are increasingly important to investors worldwide, yet understanding these businesses often requires navigating hundreds of pages of disclosures and financial reports.

This project explores a simple question:

**Can an AI system automatically transform raw Japanese public disclosures into an analyst-style research memo?**

---

## Problem

Japanese public company information is publicly available through:

* EDINET filings
* Annual securities reports
* Earnings presentations
* Investor relations materials

Access, however, is not the same as understanding.

An investor researching a company typically wants answers to questions such as:

* How has revenue evolved over time?
* What drove recent changes in earnings?
* What risks does management emphasize?
* What has changed since the previous filing?
* What are the strongest bull and bear cases for the business?

Today, answering these questions often requires manually reading and synthesizing information across multiple sources.

The goal of this project is to reduce the effort required to reach an initial understanding of a company.

---

## Project Goal

Given a Japanese public company, automatically generate a research memo containing:

* Financial highlights
* Historical trends
* Management commentary summary
* Key risks
* Bull thesis
* Bear thesis

The output is intended to serve as a starting point for further research rather than a replacement for investment analysis.

---

## MVP Scope

### Input

A Japanese listed company.

Example:

```bash
python main.py --ticker 8035
```

(Tokyo Electron)

### Data Sources

* EDINET filings
* XBRL financial statements
* Annual securities reports

### Output

Example:

```text
Tokyo Electron

Revenue Growth
+12.4% YoY

Operating Income Growth
+18.7% YoY

Key Drivers
- Increased semiconductor equipment demand
- Expansion of advanced-node investments

Management Concerns
- Semiconductor cycle volatility
- Geopolitical uncertainty

Bull Thesis
...

Bear Thesis
...
```

---

## Architecture

```text
                EDINET

                   │

        ┌──────────┴──────────┐
        │                     │

        ▼                     ▼

   XBRL Parser         Filing Parser

        │                     │

        ▼                     ▼

Structured Data      Text Sections

        └──────────┬──────────┘
                   │

                   ▼

           Research Agent

                   │

                   ▼

            Research Memo
```

---

## Design Principles

### 1. Prefer Structured Data

Whenever financial metrics are available in XBRL form, use the structured source directly.

The system should not rely on LLM extraction for information that already exists in machine-readable form.

### 2. Use LLMs for Reasoning

LLMs should be used to:

* summarize management commentary
* identify key business drivers
* extract risks
* generate investment theses

rather than perform deterministic extraction tasks.

### 3. Preserve Traceability

Every generated statement should be traceable back to the source filing.

---

## Success Criteria

The MVP is considered successful if it can:

### Financial Extraction

Accurately extract core financial metrics from EDINET filings.

### Research Memo Generation

Produce coherent summaries that help a user understand:

* company performance
* management commentary
* key risks

### Research Utility

Reduce the time required for a user to obtain a first-pass understanding of a company.

---

## Stretch Goal: Research Benchmark

After building the research agent, I plan to evaluate it on a small benchmark of Japanese companies.

Example evaluation questions:

* What were the primary drivers of earnings growth?
* What risks does management identify?
* What changed materially from the previous period?

Potential comparisons:

* GPT-4.1
* Claude
* Gemini

Evaluation dimensions:

* Accuracy
* Completeness
* Reasoning quality
* Cost
* Latency

---

## Limitations

This project is an experimental research prototype.

It does not provide investment advice and should not be used as the sole basis for investment decisions.

---

## Future Work (#TODO: Check later)

* Multi-company comparison
* Earnings-call analysis
* Cross-company semiconductor supply chain mapping
* Financial reasoning benchmark for Japanese disclosures
* Multimodal analysis of charts, tables, and investor presentations
* Agentic research workflows over public filings

