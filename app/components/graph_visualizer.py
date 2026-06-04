"""
app/components/graph_visualizer.py

PyVis-based supply chain network visualization for the Streamlit dashboard.

Renders an interactive HTML network graph embedded in the Streamlit page.
Node colour encodes emission intensity; edge width encodes transaction value.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def build_pyvis_graph(
    nodes: list[dict],
    edges: list[dict],
    height: str = "550px",
    bgcolor: str = "#0e1117",
    font_color: str = "#ffffff",
) -> Optional[str]:
    """
    Build a PyVis HTML network from node/edge dicts.

    Parameters
    ----------
    nodes : list[dict]
        Each dict: {id, label, co2_scope3 (float, optional), group (str, optional)}
    edges : list[dict]
        Each dict: {source, target, weight (float, optional), label (str, optional)}
    height :
        CSS height string for the network iframe.
    bgcolor :
        Background colour (hex).
    font_color :
        Node label colour.

    Returns
    -------
    str : HTML string ready for st.components.v1.html(), or None on failure.
    """
    try:
        from pyvis.network import Network  # type: ignore[import]
    except ImportError:
        logger.error("pyvis is not installed. Run: pip install pyvis")
        return None

    net = Network(
        height=height,
        width="100%",
        bgcolor=bgcolor,
        font_color=font_color,
        directed=True,
    )
    net.set_options("""
    {
      "physics": {
        "enabled": true,
        "stabilization": {"iterations": 150},
        "barnesHut": {"gravitationalConstant": -8000, "springLength": 120}
      },
      "interaction": {"hover": true, "tooltipDelay": 100}
    }
    """)

    # Colour scale: green (low) -> yellow -> red (high CO2)
    def _co2_colour(co2: Optional[float]) -> str:
        if co2 is None:
            return "#4a90d9"
        if co2 < 10_000:
            return "#2ecc71"
        if co2 < 100_000:
            return "#f39c12"
        return "#e74c3c"

    for node in nodes:
        nid   = str(node.get("id", node.get("entity_id", "")))
        label = str(node.get("label", node.get("name", nid)))[:30]
        co2   = node.get("co2_scope3")
        colour = _co2_colour(co2)
        title = f"{label}<br>CO2: {co2:,.0f} tCO2e" if co2 else label
        net.add_node(nid, label=label, color=colour, title=title, size=18)

    for edge in edges:
        src    = str(edge.get("source", edge.get("source_id", "")))
        tgt    = str(edge.get("target", edge.get("target_id", "")))
        weight = edge.get("weight", 1.0) or 1.0
        elabel = edge.get("label", edge.get("rel_type", ""))
        width  = max(1, min(8, float(weight) * 3))
        net.add_edge(src, tgt, title=elabel, width=width, arrows="to")

    try:
        with tempfile.NamedTemporaryFile(
            suffix=".html", delete=False, mode="w", encoding="utf-8"
        ) as fh:
            path = fh.name
        net.save_graph(path)
        html = Path(path).read_text(encoding="utf-8")
        Path(path).unlink(missing_ok=True)
        return html
    except Exception as exc:
        logger.error("Failed to render PyVis graph: %s", exc)
        return None


def render_graph_in_streamlit(
    nodes: list[dict],
    edges: list[dict],
    height: int = 560,
) -> None:
    """
    Convenience wrapper: build the graph and embed it in Streamlit.
    Shows an error message if pyvis is missing or graph is empty.
    """
    import streamlit as st
    import streamlit.components.v1 as components

    if not nodes:
        st.info("No graph data to display. Run the bootstrap pipeline first.")
        return

    html = build_pyvis_graph(nodes, edges)
    if html:
        components.html(html, height=height, scrolling=False)
    else:
        st.error(
            "PyVis is not installed or graph rendering failed. "
            "Install with: `pip install pyvis`"
        )