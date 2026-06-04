"""
app/pages/1_supply_chain_map.py
"""
from __future__ import annotations
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
import streamlit as st

st.set_page_config(page_title="Supply Chain Map - EcoGraph", page_icon="🗺️", layout="wide")
from app.theme import apply_theme, section_header, empty_state
apply_theme()

def theme_toggle():
    label = "Switch to Light Mode" if st.session_state.get("_dark") else "Switch to Dark Mode"
    if st.button(label, use_container_width=True, key="_theme_toggle_btn"):
        st.session_state["_dark"] = not st.session_state.get("_dark", False)
        st.rerun()

with st.sidebar:
    st.markdown(
        '<div class="sb-brand"><div class="sb-name">EcoGraph</div>'
        '<div class="sb-sub">Supply Chain Map</div></div>',
        unsafe_allow_html=True,
    )
    st.divider()
    st.markdown('<span class="sb-nav-lbl">Filters</span>', unsafe_allow_html=True)
    country_filter = st.text_input("Country code", value="", placeholder="e.g. CN, US, AU - blank for all")
    min_co2 = st.number_input("Min Scope 3 (tCO2e)", value=0, step=100_000, format="%d")
    max_nodes = st.slider("Max nodes", 10, 300, 50)
    st.divider()
    st.markdown('<span class="sb-nav-lbl">Legend</span>', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:0.82rem;line-height:2;">'
        '<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#2D9C5E;margin-right:8px;vertical-align:middle;"></span>Low &lt; 5M tCO2e<br>'
        '<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#C28010;margin-right:8px;vertical-align:middle;"></span>Mid &lt; 15M tCO2e<br>'
        '<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#C0392B;margin-right:8px;vertical-align:middle;"></span>High &gt;= 15M tCO2e'
        '</div>',
        unsafe_allow_html=True,
    )
    st.divider()
    theme_toggle()
    st.divider()
    st.caption("Refreshes every 2 min")

@st.cache_data(ttl=120, show_spinner="Loading supply chain graph...")
def load_graph(country, min_co2, limit):
    try:
        from ecograph.knowledge_graph.neo4j_client import get_neo4j_client
        db = get_neo4j_client()
        where = []
        if country:
            where.append(f"s.country_code = '{country.upper().strip()}'")
        if min_co2 > 0:
            where.append(f"coalesce(s.co2_scope3, 0) >= {int(min_co2)}")
        w = ("WHERE " + " AND ".join(where)) if where else ""
        nodes = db.execute_read(
            f"MATCH (s:Supplier) {w} RETURN s.entity_id AS id, coalesce(s.name, s.entity_id) AS label, s.country_code AS country, s.co2_scope3 AS co2 ORDER BY coalesce(s.co2_scope3, 0) DESC LIMIT $lim",
            {"lim": limit},
        )
        ids = [r["id"] for r in nodes if r.get("id")]
        edges = db.execute_read(
            "MATCH (a:Supplier)-[r]->(b:Supplier) WHERE a.entity_id IN $ids AND b.entity_id IN $ids RETURN a.entity_id AS source, b.entity_id AS target, type(r) AS rel_type, coalesce(r.weight, 1.0) AS weight LIMIT 2000",
            {"ids": ids},
        ) if ids else []
        return nodes, edges
    except Exception as exc:
        st.error(f"Neo4j error: {exc}")
        return [], []

def _co2_color(val):
    if not val: return "#A9A9A9"
    if val < 5_000_000: return "#2D9C5E"
    if val < 15_000_000: return "#C28010"
    return "#C0392B"

st.markdown('<div class="pg-title">Supply Chain Map</div><div class="pg-sub">Tier-N supplier network - emission intensity colour coding</div>', unsafe_allow_html=True)

nodes, edges = load_graph(country_filter, min_co2, max_nodes)
if not nodes:
    empty_state("🔍", "No suppliers found", "Adjust filters or run the pipeline first.")
    st.stop()

total_co2 = sum((n.get("co2") or 0) for n in nodes)
k1, k2, k3 = st.columns(3, gap="medium")
with k1: st.metric("Suppliers shown", f"{len(nodes):,}")
with k2: st.metric("Relationships", f"{len(edges):,}")
with k3: st.metric("Combined Scope 3", f"{total_co2/1e9:.2f}B tCO2e" if total_co2 >= 1e9 else f"{total_co2/1e6:.1f}M tCO2e")
st.markdown("<br>", unsafe_allow_html=True)

section_header("Network Graph", level=3)

# View toggle
view_mode = st.radio(
    "Show",
    ["Connected suppliers only", "All suppliers"],
    horizontal=True,
    help="'Connected' hides isolated nodes with no supply relationships - much easier to read.",
)

