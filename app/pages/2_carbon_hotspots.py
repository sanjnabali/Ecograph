"""app/pages/2_carbon_hotspots.py"""
from __future__ import annotations
import sys
from pathlib import Path
_PROJECT_ROOT = Path(__file__).parent[2]
sys.path.insert(0, str(_PROJECT_ROOT /"src"))
sys.path.insert(0, str(_PROJECT_ROOT ))
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Carbon Hotspots - Ecograph", layout="wide")

from app.theme import apply_theme, section_header, empty_state, badfe


apply_theme()

def theme_toggle():
    label = "Switch to Light Mode" if st.session_state.get("_dark") else "Switch to Dark Mode"
    if st.button(label, use_container_width=True, key="_theme_toggle_btn"):
        st.session_state["_dark"] = not st.session_state.get("_dark", False)
        st.rerun()

# - Sidebar
with st.sidebar:
    st.markdown(
        '<div class="sb-brand">'
        '<div class="sb-icon">▲</div>'
        '<div class="sb-name">Carbon Hotspots</div>'
        '<div class="sb-sub">Emission tracking & validation</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.divider()
    st.markdown('<span class="sb-nav-lbl">NAVIGATION</span>', unsafe_allow_html=True)
    st.page_link("main.py", label="🏠 Overview")
    st.page_link("pages/1_supply_chain_map.py", label="🗺️ Supply Chain Map")
    st.page_link("pages/2_carbon_hotspots.py", label="🔥 Carbon Hotspots")
    st.page_link("pages/3_agent_query.py", label="💬 Agent Query")
    st.page_link("pages/4_audit_trail.py", label="📋 Audit Trail")
    st.page_link("pages/5_reports.py", label="📊 Reports")
    st.divider()
    
    st.markdown('<span class="sb-nav-lbl">FILTERS</span>', unsafe_allow_html=True)
    top_n = st.slider("Top N suppliers", 5, 50, 15)
    show_verified = st.checkbox("Satellite-verified only", value=False)
    flag_only = st.checkbox("Discrepancy flags only", value=False)
    
    st.divider()
    st.markdown('<span class="sb-nav-lbl">STATUS KEY</span>', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:0.82rem;line-height:2.1">'
        '<span style="color:#22C55E">●</span> <b>Verified</b> - Satellite confirmed<br>'
        '<span style="color:#94A3B8">●</span> <b>No Data</b> - Report only<br>'
        '<span style="color:#EF4444">●</span> <b>Discrepancy</b> - &gt;20% variance'
        '</div>',
        unsafe_allow_html=True,
    )
    st.divider()
    theme_toggle()
    st.divider()
    st.caption("Real-time monitoring")


@st.cache_data(ttl=120, show_spinner="Loading hotspot data...")
def _load(limit):
    try:
        from ecograph.knowledge_graph.neo4j_client import get_neo4j_client
        db = get_neo4j_client()
        rows = db.execute_read(
            "MATCH (s:Supplier) WHERE s.co2_scope3 IS NOT NULL OPTIONAL MATCH (s)-[:HAS_OBSERVATION]->(obs:Observation) WHERE obs.metric = 'co2_flux_tonnes_per_year' WITH s, avg(obs.value) AS sat_co2 RETURN s.entity_id AS name, s.country AS country, s.co2_scope3 AS reported_co2, sat_co2 AS satellite_co2, s.discrepancy_flag AS discrepancy_flag ORDER BY s.co2_scope3 DESC  LIMIT $lim",
            {"lim": limit},
        )
        df = pd.DataFrame(rows)
        if df.empty: return df
        df["reported_co2"] = pd.to_numeric(df["reported_co2"], errors="coerce")
        df["satellite_co2"] = pd.to_numeric(df["satellite_co2"], errors="coerce")
        def _disc(row):
            r, s = row["reported_co2"], row["satellite_co2"]
            if pd.isna(r) or pd.isna(s) or max(r,s)==0: return None
            return abs(r-s)/max(r,s)*100
        df["discrepancy_pct"] = df.apply(_disc, axis=1)
        def _status(row):
            if pd.isna(row["satellite_co2"]): return "No Data"
            if row.get("discrepancy_pct", 0) > 20: return "Discrepancy flagged"
            return "Verified"
        df["status"] = df.apply(_status, axis=1)
        return df
    except Exception as exc:
        st.error(f"Neo4j error: {exc}")
        return pd.DataFrame()

#
# PAGE HEADER
#

st.markdown(
    '<div class="dashboard-hero">'
    '<div class="hero-badge">EMISSIONS TRACKING</div>'
    '<div class="pg-title">Carbon Hotspots</div>'
    '<div class="pg-sub">Ranked emission analysis with satellite cross-validation and discrepancy detection</div>'
    '</div>',
    unsafe_allow_html=True,
)

st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)

