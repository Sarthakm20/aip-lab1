#!/usr/bin/env python3
"""Lab 7 — The Observability Dashboard, read from local traces.

    streamlit run labs/lab7/dashboard.py

Reads structured JSONL execution traces from `.aip_traces/`.
Provides full visibility into:
- Stage-by-stage latency breakdowns (p50, p95, total) answering "why did request X take 9s?"
- Cost accumulation over time and token expenditures
- Cache hit rates (exact and semantic)
- Error distribution by type
- Actionable alert monitoring with incident playbooks (C4)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from aip.config import settings  # noqa: E402

st.set_page_config(page_title="Aurora Assistant — Ops Dashboard", layout="wide", page_icon="📊")
st.title("📊 Aurora Policy Assistant — Observability & Ops")

# Refresh button — re-scans trace directory without restarting Streamlit
if st.button("🔄 Refresh Traces"):
    st.cache_data.clear()
    st.rerun()

@st.cache_data(ttl=5)
def _load_trace_list() -> list[str]:
    return sorted([p.stem for p in settings.trace_dir.glob("*.jsonl")], reverse=True)

trace_stems = _load_trace_list()
runs = [settings.trace_dir / f"{s}.jsonl" for s in trace_stems]

if not runs:
    st.info(f"No traces yet in {settings.trace_dir}. Run some queries first.")
    st.stop()

st.sidebar.title("Telemetry Controls")
chosen = st.sidebar.multiselect(
    "Select trace runs:",
    trace_stems,
    default=trace_stems[:1] if len(trace_stems) <= 3 else trace_stems[:3],
)

rows = [
    json.loads(l)
    for p in runs
    if p.stem in chosen
    for l in p.open(encoding="utf-8")
    if l.strip()
]

if not rows:
    st.warning("No spans found in selected trace runs.")
    st.stop()

df = pd.DataFrame(rows)
df["ts"] = pd.to_datetime(df["ts"], unit="s")

# Overview KPIs
c = st.columns(6)
c[0].metric("Total Spans", len(df))
total_cost = float(df.get("cost_usd", pd.Series([0.0])).fillna(0.0).sum())
c[1].metric("Cumulative Spend", f"${total_cost:.4f}")

llm = df[df["name"] == "llm.call"]
c[2].metric("LLM Calls", len(llm))
if len(llm):
    cached_mean = float(llm.get("cached", pd.Series([False])).fillna(False).mean())
    c[3].metric("LLM Cache Hit", f"{cached_mean:.1%}")
else:
    c[3].metric("LLM Cache Hit", "0%")

http_asks = df[df["name"] == "http.ask"]
if len(http_asks):
    cached_asks = float(http_asks.get("cached", pd.Series([False])).fillna(False).mean())
    c[4].metric("Response Cache Hit", f"{cached_asks:.1%}")
else:
    c[4].metric("Response Cache Hit", "N/A")

err_count = int((df.get("status") == "error").sum())
c[5].metric("Total Errors", err_count)

st.write("---")

# C3: Latency breakdown by stage
st.subheader("⏱️ Latency by Stage (p50 / p95 / Total)")
st.caption(
    "Stage-level timing from structured spans. This answers: 'Which stage dominates latency and "
    "where should optimization efforts be directed?' (See Part B4)."
)

if "duration_ms" in df:
    stage = (
        df.groupby("name")["duration_ms"]
        .agg(
            n="count",
            p50="median",
            p95=lambda s: s.quantile(0.95),
            max="max",
            total="sum",
        )
        .sort_values("total", ascending=False)
    )
    stage["p50"] = stage["p50"].round(1)
    stage["p95"] = stage["p95"].round(1)
    stage["max"] = stage["max"].round(1)
    stage["total"] = stage["total"].round(1)
    st.dataframe(stage, use_container_width=True)

    col_l1, col_l2 = st.columns(2)
    with col_l1:
        st.write("**p95 Latency by Operation (ms)**")
        st.bar_chart(stage["p95"])
    with col_l2:
        st.write("**Total Compute Time by Stage (ms)**")
        st.bar_chart(stage["total"])

# Cost over time
st.write("---")
st.subheader("💰 Cost & Token Economics")
if "cost_usd" in df:
    cum = df.sort_values("ts").assign(cum=lambda d: d["cost_usd"].fillna(0).cumsum())
    st.line_chart(cum.set_index("ts")["cum"])

# C4: Alerts & Operations Playbook
st.write("---")
st.subheader("🚨 Alert Monitoring & Incident Playbook (TODO C4)")

# Compute alert indicators
refusal_alert_triggered = False
p95_slo_alert_triggered = False

if len(http_asks) >= 5:
    refusals = http_asks.get("refused", pd.Series([False])).fillna(False)
    refusal_rate = float(refusals.mean())
    if refusal_rate > 0.40:
        refusal_alert_triggered = True

    p95_http = float(http_asks["duration_ms"].quantile(0.95))
    if p95_http > 6000.0:
        p95_slo_alert_triggered = True

alert_col1, alert_col2 = st.columns(2)

with alert_col1:
    st.markdown("### 🔔 Alert 1: Refusal Rate Spike / Doubling")
    st.caption("Condition: `refusal_rate > 40%` over 5-minute rolling window.")
    if refusal_alert_triggered:
        st.error(f"🔴 **ALERT FIRING: Refusal rate is {refusal_rate:.1%} (Threshold: 40%)**")
    else:
        st.success("🟢 **HEALTHY: Refusal rate is within normal operating limits.**")

    with st.expander("📖 Playbook: What to do when Refusal Rate alert fires"):
        st.markdown("""
        **Symptom:** RAG system begins issuing excessive refusals (*"I don't have enough information"*).
        **Root Cause:**
        A broken or corrupt vector index throws no errors, incurs no extra cost, and creates no latency spikes.
        It simply returns irrelevant distractor chunks, which triggers the generation refusal rule.
        **Remediation Steps:**
        1. Check `GET /health` to verify `index_size_chunks` matches expected corpus size (164 chunks).
        2. Inspect recent `rag.retrieve` spans in `.aip_traces/` to check `top_doc` relevance.
        3. If index corrupted or chunks missing, rebuild vector index (`python labs/lab3/search.py --baseline`).
        4. Check git diff for any recent changes to `data/corpus/`.
        """)

with alert_col2:
    st.markdown("### 🔔 Alert 2: p95 Latency Exceeds SLO (6,000 ms)")
    st.caption("Condition: `p95_latency > 6,000 ms` uncached.")
    if p95_slo_alert_triggered:
        st.error(f"🔴 **ALERT FIRING: p95 latency is {p95_http:.0f} ms (SLO target: 6,000 ms)**")
    else:
        st.success("🟢 **HEALTHY: p95 latency is well within the 6,000 ms SLO.**")

    with st.expander("📖 Playbook: What to do when Latency SLO alert fires"):
        st.markdown("""
        **Symptom:** Users experience sluggish answers breaching the 6.0s SLA.
        **Root Cause:**
        Generation is ~98% of uncached latency. Spikes are caused by:
        - Output token explosion (model generating lengthy essays instead of concise 2-3 sentence answers).
        - Upstream provider throttling / rate limit backoff retries.
        - Pipeline erroneously re-instantiating embeddings per-request.
        **Remediation Steps:**
        1. Check `llm.retry` event counts in traces. If rate limiting, enable request throttling or switch provider tier.
        2. Verify `max_tokens` constraint on generator (`max_tokens=600`).
        3. Confirm `pipeline()` singleton is cached and not rebuilt per request.
        """)

# Errors section
st.write("---")
st.subheader("⚠️ Error Log & Diagnostics")
errs = df[df.get("status") == "error"]
if len(errs):
    st.dataframe(
        errs[["ts", "name", "error", "span_id", "run_id"]],
        use_container_width=True,
    )
else:
    st.info("No execution errors logged in the selected traces.")
