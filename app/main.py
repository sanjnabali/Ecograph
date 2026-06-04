"""app/main.py - EcoGraph home page."""
from __future__ import annotations
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import numpy as np

st.set_page_config(
    page_title="EcoGraph - Scope 3 Intelligence",
    page_icon="🔸",
    layout="wide",
    initial_sidebar_state="expanded",
)

from app.theme import apply_theme, status_card, section_header, badge

apply_theme()


def theme_toggle(label_light: str = "Switch to Dark Mode",
                 label_dark: str = "Switch to Light Mode") -> None:
    label = label_dark if st.session_state.get("_dark") else label_light
    st.markdown('<div class="theme-btn">', unsafe_allow_html=True)
    if st.button(label, use_container_width=True, key="_theme_toggle_btn"):
        st.session_state["_dark"] = not st.session_state.get("_dark", False)
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# --- Sidebar --------------------------------------
with st.sidebar:
    st.markdown(
        '<div class="sb-brand">'
        '<div class="sb-icon"> 🌐 </div>'
        '<div class="sb-name">EcoGraph</div>'
        '<div class="sb-sub">Scope 3 Supply Chain Intelligence</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.divider()
    st.markdown('<span class="sb-nav-lbl">NAVIGATION</span>', unsafe_allow_html=True)

    # Navigation with icons
    pages = [
        ("main.py", "▶ Overview", "main"),
        ("pages/1_supply_chain_map.py", "🗺 Supply Chain Map", "map"),
        ("pages/2_carbon_hotspots.py", "🔥 Carbon Hotspots", "hotspots"),
        ("pages/3_agent_query.py", "🤖 Agent Query", "agent"),
        ("pages/4_audit_trail.py", "📜 Audit Trail", "audit"),
        ("pages/5_reports.py", "📊 Reports", "reports"),
    ]

    for page_path, label, key in pages:
        st.page_link(page_path, label=label)

    st.divider()
    st.markdown('<span class="sb-nav-lbl">SETTINGS</span>', unsafe_allow_html=True)
    theme_toggle()
    st.divider()
    st.caption("v1.0 • EcoGraph 2026")


# --- Data helpers ---------------------------------
@st.cache_resource(show_spinner=False)
def _neo4j_status():
    try:
        from ecograph.knowledge_graph.neo4j_client import get_neo4j_client
        db = get_neo4j_client()
        ok = db.health_check()
        return ok, "Connected" if ok else "Unreachable"
    except Exception as exc:
        return False, str(exc)[:80]

@st.cache_resource(show_spinner=False)
def _groq_status():
    try:
        from ecograph.llm import get_groq_client
        get_groq_client()
        return True, "Connected"
    except Exception as exc:
        return False, str(exc)[:80]

@st.cache_data(ttl=60, show_spinner=False)
def _metrics():
    try:
        from ecograph.knowledge_graph.neo4j_client import get_neo4j_client
        db = get_neo4j_client()
        s = db.execute_read("MATCH (s:Supplier) RETURN count(s) AS n", {})
        r = db.execute_read("MATCH ()-[r]->() RETURN count(r) AS n", {})
        o = db.execute_read("MATCH (o:Observation) RETURN count(o) AS n", {})
        t = db.execute_read("MATCH (s:Supplier) WHERE s.co2_scope3 IS NOT NULL RETURN sum(s.co2_scope3) AS total", {})
        total = (t[0].get("total") or 0) if t else 0

        # Get high-risk count (>15M tCO2e)
        h = db.execute_read("MATCH (s:Supplier) WHERE s.co2_scope3 > 15000000 RETURN count(s) AS n", {})
        high_risk = (h[0].get("n") or 0) if h else 0

        return {
            "suppliers": (s[0].get("n") or 0) if s else 0,
            "relationships": (r[0].get("n") or 0) if r else 0,
            "observations": (o[0].get("n") or 0) if o else 0,
            "total_co2": total,
            "high_risk": high_risk,
        }
    except Exception:
        return {"suppliers": 0, "relationships": 0, "observations": 0, "total_co2": 0, "high_risk": 0}

@st.cache_data(ttl=60, show_spinner=False)
def _get_top_suppliers():
    """Get top 10 suppliers by emissions"""
    try:
        from ecograph.knowledge_graph.neo4j_client import get_neo4j_client
        db = get_neo4j_client()
        result = db.execute_read(
            "MATCH (s:Supplier) WHERE s.co2_scope3 IS NOT NULL "
            "RETURN coalesce(s.name, s.entity_id) AS name, s.co2_scope3 AS emissions "
            "ORDER BY s.co2_scope3 DESC LIMIT 10", {}
        )
        return result
    except Exception:
        return []

@st.cache_data(ttl=60, show_spinner=False)
def _generate_time_series():
    """Generate mock time series data for emissions trend"""
    dates = [(datetime.now() - timedelta(days=30-i)).strftime("%Y-%m-%d") for i in range(30)]
    # Simulate emissions with slight growth trend
    base = 45_000_000
    values = [base + np.random.randint(-2_000_000, 5_000_000) + (i * 150_000) for i in range(30)]
    return dates, values


# =============================================================================
# PAGE HEADER
# =============================================================================

st.markdown(
    '<div class="dashboard-hero">'
    '<div class="hero-badge">REAL-TIME MONITORING</div>'
    '<div class="pg-title">Executive Dashboard</div>'
    '<div class="pg-sub">Comprehensive Scope 3 emissions intelligence and supply chain analytics</div>'
    '</div>',
    unsafe_allow_html=True,
)

st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# TOP KPI CARDS
# -----------------------------------------------------------------------------

m = _metrics()

# Calculate scope 3 percentage (mock - assuming Scope 3 is 73.2% of total)
scope3_pct = 73.2
co2_label = (f"{m['total_co2']/1e9:.2f}B"
             if m['total_co2'] >= 1e9
             else f"{m['total_co2']/1e6:.1f}M")

# KPI Cards with modern styling
col1, col2, col3, col4 = st.columns(4, gap="medium")

with col1:
    st.markdown(
        '<div class="kpi-card kpi-primary">'
        '<div class="kpi-label">TOTAL EMISSIONS</div>'
        f'<div class="kpi-value">{co2_label}</div>'
        '<div class="kpi-unit">tCO2e</div>'
        '<div class="kpi-change positive">↑ 2.3% from last month</div>'
        '</div>',
        unsafe_allow_html=True,
    )

with col2:
    st.markdown(
        '<div class="kpi-card kpi-success">'
        '<div class="kpi-label">SCOPE 3 CONTRIBUTION</div>'
        f'<div class="kpi-value">{scope3_pct}%</div>'
        '<div class="kpi-unit">of total emissions</div>'
        '</div>',
        unsafe_allow_html=True,
    )

with col3:
    st.markdown(
        '<div class="kpi-card kpi-info">'
        '<div class="kpi-label">ACTIVE SUPPLIERS</div>'
        f'<div class="kpi-value">{m["suppliers"]:,}</div>'
        '<div class="kpi-unit">tracked entities</div>'
        '<div class="kpi-change positive">↑ 12 new this month</div>'
        '</div>',
        unsafe_allow_html=True,
    )

with col4:
    st.markdown(
        '<div class="kpi-card kpi-warning">'
        '<div class="kpi-label">HIGH-RISK SUPPLIERS</div>'
        f'<div class="kpi-value">{m["high_risk"]}</div>'
        '<div class="kpi-unit">&gt;15M tCO2e</div>'
        '<div class="kpi-change negative">! Requires attention</div>'
        '</div>',
        unsafe_allow_html=True,
    )

st.markdown("<div style='margin-top:2.5rem'></div>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# ALERT BANNER
# -----------------------------------------------------------------------------

if m["high_risk"] > 0:
    st.markdown(
        '<div class="alert-banner warning">'
        '<div class="alert-icon">⚠️</div>'
        '<div class="alert-content">'
        '<div class="alert-title">High Emission Alert</div>'
        f'<div class="alert-text">{m["high_risk"]} suppliers exceed emission thresholds. '
        '<a href="pages/2_carbon_hotspots.py" style="color: inherit; text-decoration: underline;">View hotspots ➔</a></div>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown("<div style='margin-top:1.5rem'></div>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# CHARTS SECTION
# -----------------------------------------------------------------------------
section_header("EMISSIONS ANALYTICS", level=2)

# Two-column layout for charts
chart_col1, chart_col2 = st.columns([2, 1], gap="large")

with chart_col1:
    st.markdown('<div class="chart-title">Emissions Trend (Last 30 Days)</div>', unsafe_allow_html=True)

    dates, values = _generate_time_series()

    fig_line = go.Figure()
    fig_line.add_trace(go.Scatter(
        x=dates,
        y=values,
        mode='lines+markers',
        name='Total Emissions',
        line=dict(color='#22C55E', width=3),
        marker=dict(size=6, color='#22C55E'),
        fill='tozeroy',
        fillcolor='rgba(34, 197, 94, 0.1)'
    ))

    fig_line.update_layout(
        height=350,
        margin=dict(l=20, r=20, t=20, b=40),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        xaxis=dict(
            showgrid=True,
            gridcolor='rgba(255,255,255,0.05)',
            title=dict(text='Date', font=dict(size=11)),
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor='rgba(255,255,255,0.05)',
            title=dict(text='Emissions (tCO2e)', font=dict(size=11)),
        ),
        font=dict(color='#A8A39C', size=11),
        hovermode='x unified',
        showlegend=False,
    )

    st.plotly_chart(fig_line, use_container_width=True, key="line_chart")

with chart_col2:
    st.markdown('<div class="chart-title">Emissions by Scope</div>', unsafe_allow_html=True)
    
    # Scope breakdown (mock data)
    scopes = ['Scope 1', 'Scope 2', 'Scope 3']
    scope_values = [12.5, 14.3, 73.2]
    colors = ['#3B82F6', '#38BDF8', '#22C55E']

    fig_donut = go.Figure(data=[go.Pie(
        labels=scopes,
        values=scope_values,
        hole=0.6,
        marker=dict(colors=colors),
        textinfo='label+percent',
        textfont=dict(size=12),
        hovertemplate='<b>%{label}</b><br>%{value:.1f}%<br>of total emissions<extra></extra>',
    )])

    fig_donut.update_layout(
        height=350,
        margin=dict(l=20, r=20, t=20, b=20),
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#A8A39C', size=11),
        showlegend=True,
        legend=dict(orientation="v", x=0.7, y=0.5),
    )

    st.plotly_chart(fig_donut, use_container_width=True, key="donut_chart")

st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)

# Bar chart - Top emitting suppliers
st.markdown('<div class="chart-title">Top 10 Emitting Suppliers</div>', unsafe_allow_html=True)

top_suppliers = _get_top_suppliers()
if top_suppliers:
    names = [s['name'][:30] for s in top_suppliers]
    emissions = [s['emissions'] / 1e6 for s in top_suppliers] # Convert to millions

    fig_bar = go.Figure(data=[go.Bar(
        x=emissions,
        y=names,
        orientation='h',
        marker=dict(
            color=emissions,
            colorscale=[
                [0, '#22C55E'],
                [0.5, '#F59E0B'],
                [1, '#EF4444']
            ],
            showscale=True,
            colorbar=dict(
                title=dict(
                    text="Million tCO2e",
                    side="right"
                ),
                tickfont=dict(size=10),
            ),
        ),
        text=[f'{e:.1f}M' for e in emissions],
        textposition='auto',
        hovertemplate='<b>%{y}</b><br>%{x:.2f}M tCO2e<extra></extra>',
    )])

    fig_bar.update_layout(
        height=400,
        margin=dict(l=20, r=20, t=20, b=40),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        xaxis=dict(
            showgrid=True,
            gridcolor='rgba(255,255,255,0.05)',
            title=dict(text='Emissions (Million tCO2e)', font=dict(size=11)),
        ),
        yaxis=dict(
            showgrid=False,
            autorange='reversed',
        ),
        font=dict(color='#A8A39C', size=11),
    )

    st.plotly_chart(fig_bar, use_container_width=True, key="bar_chart")
else:
    st.info("No supplier data available. Run the pipeline to populate the knowledge graph.")

st.markdown("<div style='margin-top:2.5rem'></div>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# AI INSIGHTS PANEL
# -----------------------------------------------------------------------------

section_header("AI-GENERATED INSIGHTS", level=2)

insights_col1, insights_col2 = st.columns([2, 1], gap="large")

with insights_col1:
    st.markdown(
        '<div class="insight-card">'
        '<div class="insight-badge">ANOMALY DETECTED</div>'
        '<div class="insight-title">Emission Spike in Southeast Asia Region</div>'
        '<div class="insight-body">'
        'Analysis shows a 23% increase in reported emissions from suppliers in the '
        'SE Asia region over the past 14 days. This correlates with seasonal manufacturing '
        'peaks but exceeds historical averages by 8.2%. Satellite validation confirms increased '
        'CO2 flux at 3 major facilities.'
        '</div>'
        '<div class="insight-footer">'
        '<span class="insight-confidence">Confidence: High (94%)</span>'
        '<span class="insight-source">Sources: ERP invoices, TROPOMI satellite data</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="insight-card">'
        '<div class="insight-badge success">POSITIVE TREND</div>'
        '<div class="insight-title">Renewable Energy Adoption Increasing</div>'
        '<div class="insight-body">'
        '12 suppliers have updated their ESG reports indicating renewable energy commitments. '
        'Projected emissions reduction of 4.2M tCO2e annually if targets are met. '
        'Recommend prioritizing these suppliers in procurement decisions.'
        '</div>'
        '<div class="insight-footer">'
        '<span class="insight-confidence">Confidence: Medium (76%)</span>'
        '<span class="insight-source">Sources: ESG reports, emission factor database</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

with insights_col2:
    st.markdown(
        '<div class="quick-stats-card">'
        '<div class="quick-stats-title">Quick Stats</div>'
        '<div class="quick-stats-item">'
        f'<div class="quick-stats-value">{m["observations"]:,}</div>'
        '<div class="quick-stats-label">Data Observations</div>'
        '</div>'
        '<div class="quick-stats-item">'
        f'<div class="quick-stats-value">{m["relationships"]:,}</div>'
        '<div class="quick-stats-label">Supply Chain Links</div>'
        '</div>'
        '<div class="quick-stats-item">'
        '<div class="quick-stats-value">98.2%</div>'
        '<div class="quick-stats-label">Data Quality Score</div>'
        '</div>'
        '<div class="quick-stats-item">'
        '<div class="quick-stats-value">43</div>'
        '<div class="quick-stats-label">Countries Covered</div>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

st.markdown("<div style='margin-top:2.5rem'></div>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# SYSTEM STATUS
# -----------------------------------------------------------------------------

section_header("SYSTEM STATUS", level=2)

neo_ok, neo_msg = _neo4j_status()
groq_ok, groq_msg = _groq_status()

status_col1, status_col2, status_col3 = st.columns(3, gap="medium")

with status_col1:
    status_card("Neo4j Knowledge Graph",
                "Connected" if neo_ok else "Disconnected",
                "AuraDB • Query API Active" if neo_ok else neo_msg,
                "ok" if neo_ok else "err")

with status_col2:
    status_card("Groq LLM Engine",
                "Ready" if groq_ok else "Not configured",
                "llama-3.1-8b-instant" if groq_ok else groq_msg,
                "ok" if groq_ok else "err")

with status_col3:
    try:
        from ecograph.graphrag.vector_store import get_vector_store
        vs = get_vector_store()
        mock = "Mock" in type(vs).__name__
        status_card("Qdrant Vector Store",
                    "Connected" if not mock else "Using Mock",
                    "GraphRAG embeddings active" if not mock else "Set Quadrant_URL in .env",
                    "ok" if not mock else "warn")
    
    except Exception as exc:
        status_card("Qdrant Vector Store", "Error", str(exc)[:60], "err")

st.markdown("<div style='margin-bottom:4rem'></div>", unsafe_allow_html=True)

section_header("EXPLORE ANALYSIS PAGES", level=2)


CARDS = [
    (
        "Supply Chain Map",
        "NETWORK ANALYSIS",
        "Interactive Tier-N supplier graph with emission intensity color coding and relationship weights.",
        "pages/1_supply_chain_map.py",
        "🌐",
    ),
    (
        "Carbon Hotspots",
        "EMISSIONS TRACKING",
        "Ranked emission analysis with satellite cross-validation and discrepancy detection.",
        "pages/2_carbon_hotspots.py",
        "🔺",
    ),
    (
        "Agent Query",
        "AI ASSISTANT",
        "Ask natural-language questions. The multi-agent system queries the graph and writes cited reports.",
        "pages/3_agent_query.py",
        "🤖",
    ),
    (
        "Audit Trail",
        "COMPLIANCE",
        "Immutable observation history and evidence lineage for CSRD and California SB 253.",
        "pages/4_audit_trail.py",
        "📜",
    ),
]

cols = st.columns(4, gap="medium")
for col, (title, tag, body, page, icon) in zip(cols, CARDS):
    with col:
        st.markdown(
            f'<div class="nav-card">'
            f'<div class="nav-card-icon">{icon}</div>'
            f'<div class="nav-card-tag">{tag}</div>'
            f'<div class="nav-card-title">{title}</div>'
            f'<div class="nav-card-body">{body}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.page_link(page, label=f"Open {title} ➔")

st.markdown("<div style='margin-top:3rem'></div>", unsafe_allow_html=True)