df = _load(top_n)
if df.empty:
    empty_state("⚠️", "No data available", "Run the pipeline to populate supplier CO₂ data.")
    st.stop()

if show_verified: df = df[df["status"] == "Verified"]
if flag_only: df = df[df["status"] == "Discrepancy flagged"]

if df.empty:
    empty_state("🔍", "No results match your filters", "Try adjusting the sidebar filters.")
    st.stop()

#
# KPI METRICS
#

total = df["reported_co2"].sum()
verified_count = (df["status"]=="Verified").sum()
discrepancy_count = (df["status"]=="Discrepancy flagged").sum()

k1, k2, k3, k4 = st.columns(4, gap="medium")

with k1:
    st.markdown(
        f'<div class="kpi-card kpi-info">'
        f'<div class="kpi-label">SUPPLIERS ANALYZED</div>'
        f'<div class="kpi-value">{len(df)}</div>'
        f'<div class="kpi-unit">entities tracked</div>'
        f'<div class="kpi-change neutral">from top {top_n}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

with k2:
    total_label = f"{total/1e9:.2f}B" if total >= 1e9 else f"{total/1e6:.1f}M"
    st.markdown(
        f'<div class="kpi-card kpi-primary">'
        f'<div class="kpi-label">TOTAL SCOPE 3</div>'
        f'<div class="kpi-value">{total_label}</div>'
        f'<div class="kpi-unit">tCO₂e</div>'
        f'<div class="kpi-change neutral">aggregated emissions</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

with k3:
    st.markdown(
        f'<div class="kpi-card kpi-success">'
        f'<div class="kpi-label">SATELLITE VERIFIED</div>'
        f'<div class="kpi-value">{verified_count}</div>'
        f'<div class="kpi-unit">of {len(df)} suppliers</div>'
        f'<div class="kpi-change positive">✓ Cross-validated</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

with k4:
    st.markdown(
        f'<div class="kpi-card kpi-warning">'
        f'<div class="kpi-label">DISCREPANCY FLAGS</div>'
        f'<div class="kpi-value">{discrepancy_count}</div>'
        f'<div class="kpi-unit">&gt;20% variance</div>'
        f'<div class="kpi-change {"negative" if discrepancy_count > 0 else "neutral"}">{"⚠️ Requires review" if discrepancy_count > 0 else "✓ All clear"}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)

#
# ALERT BANNER
#

if discrepancy_count > 0:
    st.markdown(
        f'<div class="alert-banner warning">'
        f'<div class="alert-icon">⚠️</div>'
        f'<div class="alert-content">'
        f'<div class="alert-title">Discrepancy Alert</div>'
        f'<div class="alert-text">{discrepancy_count} suppliers show significant variance (&gt;20%) '
        f'between reported and satellite-validated emissions. Manual review recommended.</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

#
# EMISSIONS RANKING CHART
#

section_header("SCOPE 3 EMISSIONS RANKING", level=2)

import plotly.express as px
import plotly.graph_objects as go

color_map = {"Verified": "#22C55E", "No satellite data": "#94A3B8", "Discrepancy flagged": "#EF4444"}
chart_df = df.sort_values("reported_co2", ascending=True).tail(top_n)

fig = px.bar(chart_df, x="reported_co2", y="name", orientation="h", color="status",
             color_discrete_map=color_map,
             labels={"reported_co2": "Scope 3 Emissions (tCO₂e)", "name": ""},
             template="plotly_white")

fig.update_layout(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=10, r=30, t=10, b=40),
    height=max(380, len(chart_df)*35),
    font=dict(family="Inter, sans-serif", size=11, color="#CBD5E1"),
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
        title_text="",
        font=dict(size=11)
    ),
    xaxis=dict(
        gridcolor="rgba(255,255,255,0.05)",
        zeroline=False,
    ),
    yaxis=dict(gridcolor="rgba(0,0,0,0)")
)

fig.update_traces(marker_line_width=0)
st.plotly_chart(fig, use_container_width=True, key="ranking_chart")

st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)

#
# SCOPE 1/2/3 BREAKDOWN
#

try:
    from ecograph.knowledge_graph.neo4j_client import get_neo4j_client
    db = get_neo4j_client()
    scope_rows = db.execute_read(
        "MATCH (s:Supplier)-[:HAS_OBSERVATION]->(obs:Observation) WHERE obs.metric IN ['co2_scope1', 'co2_scope2', 'co2_scope3'] RETURN coalesce(s.name, s.entity_id) AS name, obs.metric AS metric, obs.value AS value ORDER BY name",
        {},
    )
    if scope_rows:
        scope_df = pd.DataFrame(scope_rows)
        scope_df["value"] = pd.to_numeric(scope_df["value"], errors="coerce")
        pivot = scope_df.pivot_table(index="name", columns="metric", values="value", aggfunc="mean").reset_index()
        pivot = pivot.sort_values("co2_scope3", ascending=False).head(10)
        
        section_header("SCOPE 1 / 2 / 3 BREAKDOWN - TOP 10", level=2)
        
        scope_cols = [c for c in ["co2_scope1", "co2_scope2", "co2_scope3"] if c in pivot.columns]
        fig2 = go.Figure()
        
        for sc, col, lbl in [
            ("co2_scope1", "#3B82F6", "Scope 1"),
            ("co2_scope2", "#8B5CF6", "Scope 2"),
            ("co2_scope3", "#EF4444", "Scope 3")
        ]:
            if sc in pivot.columns:
                fig2.add_trace(go.Bar(name=lbl, x=pivot["name"], y=pivot[sc], marker_color=col))
                
        fig2.update_layout(
            barmode="stack",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=400,
            margin=dict(l=10, r=10, t=20, b=80),
            font=dict(family="Inter, sans-serif", size=11, color="#CBD5E1"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            xaxis=dict(gridcolor="rgba(255,255,255,0.05)", tickangle=-35),
            yaxis=dict(gridcolor="rgba(255,255,255,0.05)", title="tCO₂e")
        )
        
        st.plotly_chart(fig2, use_container_width=True, key="scope_breakdown")
        st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)
except Exception:
    pass

#
# SUPPLIER DETAIL TABLE
#

section_header("SUPPLIER DETAIL TABLE", level=2)

disp = df[["name", "country", "reported_co2", "satellite_co2", "discrepancy_pct", "status"]].copy()
disp.columns = ["Supplier", "Country", "Reported CO₂ (tCO₂e)", "Satellite CO₂ (tCO₂e)", "Discrepancy %", "Status"]

for c in ["Reported CO₂ (tCO₂e)", "Satellite CO₂ (tCO₂e)"]:
    disp[c] = disp[c].apply(lambda x: f"{x:,.0f}" if pd.notna(x) else "-")

disp["Discrepancy %"] = disp["Discrepancy %"].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "-")

# Add status badges
def status_badge(status):
    if status == "Verified":
        return "✓ Verified"
    elif status == "Discrepancy flagged":
        return "⚠️ Flagged"
    else:
        return "➖ No Data"

disp["Status"] = disp["Status"].apply(status_badge)

st.dataframe(disp, use_container_width=True, hide_index=True, height=400)

st.markdown("<div style='margin-top:1rem'></div>", unsafe_allow_html=True)

# Download button
col_a, col_b, col_c = st.columns([1, 1, 2])
with col_a:
    st.download_button(
        "📥 Download CSV",
        df.to_csv(index=False).encode(),
        "carbon_hotspots.csv",
        "text/csv",
        use_container_width=True,
    )

with col_b:
    st.download_button(
        "📥 Download JSON",
        df.to_json(orient="records", indent=2).encode(),
        "carbon_hotspots.json",
        "application/json",
        use_container_width=True,
    )

st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)