"""Minimal local web UI for the JP Research Agent.

    python -m src.web.app        # -> http://localhost:8000

Pick a ticker, optionally enter API keys / upload an IR deck, and see everything
the engine produces. Runs offline (bundled sample) with no keys.

Security: API keys entered here are kept in memory for the running process only —
never written to disk or logged. This is a LOCAL, single-user tool.
"""
from __future__ import annotations

import os
import traceback
from pathlib import Path

from flask import Flask, abort, render_template_string, request, send_from_directory

from ..comparison import build_comparison, comparison_memo
from ..charts_compare import build_comparison_html
from ..edinet.client import EDINETClient, EDINETError
from ..jquants.client import JQuantsClient
from ..management import add_bios, build_profile
from ..pipeline import PipelineError, run as run_pipeline
from ..presentation import analyze_presentation
from ..quarterly import build_quarterly
from ..research import llm

_REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = _REPO_ROOT / "data" / "output"
UPLOADS = OUTPUT / "uploads"
SECTORS = {"semiconductors": ["8035", "6857", "6920", "7735", "6146"]}

_KEYS = ["EDINET_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "JQUANTS_API_KEY"]
CONFIG: dict = {}  # in-memory keys for this process only

app = Flask(__name__)


def _apply_keys() -> None:
    for k in _KEYS:
        if CONFIG.get(k):
            os.environ[k] = CONFIG[k]


def _rel(path) -> str:
    return str(Path(path).resolve().relative_to(OUTPUT.resolve()))


@app.route("/file/<path:rel>")
def serve_file(rel):
    target = (OUTPUT / rel).resolve()
    if not str(target).startswith(str(OUTPUT.resolve())):
        abort(403)
    return send_from_directory(OUTPUT, rel)


@app.route("/")
def index():
    have = {k: bool(CONFIG.get(k) or os.environ.get(k)) for k in _KEYS}
    return render_template_string(INDEX_HTML, have=have, sectors=list(SECTORS))


@app.route("/analyze", methods=["POST"])
def analyze():
    # 1) stash any keys the user entered (in memory only)
    for k in _KEYS:
        v = (request.form.get(k) or "").strip()
        if v:
            CONFIG[k] = v
    _apply_keys()

    ticker = (request.form.get("ticker") or "").strip()
    sections = set(request.form.getlist("sections"))
    if not ticker:
        return render_template_string(INDEX_HTML, have={k: bool(CONFIG.get(k)) for k in _KEYS},
                                      sectors=list(SECTORS), error="Please enter a ticker.")

    client = EDINETClient(verbose=False)
    blocks = []  # (title, html)

    def safe(title, fn):
        try:
            blocks.append((title, fn()))
        except (EDINETError, PipelineError) as e:
            blocks.append((title, f"<p class='err'>{e}</p>"))
        except Exception as e:  # noqa: BLE001
            blocks.append((title, f"<p class='err'>Unexpected error: {e}</p><pre>{traceback.format_exc()[-600:]}</pre>"))

    result = {}
    if {"memo", "history"} & sections:
        def _run():
            result["r"] = run_pipeline(ticker, client=client, use_llm=None, write=True, make_charts=True)
            return ""
        safe("_pipeline", _run)

    if "memo" in sections and "r" in result:
        blocks.append(("Research Memo", _memo_html(result["r"]["memo"])))
    if "history" in sections and "r" in result:
        charts = result["r"]["artifacts"].get("charts_html")
        blocks.append(("Financial History", _iframe(charts) if charts else "<p class='err'>No chart.</p>"))
    if "management" in sections:
        def _mg():
            p = build_profile(ticker, client=client)
            # Auto-generate English bios when an LLM key is set (the as-filed career
            # history is Japanese; the bio is the English translation/summary).
            if llm.llm_available():
                add_bios(p.representatives())
            return _mgmt_html(p, have_llm=llm.llm_available())
        safe("Management / Board", _mg)
    if "quarterly" in sections:
        safe("Quarterly Trend", lambda: _quarterly_html(ticker))
    if "ir" in sections:
        safe("IR Presentation", lambda: _ir_html(ticker, client))
    if "comparison" in sections:
        safe("Peer Comparison", lambda: _comparison_html(ticker, client))

    blocks = [b for b in blocks if b[0] != "_pipeline"]
    source = ""
    if "r" in result:
        f = result["r"]["filing"]
        source = f"{f.source} ({f.data_kind})"
    return render_template_string(RESULTS_HTML, ticker=ticker, blocks=blocks, src_label=source)


# ----------------------------------------------------------------- renderers
def _iframe(abs_path) -> str:
    return f"<iframe src='/file/{_rel(abs_path)}' style='width:100%;height:1100px;border:0'></iframe>"


def _memo_html(memo) -> str:
    def ul(items):
        return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"
    caveat = f"<p class='caveat'>⚠️ {memo.data_caveat}</p>" if memo.data_caveat else ""
    return (
        f"{caveat}"
        f"<h4>Executive Summary</h4><p>{memo.executive_summary}</p>"
        f"<h4>Financial Highlights</h4>{ul(memo.financial_highlights)}"
        f"<h4>Key Risks</h4>{ul(memo.key_risks)}"
        f"<h4>Bull Thesis</h4><p>{memo.bull_thesis}</p>"
        f"<h4>Bear Thesis</h4><p>{memo.bear_thesis}</p>"
        f"<p class='muted'>Generation: {memo.generation_mode}</p>"
    )


def _mgmt_html(p, have_llm=False) -> str:
    import html as _html
    rows = p.representatives() or p.officers
    note = ("English career bios are generated from the filing's career record below."
            if have_llm else
            "Set an Anthropic/OpenAI key for English career bios; the career history "
            "below is shown as filed (Japanese).")
    out = [f"<p class='muted'>{len(p.officers)} officers, "
           f"{len(p.representatives())} representative director(s). {note}</p>"]
    for o in rows:
        star = " ⭐" if o.is_representative else ""
        meta = []
        if o.age is not None:
            meta.append(f"Age {o.age}" + (f" (DOB {o.date_of_birth})" if o.date_of_birth else ""))
        if o.shares_held is not None:
            meta.append(f"{o.shares_held:,.0f} shares")
        if o.term_of_office:
            meta.append(f"Term {_html.escape(o.term_of_office)}")
        meta_line = f"<br><span class='muted'>{' · '.join(meta)}</span>" if meta else ""
        # English bio (LLM, grounded in the career summary) when present; always
        # offer the as-filed career history (in the filing's own language).
        bio = f"<p><i>{_html.escape(o.bio)}</i></p>" if o.bio else ""
        career = ""
        if o.career_summary:
            career = ("<details><summary>Career history (as filed)</summary>"
                      f"<p class='muted' style='white-space:pre-wrap;margin:6px 0 0'>"
                      f"{_html.escape(o.career_summary)}</p></details>")
        out.append(
            f"<div class='card'><b>{_html.escape(o.name_en or o.name)}</b>{star} "
            f"<span class='muted'>({_html.escape(o.name)})</span><br>"
            f"{_html.escape(o.title_en or o.title)}{meta_line}{bio}{career}</div>"
        )
    return "".join(out)


def _quarterly_html(ticker) -> str:
    jq = JQuantsClient()
    if not jq.configured:
        return "<p class='err'>Quarterly needs a J-Quants API key (enter it above).</p>"
    s = build_quarterly(ticker, client=jq)
    if not s.has_data():
        return "<p class='err'>No quarterly data returned.</p>"
    rows = "".join(
        f"<tr><td>{p.label}</td><td>{_b(p.revenue)}</td><td>{_b(p.revenue_q)}</td>"
        f"<td>{_b(p.operating_profit_q)}</td><td>{_b(p.net_income)}</td></tr>" for p in s.points)
    return ("<table><tr><th>Period</th><th>Rev (cum)</th><th>Rev (Q)</th><th>OP (Q)</th><th>Net (cum)</th></tr>"
            f"{rows}</table>")


def _ir_html(ticker, client) -> str:
    pdf = UPLOADS / f"{ticker}.pdf"
    if "pdf" in request.files and request.files["pdf"].filename:
        UPLOADS.mkdir(parents=True, exist_ok=True)
        request.files["pdf"].save(str(pdf))
    if not pdf.exists():
        return "<p class='err'>Upload an IR-deck PDF to analyze.</p>"
    if not llm.anthropic_available():
        return "<p class='err'>IR analysis needs an Anthropic API key (enter it above).</p>"
    a = analyze_presentation(str(pdf), ticker=ticker, client=client)
    def ul(items):
        return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"
    return (f"<p class='caveat'>⚠️ LLM read of the deck — verify against the filing.</p>"
            f"<h4>Summary</h4><p>{a.summary}</p>"
            f"<h4>Guidance & Targets</h4>{ul(a.guidance_and_targets)}"
            f"<h4>Key Messages</h4>{ul(a.key_messages)}"
            f"<h4>Consistency with Filing</h4><p>{a.consistency_with_filing}</p>")


def _comparison_html(ticker, client) -> str:
    import re as _re
    raw = (request.form.get("peers") or "").strip()
    peers = [t for t in _re.split(r"[,\s]+", raw) if t]
    if peers:
        tickers, sector = list(dict.fromkeys([ticker] + peers)), "custom"
    else:
        sector = next((s for s, ts in SECTORS.items() if ticker in ts), None)
        tickers = SECTORS.get(sector, [])
    if len(tickers) < 2:
        return ("<p class='err'>Peer comparison needs at least two companies. Enter peer "
                "tickers (comma-separated) in the <b>Peers</b> box, e.g. <code>6857, 6920, 7735</code>. "
                "Each peer is a separate live EDINET fetch, so this can take a few minutes.</p>")
    comp, histories, errors = build_comparison(tickers, sector=sector or "custom", client=client)
    from ..models.comparison import METRIC_LABEL
    from ..comparison import fmt_metric
    head = "".join(f"<th>{METRIC_LABEL[k]}</th>" for k in comp.metric_order)
    rows = ""
    for r in comp.rows:
        cells = "".join(f"<td>{fmt_metric(r.get(k)) if r.get(k) else '—'}</td>" for k in comp.metric_order)
        rows += f"<tr><td><b>{r.ticker}</b><br><span class='muted'>{r.company[:18]}</span></td>{cells}</tr>"
    out = f"<table><tr><th>Company</th>{head}</tr>{rows}</table>"
    if errors:
        out += "<p class='err'>Could not fetch: " + ", ".join(
            f"{e['ticker']} ({e['error'][:60]})" for e in errors) + "</p>"
    path = build_comparison_html(comp, histories, OUTPUT / "comparison" / (sector or "custom") / "comparison.html")
    if path and len(comp.rows) >= 2:
        out += _iframe(path)
    return out


def _b(v):
    return f"¥{v/1e9:.1f}B" if v is not None else "—"


# ----------------------------------------------------------------- templates
_STYLE = """
<style>
 body{font:15px/1.55 -apple-system,system-ui,sans-serif;max-width:1024px;margin:24px auto;padding:0 16px;color:#1a1a1a}
 h1{margin-bottom:4px} .muted{color:#888;font-size:13px} .caveat{color:#b15c00;background:#fff7e6;padding:8px;border-radius:6px}
 .err{color:#b00020} fieldset{border:1px solid #ddd;border-radius:8px;margin:14px 0;padding:12px}
 legend{font-weight:600;padding:0 6px} label{display:inline-block;margin:4px 12px 4px 0}
 input[type=text],input[type=password]{width:100%;padding:7px;margin:3px 0;border:1px solid #ccc;border-radius:6px}
 button{background:#1a1a1a;color:#fff;border:0;padding:10px 18px;border-radius:8px;font-size:15px;cursor:pointer}
 .grid{display:grid;grid-template-columns:1fr 1fr;gap:8px} details summary{cursor:pointer;font-weight:600}
 .card{border:1px solid #eee;border-radius:8px;padding:10px;margin:8px 0}
 table{border-collapse:collapse;width:100%;font-size:13px} th,td{border:1px solid #eee;padding:5px 7px;text-align:right}
 th:first-child,td:first-child{text-align:left} section{border-top:2px solid #eee;margin-top:22px;padding-top:8px}
 #spin{display:none;margin-top:10px;color:#888}
</style>
"""

INDEX_HTML = _STYLE + """
<h1>JP Research Agent</h1>
<p class="muted">Type a ticker and see the analysis. Runs offline on a bundled sample (ticker 8035) with no keys.</p>
{% if error %}<p class="err">{{error}}</p>{% endif %}
<form method="post" action="/analyze" enctype="multipart/form-data" onsubmit="document.getElementById('spin').style.display='block'">
  <fieldset><legend>Ticker</legend>
    <input type="text" name="ticker" placeholder="e.g. 8035" value="8035" style="width:200px">
    <span class="muted">offline sample only has 8035; other tickers need an EDINET key</span>
  </fieldset>
  <fieldset><legend>Sections</legend>
    <label><input type="checkbox" name="sections" value="memo" checked> Memo</label>
    <label><input type="checkbox" name="sections" value="history" checked> Financial history</label>
    <label><input type="checkbox" name="sections" value="management" checked> Management</label>
    <label><input type="checkbox" name="sections" value="quarterly"> Quarterly (needs J-Quants)</label>
    <label><input type="checkbox" name="sections" value="ir"> IR deck (upload below)</label>
    <label><input type="checkbox" name="sections" value="comparison"> Peer comparison (slow)</label>
    <br><label style="display:block">Peers for comparison (comma-separated tickers)
      <input type="text" name="peers" placeholder="e.g. 6857, 6920, 7735 — each is a separate live fetch"></label>
  </fieldset>
  <details><summary>API keys (optional — kept in memory only, never saved)</summary>
    <div class="grid">
      {% for k in ['EDINET_API_KEY','ANTHROPIC_API_KEY','OPENAI_API_KEY','JQUANTS_API_KEY'] %}
      <div><label>{{k}}{% if have[k] %} <span class="muted">(set)</span>{% endif %}</label>
        <input type="password" name="{{k}}" placeholder="{% if have[k] %}already set — leave blank to keep{% else %}paste key{% endif %}"></div>
      {% endfor %}
    </div>
  </details>
  <fieldset><legend>IR deck PDF (optional)</legend>
    <input type="file" name="pdf" accept="application/pdf">
  </fieldset>
  <button type="submit">Analyze</button>
  <div id="spin">Running… live EDINET data can take a minute or two.</div>
</form>
"""

RESULTS_HTML = _STYLE + """
<p><a href="/">&larr; back</a></p>
<h1>{{ticker}}{% if src_label %} <span class="muted">— {{src_label}}</span>{% endif %}</h1>
{% for title, html in blocks %}
  <section><h2>{{title}}</h2>{{ html|safe }}</section>
{% endfor %}
"""


def main():
    UPLOADS.mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), threaded=True)


if __name__ == "__main__":
    main()
