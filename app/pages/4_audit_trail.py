"""app/pages/4_audit_trail.py"""
from __future__ import annotations
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT))
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Audit Trail • EcoGraph", page_icon="📄", layout="wide")
from app.theme import apply_theme, section_header, empty_state

apply_theme()


def theme_toggle():
    label = (
        "Switch to Light Mode"
        if st.session_state.get("_dark")
        else "Switch to Dark Mode"
    )
    if st.button(label, use_container_width=True, key="_theme_toggle_btn"):
        st.session_state["_dark"] = not st.session_state.get("_dark", False)
        st.rerun()


with st.sidebar:
    st.markdown(
        '<div class="sb-brand"><div class="sb-name">EcoGraph</div>'
        '<div class="sb-sub">Audit Trail</div></div>',
        unsafe_allow_html=True,
    )
    st.divider()
    st.markdown('<span class="sb-nav-lbl">Filters</span>', unsafe_allow_html=True)
    entity_search = st.text_input(
        "Search supplier name or ID", value="", placeholder="e.g. Microsoft, Apple"
    )
    metric_filter = st.selectbox(
        "Metric",
        [
            "All",
            "co2_scope1",
            "co2_scope2",
            "co2_scope3",
            "co2_flux_tonnes_per_year",
        ],
    )
    method_filter = st.selectbox(
        "Method", ["All", "self_reported", "satellite", "spend_based", "tropomi_ch4"]
    )
    st.divider()
    st.markdown(
        '<span class="sb-nav-lbl">Compliance</span>'
        '<div style="font-size:0.8rem;line-height:1.7;margin-top:4px;">'
        "All observations are append-only.<br>"
        "Evidence lineage is traceable to source documents."
        "</div>",
        unsafe_allow_html=True,
    )
    st.divider()
    theme_toggle()
    st.divider()
    st.caption("Refreshes every 60 s")


@st.cache_data(ttl=60, show_spinner=False)
def _load_observations(entity, metric, method):
    try:
        from ecograph.knowledge_graph.neo4j_client import get_neo4j_client

        db = get_neo4j_client()
        wheres = []
        if entity:
            safe = entity.replace("'", "''")
            wheres.append(
                f"(s.entity_id CONTAINS '{safe}' OR toLower(s.name) CONTAINS toLower('{safe}'))"
            )
        if metric != "All":
            wheres.append(f"obs.metric = '{metric}'")
        if method != "All":
            wheres.append(f"obs.method = '{method}'")
        w = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        rows = db.execute_read(
            f"MATCH (s)-[:HAS_OBSERVATION]->(obs:Observation) {w} OPTIONAL MATCH (obs)-[:SUPPORTED_BY]->(ev:Evidence) RETURN s.entity_id AS entity_id, coalesce(s.name,s.entity_id) AS supplier_name, obs.observation_id AS observation_id, obs.metric AS metric, obs.value AS value, obs.unit AS unit, obs.method AS method, obs.confidence AS confidence, toString(obs.timestamp) AS timestamp, obs.source AS source, ev.source AS evidence_source ORDER BY obs.timestamp DESC LIMIT 500",
              {},  
        )
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    except Exception as exc:
        st.error(f"Neo4j error: {exc}")
        return pd.DataFrame()


@st.cache_data(ttl=60, show_spinner=False)
def _load_evidence():
    try:
        from ecograph.knowledge_graph.neo4j_client import get_neo4j_client

        db = get_neo4j_client()
        rows = db.execute_read(
            "MATCH (ev:Evidence) OPTIONAL MATCH (obs:Observation)-[:SUPPORTED_BY]->(ev) WITH ev, count(obs) AS obs_count RETURN ev.evidence_id AS evidence_id, ev.source AS source, ev.file AS file, toString(ev.ingested_at) AS ingested_at, obs_count ORDER BY ev.ingested_at DESC LIMIT 200" , {}
        )
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60, show_spinner=False)
def _load_entity_resolution():
    try:
        from ecograph.knowledge_graph.neo4j_client import get_neo4j_client

        db = get_neo4j_client()
        rows = db.execute_read(
            "MATCH (s:Supplier) WHERE s.canonical_id IS NOT NULL RETURN s.canonical_id AS canonical_id, s.entity_id AS entity_id, coalesce(s.name,s.entity_id) AS name, s.resolution_confidence AS confidence ORDER BY s.canonical_id LIMIT 500" , {}
        )
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60, show_spinner=False)
def _load_discrepancies():
    try:
        from ecograph.knowledge_graph.neo4j_client import get_neo4j_client

        db = get_neo4j_client()
        rows = db.execute_read(
            "MATCH (s:Supplier) WHERE s.discrepancy_flag = true RETURN s.entity_id AS entity_id, coalesce(s.name,s.entity_id) AS name, s.co2_scope3 AS reported_co2, s.satellite_co2 AS satellite_co2 ORDER BY s.entity_id LIMIT 500" , {}
        )
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


