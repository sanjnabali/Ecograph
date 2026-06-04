"""app/pages/5_reports.py - Generate and download audit reports"""
from __future__ import annotations
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st
from datetime import datetime
import json

st.set_page_config(
    page_title="Reports • EcoGraph",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
from app.theme import apply_theme, section_header, badge

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


# Sidebar
with st.sidebar:
    st.markdown(
        '<div class="sb-brand">'
        '<div class="sb-icon">📊</div>'
        '<div class="sb-name">Reports</div>'
        '<div class="sb-sub">Generate audit-ready reports</div>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.divider()
    st.markdown(
        '<span class="sb-nav-lbl">NAVIGATION</span>', unsafe_allow_html=True
    )
    st.page_link("main.py", label="🏠 Overview")
    st.page_link("pages/1_supply_chain_map.py", label="🗺️ Supply Chain Map")
    st.page_link("pages/2_carbon_hotspots.py", label="🔥 Carbon Hotspots")
    st.page_link("pages/3_agent_query.py", label="🤖 Agent Query")
    st.page_link("pages/4_audit_trail.py", label="📄 Audit Trail")
    st.page_link("pages/5_reports.py", label="📊 Reports")
    st.divider()

    st.markdown(
        '<span class="sb-nav-lbl">REPORT OPTIONS</span>', unsafe_allow_html=True
    )
    report_type = st.selectbox(
        "Report Type",
        [
            "Comprehensive Audit",
            "Executive Summary",
            "Emissions Analysis",
            "Supplier Risk Assessment",
        ],
    )
    include_charts = st.checkbox("Include Charts & Visualizations", value=True)
    include_raw_data = st.checkbox("Include Raw Data Tables", value=False)

    st.divider()
    theme_toggle()
    st.divider()
    st.caption("CSRD & SB 253 Compliant")


# PAGE HEADER
st.markdown(
    '<div class="dashboard-hero">'
    '<div class="hero-badge">COMPLIANCE</div>'
    '<div class="pg-title">Audit Reports</div>'
    '<div class="pg-sub">Generate CSRD and California SB 253 compliant audit documentation</div>'
    "</div>",
    unsafe_allow_html=True,
)

st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)


# REPORT GENERATION
col1, col2 = st.columns([2, 1], gap="large")

with col1:
    section_header("GENERATE NEW REPORT", level=2)

    st.markdown(
        '<div class="insight-card">'
        '<div class="insight-title">Report Configuration</div>'
        '<div class="insight-body">'
        f"Selected report type: <strong>{report_type}</strong><br>"
        f"Charts included: <strong>{'Yes' if include_charts else 'No'}</strong><br>"
        f"Raw data tables: <strong>{'Yes' if include_raw_data else 'No'}</strong><br>"
        f"Generated: <strong>{datetime.now().strftime('%Y-%m-%d %H:%M')}</strong>"
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    if st.button(
        "📝 Generate Report", use_container_width=True, type="primary"
    ):
        with st.spinner("Generating comprehensive audit report..."):
            # Mock report generation
            import time

            progress_bar = st.progress(0)
            status_text = st.empty()

            steps = [
                (10, "Querying knowledge graph..."),
                (25, "Analyzing emissions data..."),
                (40, "Cross-validating with satellite data..."),
                (60, "Generating compliance sections..."),
                (75, "Creating visualizations..."),
                (90, "Compiling final document..."),
                (100, "Report ready!"),
            ]

            for progress, message in steps:
                status_text.text(message)
                progress_bar.progress(progress)
                time.sleep(0.3)

            st.success("🎉 Report generated successfully!")

            # Mock report content
            report_content = f"""# EcoGraph Audit Report
## {report_type}
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

### Executive Summary
This comprehensive audit report provides detailed analysis of Scope 3 supply chain emissions
across your entire supplier network. The analysis covers {{50}} suppliers and {{120}} facilities
across {{43}} countries.

### Key Findings
- Total Scope 3 Emissions: 47.3M tCO2e
- High-risk Suppliers Identified: 8
- Average data quality score: 98.2%
- Satellite validation coverage: 87%

### Methodology
Data sources include ERP invoice systems, supplier ESG reports, EPA emission factors,
global facility registries, and Sentinel-5P TROPOMI satellite observations.

### Compliance Status
- [x] CSRD Compliant
- [x] California SB 253 Compliant
- [x] GHG Protocol Standards Met

### Recommendations
1. Engage with 8 high-risk suppliers for emission reduction plans
2. Expand renewable energy requirements in supplier contracts
3. Implement quarterly satellite validation checks
4. Enhance data collection for Tier 2+ suppliers
"""

            st.download_button(
                label="📥 Download Report (Markdown)",
                data=report_content,
                file_name=f"ecograph_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
                mime="text/markdown",
                use_container_width=True,
            )

with col2:
    section_header("REPORT STATISTICS", level=2)

    st.markdown(
        '<div class="quick-stats-card">'
        '<div class="quick-stats-title">Generation Stats</div>'
        '<div class="quick-stats-item">'
        '<div class="quick-stats-value">50</div>'
        '<div class="quick-stats-label">Suppliers Analyzed</div>'
        "</div>"
        '<div class="quick-stats-item">'
        '<div class="quick-stats-value">120</div>'
        '<div class="quick-stats-label">Facilities Covered</div>'
        "</div>"
        '<div class="quick-stats-item">'
        '<div class="quick-stats-value">43</div>'
        '<div class="quick-stats-label">Countries</div>'
        "</div>"
        '<div class="quick-stats-item">'
        '<div class="quick-stats-value">98.2%</div>'
        '<div class="quick-stats-label">Data Quality</div>'
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )

st.markdown(
    "<div style='margin-top:2.5rem'></div>", unsafe_allow_html=True
)

# =============================================================================
# RECENT REPORTS
# =============================================================================

section_header("RECENT REPORTS", level=2)

# Check for existing reports in docs folder
docs_path = _PROJECT_ROOT / "docs"
recent_reports = []

if docs_path.exists():
    md_files = sorted(
        docs_path.glob("ecograph_report_*.md"), reverse=True
    )[:5]
    pdf_files = sorted(
        docs_path.glob("ecograph_report_*.pdf"), reverse=True
    )[:5]

    for md_file in md_files:
        recent_reports.append(
            {
                "name": md_file.stem,
                "type": "Markdown",
                "size": f"{md_file.stat().st_size / 1024:.1f} KB",
                "date": datetime.fromtimestamp(
                    md_file.stat().st_mtime
                ).strftime("%Y-%m-%d %H:%M"),
                "path": md_file,
            }
        )

    for pdf_file in pdf_files:
        recent_reports.append(
            {
                "name": pdf_file.stem,
                "type": "PDF",
                "size": f"{pdf_file.stat().st_size / 1024:.1f} KB",
                "date": datetime.fromtimestamp(
                    pdf_file.stat().st_mtime
                ).strftime("%Y-%m-%d %H:%M"),
                "path": pdf_file,
            }
        )

if recent_reports:
    # Create a nice table layout
    for report in recent_reports[:10]:
        col_a, col_b, col_c, col_d, col_e = st.columns([3, 1, 1, 2, 1])

        with col_a:
            st.markdown(f"**{report['name']}**")
        with col_b:
            st.markdown(
                badge(report["type"], "grey"), unsafe_allow_html=True
            )
        with col_c:
            st.text(report["size"])
        with col_d:
            st.text(report["date"])
        with col_e:
            try:
                with open(report["path"], "rb") as f:
                    st.download_button(
                        label="📥",
                        data=f.read(),
                        file_name=report["path"].name,
                        mime=(
                            "application/pdf"
                            if report["type"] == "PDF"
                            else "text/markdown"
                        ),
                        key=f"download_{report['name']}",
                    )
            except Exception:
                pass

    st.markdown(
        "<div style='margin-bottom:8px;'></div>", unsafe_allow_html=True
    )
else:
    st.info("No recent reports found. Generate your first report above.")

st.markdown(
    "<div style='margin-top:2.5rem'></div>", unsafe_allow_html=True
)

# =============================================================================
# COMPLIANCE INFO
# =============================================================================

section_header("COMPLIANCE STANDARDS", level=2)

comp_col1, comp_col2, comp_col3 = st.columns(3, gap="medium")

with comp_col1:
    st.markdown(
        '<div class="insight-card">'
        '<div class="insight-badge success">COMPLIANT</div>'
        '<div class="insight-title">CSRD (EU)</div>'
        '<div class="insight-body">'
        "Corporate Sustainability Reporting Directive compliance includes:<br><br>"
        "• Double materiality assessment<br>"
        "• Value chain mapping<br>"
        "• Scope 3 emission tracking<br>"
        "• Audit trail documentation"
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )

with comp_col2:
    st.markdown(
        '<div class="insight-card">'
        '<div class="insight-badge success">COMPLIANT</div>'
        '<div class="insight-title">California SB 253</div>'
        '<div class="insight-body">'
        "Climate Corporate Data Accountability Act requirements:<br><br>"
        "• Scope 1, 2, 3 emissions disclosure<br>"
        "• Third-party verification ready<br>"
        "• Annual reporting support<br>"
        "• GHG Protocol alignment"
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )

with comp_col3:
    st.markdown(
        '<div class="insight-card">'
        '<div class="insight-badge success">ALIGNED</div>'
        '<div class="insight-title">GHG Protocol</div>'
        '<div class="insight-body">'
        "Greenhouse Gas Protocol standards adherence:<br><br>"
        "• Category-based scope 3 calculations<br>"
        "• Supplier-specific data priority<br>"
        "• Emission factor transparency<br>"
        "• Uncertainty quantification"
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )