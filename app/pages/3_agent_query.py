"""app/pages/3_agent_query.py"""
from __future__ import annotations
import sys, time
from pathlib import Path
_PROJECT_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT))
import streamlit as st
st.set_page_config(page_title="Agent Query · EcoGraph", page_icon="🤖", layout="wide", initial_sidebar_state="expanded")
from app.theme import apply_theme, section_header
apply_theme()


def theme_toggle():
    label = "Switch to Light Mode" if st.session_state.get("_dark") else "Switch to Dark Mode"
    if st.button(label, use_container_width=True, key="_theme_toggle_btn"):
        st.session_state["_dark"] = not st.session_state.get("_dark", False)
        st.rerun()

if "messages" not in st.session_state: st.session_state["messages"] = []
if "last_state" not in st.session_state: st.session_state["last_state"] = {}

with st.sidebar:
    st.markdown(
        '<div class="sb-brand"><div class="sb-name">EcoGraph</div>'
        '<div class="sb-sub">Agent Query</div></div>',
        unsafe_allow_html=True,
    )
    st.divider()
    st.markdown('<span class="sb-nav-lbl">Example Queries</span>', unsafe_allow_html=True)
    EXAMPLES = [
        "What are the top 5 Scope 3 emission hotspots?",
        "Suggest a 20% emission reduction plan for electronics suppliers.",
        "Are our Chinese suppliers GHG Protocol compliant?",
        "Verify reported emissions for our top steel supplier via satellite.",
        "Which suppliers have the highest reported vs satellite discrepancy?",
    ]
    for ex in EXAMPLES:
        if st.button(ex, use_container_width=True, key=f"ex_{hash(ex)}"):
            st.session_state["prefill"] = ex
    st.divider()
    if st.button("Clear conversation", use_container_width=True):
        st.session_state["messages"] = []
        st.session_state["last_state"] = {}
        st.rerun()
    st.divider()
    st.markdown('<span class="sb-nav-lbl">Pipeline Steps</span>', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:0.82rem;line-height:2">'
        '1. Translate query to Cypher<br>'
        '2. Query knowledge graph<br>'
        '3. Satellite verification<br>'
        '4. Generate mitigation plan<br>'
        '5. Validate<br>'
        '6. Write report'
        '</div>',
        unsafe_allow_html=True,
    )
    st.divider()
    theme_toggle()

def _run_agent(query):
    from ecograph.agents.graph import get_agent
    agent = get_agent()
    return agent.invoke({"query": query, "iteration_count": 0, "errors": []})

st.markdown('<div class="pg-title">Agent Query</div><div class="pg-sub">Multi-agent pipeline · knowledge graph · satellite verification · mitigation planning</div>', unsafe_allow_html=True)

for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prefill = st.session_state.pop("prefill", "")
user_input = st.chat_input("Ask a supply chain question...")
if not user_input and prefill:
    user_input = prefill

if user_input:
    st.session_state["messages"].append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        status_ph = st.empty()
        answer_ph = st.empty()
        _STEPS = ["Translating query...", "Querying knowledge graph...", "Satellite verification...", "Generating mitigation plan...", "Validating...", "Writing report..."]
        prog = st.progress(0)
        for i, step in enumerate(_STEPS):
            status_ph.info(step)
            prog.progress((i + 1) / len(_STEPS))
            time.sleep(0.12)
        try:
            state = _run_agent(user_input)
            st.session_state["last_state"] = state
        except Exception as exc:
            st.error(f"Agent pipeline error: {exc}")
            st.session_state["messages"].append({"role": "assistant", "content": f"⚠️ Error: {exc}"})
            st.stop()
        prog.empty()
        status_ph.empty()
        summary = state.get("data_analyst_summary") or state.get("report_markdown", "")[:800] or "Agent completed but produced no summary."
        answer_ph.markdown(summary)
        st.session_state["messages"].append({"role": "assistant", "content": summary})

state = st.session_state["last_state"]
col_a, col_b = st.columns(2, gap="large")
with col_a:
    if state.get("supply_mitigation_plan"):
        with st.expander("Mitigation Plan", expanded=True):
            plan = state["supply_mitigation_plan"]
            if isinstance(plan, dict):
                recs = plan.get("recommendations", [])
                if recs:
                    import pandas as pd
                    st.dataframe(pd.DataFrame(recs), use_container_width=True)
                else:
                    st.json(plan)
            else:
                st.write(plan)
    if state.get("compliance_violations"):
        with st.expander("Compliance Violations"):
            for v in state["compliance_violations"]:
                st.warning(str(v))
with col_b:
    if state.get("satellite_verification"):
        with st.expander("Satellite Verification", expanded=True):
            sv = state["satellite_verification"]
            if isinstance(sv, dict):
                for k, v in sv.items(): st.markdown(f"**{k}**: {v}")
            else:
                st.write(sv)
    if state.get("citations"):
        with st.expander("Citations"):
            for cit in state["citations"]: st.markdown(f"- {cit}")
if state.get("report_path") and Path(state["report_path"]).exists():
    st.download_button("Download PDF Report", Path(state["report_path"]).read_bytes(), "ecograph_report.pdf", "application/pdf")