st.markdown(
    '<div class="pg-title">Audit Trail</div><div class="pg-sub">Immutable observation history, evidence lineage, CSRD / California SB 253 audit readiness</div>',
    unsafe_allow_html=True
)

obs_df = _load_observations(entity_search, metric_filter, method_filter)
ev_df = _load_evidence()
er_df = _load_entity_resolution()
disc_df = _load_discrepancies()

k1, k2, k3, k4 = st.columns(4, gap="medium")
with k1:
    st.metric("Observations", len(obs_df))
with k2:
    st.metric("Evidence Sources", len(ev_df))
with k3:
    st.metric("Resolved Entities", len(er_df))
with k4:
    st.metric("Discrepancy Flags", len(disc_df))
st.markdown("<br>", unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(
    [
        "Observation Timeline",
        "Evidence Sources",
        "Entity Resolution",
        "Discrepancy Log",
    ]
)

with tab1:
    section_header("Observation Timeline", level=3)
    if obs_df.empty:
        empty_state(
            "🔍", "No observations found", "Adjust filters or run the pipeline."
        )
    else:
        st.caption(f"{len(obs_df)} records (capped at 500)")
        display_cols = [
            "timestamp",
            "supplier_name",
            "metric",
            "value",
            "unit",
            "method",
            "confidence",
            "source",
        ]
        disp_obs_df = obs_df[
            [c for c in display_cols if c in obs_df.columns]
        ].copy()
        disp_obs_df.columns = [
            c.replace("_", " ").title() for c in disp_obs_df.columns
        ]
        st.dataframe(disp_obs_df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download CSV",
            obs_df.to_csv(index=False).encode(),
            "observations.csv",
            "text/csv",
        )

with tab2:
    section_header("Evidence Sources", level=3)
    if ev_df.empty:
        empty_state(
            "🔍",
            "No evidence nodes found",
            "Evidence nodes are created during pipeline ingestion.",
        )
    else:
        st.caption(f"{len(ev_df)} evidence sources indexed")
        ev_df.columns = [c.replace("_", " ").title() for c in ev_df.columns]
        st.dataframe(ev_df, use_container_width=True, hide_index=True)

with tab3:
    section_header("Entity Resolution Lineage", level=3)
    st.markdown(
        "Shows raw entity IDs merged into a canonical entity by the Splink probabilistic model."
    )
    if er_df.empty:
        empty_state(
            "🧬",
            "No canonical IDs found",
            "Run entity resolution: 'python scripts/bootstrap_graph.py'",
        )
    else:
        for cid, group in list(er_df.groupby("canonical_id"))[:50]:
            members = group[["entity_id", "name", "confidence"]].copy()
            avg_conf = group["confidence"].dropna().mean()
            hdr = f"Canonical: '{cid[:16]}...' ({len(members)} members)" + (
                f" - Conf: {avg_conf:.2f}" if not pd.isna(avg_conf) else ""
            )
            with st.expander(hdr):
                st.dataframe(members, use_container_width=True, hide_index=True)

with tab4:
    section_header("Discrepancy Log", level=3)
    st.markdown("Suppliers where |self-reported - satellite| / max > 20%.")
    if disc_df.empty:
        st.success("No discrepancy flags in the current graph.")
    else:
        disc_df["discrepancy_pct"] = disc_df.apply(
            lambda r: abs(r["reported_co2"] - r["satellite_co2"])
            / max(r["reported_co2"], r["satellite_co2"])
            * 100
            if pd.notna(r.get("reported_co2"))
            and pd.notna(r.get("satellite_co2"))
            and max(r.get("reported_co2", 0), r.get("satellite_co2", 0)) > 0
            else None,
            axis=1,
        )
        disc_df.columns = [
            "Entity ID",
            "Supplier",
            "Reported CO2 (tCO2e)",
            "Satellite CO2 (tCO2e)",
            "Discrepancy (%)",
        ]
        disc_df["Discrepancy (%)"] = disc_df["Discrepancy (%)"].map(
            lambda x: f"{x:.1f}%" if pd.notna(x) else "N/A"
        )
        st.dataframe(disc_df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download CSV",
            disc_df.to_csv(index=False).encode(),
            "discrepancy_log.csv",
            "text/csv",
        )