try:
    from pyvis.network import Network
    import streamlit.components.v1 as components

    # Determine which node IDs are connected
    connected_ids = set()
    for e in edges:
        connected_ids.add(e["source"])
        connected_ids.add(e["target"])

    # Filter nodes based on view mode
    display_nodes = nodes if view_mode == "All suppliers" else [
        n for n in nodes if n["id"] in connected_ids
    ]

    if not display_nodes:
        st.info("No connected suppliers found. Switch to 'All suppliers' to see isolated nodes.")
    else:
        net = Network(
            height="620px",
            width="100%",
            bgcolor="#FFFFFF",
            font_color="#1A1A1A",
            directed=True,
            notebook=False,
        )

        # Physics: tight clustering, short spring length so labels don't overlap ---
        net.set_options("""{
          "nodes": {
            "shape": "dot",
            "borderWidth": 2,
            "borderWidthSelected": 4,
            "font": {
              "size": 14,
              "face": "Inter, Arial, sans-serif",
              "strokeWidth": 3,
              "strokeColor": "#FFFFFF"
            },
            "shadow": {"enabled": true, "size": 6, "x": 2, "y": 2, "color": "rgba(0,0,0,0.12)"}
          },
          "edges": {
            "arrows": {"to": {"enabled": true, "scaleFactor": 0.7, "type": "arrow"}},
            "color": {"color": "#CCCCCC", "highlight": "#16A34A", "hover": "#16A34A"},
            "smooth": {"enabled": true, "type": "curvedCW", "roundness": 0.2},
            "width": 2,
            "selectionWidth": 3,
            "shadow": {"enabled": false}
          },
          "physics": {
            "enabled": true,
            "solver": "forceAtlas2Based",
            "forceAtlas2Based": {
              "gravitationalConstant": -60,
              "centralGravity": 0.01,
              "springLength": 180,
              "springConstant": 0.08,
              "damping": 0.4,
              "avoidOverlap": 1
            },
            "stabilization": {"iterations": 200, "updateInterval": 25}
          },
          "interaction": {
            "hover": true,
            "tooltipDelay": 100,
            "navigationButtons": true,
            "keyboard": true,
            "zoomView": true,
            "dragNodes": true
          },
          "layout": {"improvedLayout": true}
        }""")

        for n in display_nodes:
            co2 = n.get("co2") or 0
            color = _co2_color(co2)
            size = max(18, min(55, co2 / 400_000)) if co2 else 14

            # Only show label for connected nodes or top emitters
            show_label = (n["id"] in connected_ids) or (co2 >= 5_000_000)
            label = n["label"] if show_label else ""

            co2_fmt = f"{co2/1e6:.1f}M" if co2 >= 1_000_000 else (f"{co2:,}" if co2 else "N/A")
            tooltip = (
                f"<b>{n['label']}</b><br>"
                f"Country: {n.get('country') or '-'}<br>"
                f"Scope 3: {co2_fmt} tCO2e"
            )

            net.add_node(
                n["id"],
                label=label,
                title=tooltip,
                color={
                    "background": color,
                    "border": color,
                    "highlight": {"background": color, "border": "#000000"},
                    "hover": {"background": color, "border": "#333333"},
                },
                size=size,
                font={"color": "#1A1A1A", "size": 13 if show_label else 0},
            )

        for e in edges:
            rel = (e.get("rel_type") or "SUPPLIES").replace("_", " ").title()
            net.add_edge(
                e["source"],
                e["target"],
                title=rel,
                width=max(1.5, min(5, (e.get("weight") or 1) * 1.5)),
                color={"color": "#BBBBBB", "highlight": "#16A34A"},
            )

        # Wrap in a styled container
        st.markdown(
            f'<div style="border: 1px solid #E4E4E7; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.07);">',
            unsafe_allow_html=True,
        )
        components.html(net.generate_html(), height=640, scrolling=False)
        st.markdown("</div>", unsafe_allow_html=True)

        st.caption(
            "👉 Drag nodes • scroll to zoom • click a node to highlight its connections"
        )

except ImportError:
    st.info("Install pyvis for the interactive graph: `pip install pyvis`")
    import pandas as pd
    st.dataframe(
        pd.DataFrame(nodes)[["label", "country", "co2"]].rename(
            columns={"label": "Supplier", "country": "Country", "co2": "Scope 3 (tCO2e)"}
        ),
        use_container_width=True, hide_index=True,
    )

st.markdown("<br>", unsafe_allow_html=True)
section_header("Supplier Table", level=3)
import pandas as pd
df = pd.DataFrame(nodes)
if not df.empty:
    df = df.rename(columns={"label": "Supplier", "country": "Country", "id": "Entity ID", "co2": "Scope 3 (tCO2e)"})
    df["Scope 3 (tCO2e)"] = df["Scope 3 (tCO2e)"].apply(lambda x: f"{x:,.0f}" if x else "-")
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.download_button("Download CSV", pd.DataFrame(nodes).to_csv(index=False).encode(), "supply_chain.csv", "text/csv")