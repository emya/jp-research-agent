# CLAUDE.md

## Project Overview

JP Research Agent is a research prototype that converts Japanese public company filings into investor-oriented research memos.

The MVP focuses on:

* EDINET ingestion
* XBRL financial extraction
* Filing section retrieval
* Research memo generation

This project prioritizes correctness and transparency over UI polish.

---

## Core Principle

Prefer structured financial data over LLM extraction whenever possible.

Bad:

```python
llm.extract_revenue(pdf)
```

Good:

```python
xbrl_parser.extract_revenue()
```

LLMs should be used for reasoning and summarization, not for extracting values already available in structured form.

---

## MVP Workflow

### Step 1

Download filing from EDINET.

Output:

```python
FilingDocument
```

### Step 2

Extract structured financial metrics.

Output:

```python
FinancialMetrics
```

Fields:

```python
revenue
operating_income
net_income
assets
equity
```

### Step 3

Extract textual sections.

Target sections:

* Management Discussion
* Business Risks
* Future Outlook

Output:

```python
FilingSections
```

### Step 4

Generate research memo.

Output:

```python
ResearchMemo
```

Fields:

```python
executive_summary
financial_highlights
key_risks
bull_thesis
bear_thesis
```

---

## Directory Structure

```text
src/

  edinet/
    client.py

  parser/
    xbrl_parser.py
    filing_parser.py

  models/
    financial_metrics.py
    research_memo.py

  research/
    summarizer.py
    thesis_generator.py

  evaluation/
    benchmark.py

tests/

data/
```

---

## Engineering Constraints

### Keep components independent

EDINET ingestion should not depend on LLM code.

Research generation should not depend on EDINET APIs.

### Typed outputs

Use Pydantic models for all intermediate artifacts.

Avoid passing raw dictionaries between components.

### Reproducibility

Generated memos should be saved alongside the extracted source data.

Every conclusion should be traceable back to source filings.

---

## Evaluation (Stretch Goal)

Benchmark across multiple companies.

Metrics:

### Extraction

Compare extracted metrics against XBRL ground truth.

### Summarization

Human evaluation:

* Accuracy
* Completeness
* Usefulness

### Research Quality

Questions:

* Does the memo identify major risks?
* Does the memo explain earnings changes?
* Does the memo provide plausible investment arguments?

---

## Non-Goals

For the MVP:

* No trading signals
* No stock recommendations
* No portfolio construction
* No forecasting

Focus exclusively on understanding public company disclosures.

