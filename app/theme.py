"""
app/theme.py - Ecograph design system.
Call apply_theme() immediately after st.set_page_config().
Theme toggle lives in the sidebar via st.session_state["_dark"].
"""

from __future__ import annotations
import streamlit as st

# --- Palette
_LIGHT = dict(
    bg         = "#F9F8F6",
    bg2        = "#F1F0EE",
    bg3        = "#E8E6E3",
    card       = "#FFFFFF",
    border     = "#DDD9D4",
    border2    = "#C8C3BC",
    txt        = "#1A1917",
    txt2       = "#4A4540",
    txt3       = "#847E78",
    accent     = "#22C55E",
    acc_h      = "#16A34A",
    acc_bg     = "#EEF7F2",
    acc_bdr    = "#B7DEC9",
    danger     = "#EF4444",
    dan_bg     = "#FEF2F2",
    warn       = "#F59E0B",
    warn_bg    = "#FEF3C7",
    ok_dot     = "#22C55E",
    err_dot    = "#EF4444",
    warn_dot   = "#F59E0B",
    info       = "#3B82F6",
    info_bg    = "#E0F2FE",
)

_DARK = dict(
    bg         = "#0F172A",
    bg2        = "#1E293B",
    bg3        = "#334155",
    card       = "#1E293B",
    border     = "#334155",
    border2    = "#475569",
    txt        = "#F1F5F9",
    txt2       = "#CBD5E1",
    txt3       = "#94A3B8",
    accent     = "#22C55E",
    acc_h      = "#16A34A",
    acc_bg     = "#0A2E1A",
    acc_bdr    = "#16A34A",
    danger     = "#EF4444",
    dan_bg     = "#1C0A0A",
    warn       = "#F59E0B",
    warn_bg    = "#1C1200",
    ok_dot     = "#22C55E",
    err_dot    = "#EF4444",
    warn_dot   = "#F59E0B",
    info       = "#3B82F6",
    info_bg    = "#0A1929",
)

def _css(p: dict) -> str:
    return f"""
    <style>
    /*
    ECOGRAPH PROFESSIONAL DASHBOARD THEME
    */

    /* --- Reset & App Shell --- */
    .stApp, .stApp > div {{
        background: {p["bg"]} !important;
        color: {p["txt"]} !important;
    }}

    /* --- Remove Streamlit chrome noise --- */
    #MainMenu, footer {{ visibility: hidden; }}
    [data-testid="stHeader"] {{
        background: {p["bg"]} !important;
        border-bottom: 1px solid {p["border"]} !important;
        visibility: visible !important;
        display: block !important;
    }}
    [data-testid="stToolbar"] {{ display: none !important; }}
    /* Keep sidebar expand/collapse button ALWAYS visible */
    [data-testid="collapsedControl"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="stSidebarCollapseButton"],
    button[kind="header"],
    [data-testid="stHeader"] button {{
        display: flex !important;
        visibility: visible !important;
        opacity: 1 !important;
        color: {p["txt"]} !important;
        z-index: 99999 !important;
        position: relative !important;
    }}
    [data-testid="collapsedControl"] svg,
    [data-testid="stSidebarCollapsedControl"] svg,
    [data-testid="stHeader"] button svg {{
        fill: {p["txt"]} !important;
        stroke: {p["txt"]} !important;
        width: 24px !important;
        height: 24px !important;
    }}

    /* --- Sidebar --- */
    [data-testid="stSidebar"],
    section[data-testid="stSidebar"],
    .css-1d391kg {{
        background: {p["bg2"]} !important;
        border-right: 1px solid {p["border"]} !important;
        min-width: 300px !important;
        width: 300px !important;
        max-width: 300px !important;
        display: block !important;
        visibility: visible !important;
        opacity: 1 !important;
        transform: translateX(0) !important;
        transition: none !important;
        position: relative !important;
        left: 0 !important;
    }}
    [data-testid="stSidebar"] > div,
    [data-testid="stSidebar"] > div:first-child {{
        width: 300px !important;
        min-width: 300px !important;
        display: block !important;
        visibility: visible !important;
    }}
    /* Prevent sidebar collapse */
    [data-testid="stSidebar"][aria-expanded="false"],
    section[data-testid="stSidebar"][aria-expanded="false"] {{
        display: block !important;
        width: 300px !important;
        transform: translateX(0) !important;
    }}
    [data-testid="stSidebar"] * {{ color: {p["txt"]} !important; }}
    [data-testid="stSidebarNav"] a:hover {{
        background: {p["bg3"]} !important;
        border-radius: 6px !important;
    }}

    /* --- Main content --- */
    .main .block-container {{
        padding-top: 2.25rem !important;
        padding-bottom: 3rem !important;
        max-width: 1380px !important;
    }}

    /* --- Typography --- */
    h1, h2, h3, h4, h5, h6 {{
        color: {p["txt"]} !important;
        font-weight: 600 !important;
        letter-spacing: -0.2px;
    }}
    p, li, span, label, div {{ color: {p["txt2"]} !important; }}
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {{ color: {p["txt"]} !important; }}
    [data-testid="stCaptionContainer"] {{ color: {p["txt3"]} !important; font-size: 0.8rem !important; }}

    /* --- Page header --- */
    .pg-title {{
        font-size: 1.75rem;
        font-weight: 700;
        color: {p["txt"]} !important;
        letter-spacing: -0.4px;
        line-height: 1.2;
        margin: 0 0 4px 0;
    }}
    .pg-sub {{
        font-size: 0.9rem;
        color: {p["txt3"]} !important;
        font-weight: 400;
        margin: 0 0 1.75rem 0;
    }}

    /* --- Section label --- */
    .sec-label {{
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.1rem;
        text-transform: uppercase;
        color: {p["txt3"]} !important;
        margin: 1.75rem 0 0.75rem 0;
    }}

    /* --- Metric cards --- */
    [data-testid="metric-container"] {{
        background: {p["card"]} !important;
        border: 1px solid {p["border"]} !important;
        border-radius: 8px !important;
        padding: 18px 22px !important;
        box-shadow: none !important;
    }}
    [data-testid="metric-container"] [data-testid="stMetricLabel"] {{
        font-size: 0.75rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.05rem !important;
        text-transform: uppercase;
        color: {p["txt3"]} !important;
    }}
    [data-testid="metric-container"] [data-testid="stMetricValue"] {{
        font-size: 1.9rem !important;
        font-weight: 700 !important;
        color: {p["txt"]} !important;
        line-height: 1.15;
    }}

    /* --- Status strip cards --- */
    .stat-strip {{
        background: {p["card"]};
        border: 1px solid {p["border"]};
        border-radius: 8px;
        padding: 16px 20px;
        display: flex;
        align-items: flex-start;
        gap: 12px;
    }}
    .stat-dot {{
        width: 8px; height: 8px;
        border-radius: 50%;
        margin-top: 6px;
        flex-shrink: 0;
    }}
    .stat-dot.ok {{ background: {p["ok_dot"]}; }}
    .stat-dot.err {{ background: {p["err_dot"]}; }}
    .stat-dot.warn {{ background: {p["warn_dot"]}; }}
    .stat-lbl {{ font-size: 0.7rem; font-weight: 700; letter-spacing: 0.05rem; text-transform: uppercase; color: {p["txt3"]} !important; }}
    .stat-val {{ font-size: 0.95rem; font-weight: 600; color: {p["txt"]} !important; margin-top: 2px; }}
    .stat-desc {{ font-size: 0.78rem; color: {p["txt2"]} !important; margin-top: 1px; }}

    /* --- Nav cards --- */
    .nav-card {{
        background: {p["card"]};
        border: 1px solid {p["border"]};
        border-radius: 8px;
        padding: 22px 22px 16px 22px;
        height: 100%;
        transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }}
    .nav-card:hover {{
        border-color: {p["accent"]};
        box-shadow: 0 0 3px {p["acc_bg"]};
    }}
    .nav-card-tag {{
        font-size: 0.65rem;
        font-weight: 700;
        letter-spacing: 0.1rem;
        text-transform: uppercase;
        color: {p["accent"]} !important;
        margin-bottom: 8px;
    }}
    .nav-card-title {{
        font-size: 1rem;
        font-weight: 700;
        color: {p["txt"]} !important;
        margin-bottom: 8px;
        line-height: 1.3;
    }}
    .nav-card-body {{
        font-size: 0.83rem;
        color: {p["txt3"]} !important;
        line-height: 1.6;
    }}

    /* --- Buttons --- */
    section[data-testid="stMain"] .stButton > button {{
        background: {p["txt"]} !important;
        color: {p["bg"]} !important;
        border: none !important;
        border-radius: 6px !important;
        padding: 9px 18px !important;
        font-weight: 600 !important;
        font-size: 0.85rem !important;
        letter-spacing: 0.01rem !important;
        transition: opacity 0.15s ease !important;
        box-shadow: none !important;
    }}
    section[data-testid="stMain"] .stButton > button:hover {{ opacity: 0.78 !important; }}
    /* Sidebar buttons - secondary/outlined style */
    section[data-testid="stSidebar"] .stButton > button,
    [data-testid="stSidebar"] .stButton > button {{
        background: {p["bg2"]} !important;
        color: {p["txt"]} !important;
        border: 1px solid {p["border"]} !important;
        font-size: 0.8rem !important;
        font-weight: 500 !important;
        text-align: left !important;
        white-space: normal !important;
        line-height: 1.4 !important;
        padding: 10px 14px !important;
        border-radius: 6px !important;
        box-shadow: none !important;
    }}
    section[data-testid="stSidebar"] .stButton > button:hover,
    [data-testid="stSidebar"] .stButton > button:hover,
    .stSidebar .stButton > button:hover {{
        background: {p["bg3"]} !important;
        border-color: {p["border2"]} !important;
    }}
    /* Button inner text spans */
    section[data-testid="stSidebar"] .stButton > button p,
    section[data-testid="stSidebar"] .stButton > button span,
    [data-testid="stSidebar"] .stButton > button p,
    [data-testid="stSidebar"] .stButton > button span {{
        color: {p["txt"]} !important;
    }}
    section[data-testid="stMain"] .stButton > button p,
    section[data-testid="stMain"] .stButton > button span {{
        color: {p["bg"]} !important;
    }}
    [data-testid="stDownloadButton"] > button {{
        background: {p["bg2"]} !important;
        color: {p["txt"]} !important;
        border: 1px solid {p["border"]} !important;
        font-weight: 500 !important;
    }}
    [data-testid="stDownloadButton"] > button:hover {{
        background: {p["bg3"]} !important;
    }}
    [data-testid="stPageLink"] a {{
        background: {p["bg2"]} !important;
        color: {p["txt"]} !important;
        border-radius: 6px !important;
        padding: 7px 16px !important;
        font-weight: 500 !important;
        font-size: 0.82rem !important;
        text-decoration: none !important;
        border: none !important;
        transition: opacity 0.15s ease !important;
    }}
    [data-testid="stPageLink"] a:hover {{ opacity: 0.82 !important; }}

    /* Theme toggle button - secondary style */
    .theme-btn .stButton > button {{
        background: {p["bg2"]} !important;
        color: {p["txt"]} !important;
        border: 1px solid {p["border"]} !important;
        font-size: 0.8rem !important;
        padding: 7px 14px !important;
        font-weight: 500 !important;
    }}
    .theme-btn .stButton > button:hover {{
        background: {p["border"]} !important;
        opacity: 1 !important;
    }}

    /* --- Inputs --- */
    [data-testid="stTextInput"] input,
    [data-testid="stNumberInput"] input,
    [data-testid="stTextArea"] textarea {{
        background: {p["card"]} !important;
        border: 1px solid {p["border"]} !important;
        border-radius: 6px !important;
        color: {p["txt"]} !important;
        font-size: 0.88rem !important;
    }}
    [data-testid="stTextInput"] input:focus,
    [data-testid="stNumberInput"] input:focus {{
        border-color: {p["accent"]} !important;
        box-shadow: 0 0 2px {p["acc_bg"]} !important;
        outline: none !important;
    }}
    [data-baseweb="select"] > div {{
        background: {p["card"]} !important;
        border-color: {p["border"]} !important;
        border-radius: 6px !important;
        color: {p["txt"]} !important;
    }}
    [data-baseweb="popover"] {{
        background: {p["card"]} !important;
        border: 1px solid {p["border"]} !important;
        border-radius: 6px !important;
        box-shadow: 0 8px 24px rgba(0,0,0,0.14) !important;
    }}
    [role="option"] {{ background: {p["card"]} !important; color: {p["txt"]} !important; }}
    [role="option"]:hover {{ background: {p["bg2"]} !important; }}

    [data-testid="stChatInput"] textarea {{
        background: {p["card"]} !important;
        border: 1px solid {p["border"]} !important;
        border-radius: 8px !important;
        color: {p["txt"]} !important;
    }}
    [data-testid="stChatInput"] textarea:focus {{
        border-color: {p["accent"]} !important;
        box-shadow: 0 0 2px {p["acc_bg"]} !important;
    }}

    /* Slider thumb */
    [role="slider"] {{ background: {p["accent"]} !important; border-color: {p["accent"]} !important; }}

    /* --- Tabs --- */
    .stTabs [data-baseweb="tab-list"] {{
        background: {p["bg2"]} !important;
        border-radius: 8px !important;
        padding: 3px !important;
        gap: 2px !important;
        border: 1px solid {p["border"]} !important;
    }}
    .stTabs [data-baseweb="tab"] {{
        background: transparent !important;
        color: {p["txt3"]} !important;
        border-radius: 5px !important;
        font-weight: 500 !important;
        font-size: 0.85rem !important;
        padding: 7px 16px !important;
        border: none !important;
        transition: all 0.15s ease !important;
    }}
    .stTabs [aria-selected="true"] {{
        background: {p["card"]} !important;
        color: {p["txt"]} !important;
        font-weight: 600 !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08) !important;
    }}
    .stTabs [data-baseweb="tab-panel"] {{ padding-top: 1.25rem !important; }}

    /* --- Dataframes --- */
    [data-testid="stDataFrame"] {{
        border: 1px solid {p["border"]} !important;
        border-radius: 8px !important;
        overflow: hidden !important;
    }}
    [data-testid="stDataFrame"] th {{
        background: {p["bg2"]} !important;
        color: {p["txt3"]} !important;
        font-size: 0.72rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.08rem !important;
        text-transform: uppercase;
        border-bottom: 1px solid {p["border"]} !important;
        padding: 10px 14px !important;
    }}
    [data-testid="stDataFrame"] td {{
        color: {p["txt"]} !important;
        font-size: 0.87rem !important;
        border-bottom: 1px solid {p["border"]} !important;
        padding: 9px 14px !important;
        background: {p["card"]} !important;
    }}

    /* --- Alerts --- */
    [data-testid="stAlert"] {{
        border-radius: 6px !important;
        border: none !important;
        border-left: 3px solid !important;
        font-size: 0.87rem !important;
    }}

    /* --- Expanders --- */
    [data-testid="stExpander"] {{
        background: {p["card"]} !important;
        border: 1px solid {p["border"]} !important;
        border-radius: 8px !important;
        overflow: hidden !important;
        margin-bottom: 8px !important;
    }}
    [data-testid="stExpander"] summary {{
        background: {p["card"]} !important;
        color: {p["txt"]} !important;
        font-weight: 600 !important;
        font-size: 0.88rem !important;
        padding: 13px 16px !important;
    }}

    /* --- Progress --- */
    [data-testid="stProgressBar"] > div > div {{ background: {p["accent"]} !important; border-radius: 3px !important; }}
    [data-testid="stProgressBar"] > div {{ background: {p["bg3"]} !important; border-radius: 3px !important; height: 5px !important; }}

    /* --- Chat messages --- */
    [data-testid="stChatMessage"] {{
        background: {p["card"]} !important;
        border: 1px solid {p["border"]} !important;
        border-radius: 8px !important;
        margin-bottom: 10px !important;
        padding: 14px 18px !important;
    }}

    /* --- Divider --- */
    hr {{ border: none !important; border-top: 1px solid {p["border"]} !important; margin: 1.25rem 0 !important; }}

    /* --- Checkbox --- */
    [data-testid="stCheckbox"] label span {{ color: {p["txt2"]} !important; font-size: 0.88rem !important; }}

    /* --- Radio --- */
    [data-testid="stRadio"] label {{ color: {p["txt2"]} !important; font-size: 0.88rem !important; }}

    /* --- Empty state --- */
    .empty-blk {{
        text-align: center;
        padding: 32px 24px;
        color: {p["txt3"]} !important;
        border: 1px dashed {p["border2"]};
        border-radius: 8px;
    }}
    .empty-blk .e-title {{ font-size: 1rem; font-weight: 600; color: {p["txt2"]} !important; margin-bottom: 6px; }}
    .empty-blk .e-sub {{ font-size: 0.85rem; }}

    /* --- Sidebar brand --- */
    .sb-brand {{ padding: 0 0 16px 0; text-align: center; }}
    .sb-icon {{ font-size: 2.5rem; margin-bottom: 8px; }}
    .sb-name {{ font-size: 1.15rem; font-weight: 700; color: {p["txt"]} !important; letter-spacing: -0.2px; }}
    .sb-sub {{ font-size: 0.75rem; color: {p["txt3"]} !important; margin-top: 3px; line-height: 1.4; }}
    .sb-rule {{ height: 1px; background: {p["border"]}; margin: 12px 0; }}
    .sb-nav-lbl {{ font-size: 0.68rem; font-weight: 700; letter-spacing: 0.1rem; text-transform: uppercase; color: {p["txt3"]} !important; margin: 20px 0 8px 0; display: block; }}

    /* Scrollbar */
    ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}
    ::-webkit-scrollbar-thumb {{ background: {p["border2"]}; border-radius: 3px; }}

    /* --- Graph container --- */
    .graph-wrap {{
        border: 1px solid {p["border"]};
        border-radius: 10px;
        overflow: hidden;
        background: {p["card"]};
    }}

    /*
    PROFESSIONAL DASHBOARD COMPONENTS
    */

    /* --- Dashboard Hero --- */
    .dashboard-hero {{
        text-align: left;
        margin-bottom: 2rem;
    }}
    .hero-badge {{
        display: inline-block;
        padding: 4px 12px;
        background: {p["acc_bg"]};
        color: {p["accent"]};
        border: 1px solid {p["acc_bdr"]};
        border-radius: 100px;
        font-size: 0.65rem;
        font-weight: 700;
        letter-spacing: 0.1rem;
        text-transform: uppercase;
        margin-bottom: 12px;
    }}

    /* --- KPI Cards --- */
    .kpi-card {{
        background: {p["card"]};
        border: 1px solid {p["border"]};
        border-radius: 12px;
        padding: 24px;
        position: relative;
        overflow: hidden;
        transition: all 0.2s ease;
        height: 100%;
    }}
    .kpi-card:hover {{
        transform: translateY(-2px);
        box-shadow: 0 6px 24px rgba(0,0,0,0.12);
        border-color: {p["border2"]};
    }}
    .kpi-card::before {{
        content: "";
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 3px;
        background: linear-gradient(90deg, {p["accent"]}, {p["info"]});
    }}
    .kpi-card.kpi-primary::before {{ background: {p["accent"]}; }}
.kpi-card.kpi-success::before {{ background: {p["accent"]}; }}
.kpi-card.kpi-info::before {{ background: {p["info"]}; }}
.kpi-card.kpi-warning::before {{ background: {p["warn"]}; }}

.kpi-label {{
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.1rem;
    text-transform: uppercase;
    color: {p["txt3"]} !important;
    margin-bottom: 10px;
}}
.kpi-value {{
    font-size: 2.5rem;
    font-weight: 700;
    color: {p["txt"]} !important;
    line-height: 1;
    margin-bottom: 4px;
}}
.kpi-unit {{
    font-size: 0.85rem;
    color: {p["txt3"]} !important;
    font-weight: 500;
    margin-bottom: 10px;
}}
.kpi-change {{
    font-size: 0.75rem;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 4px;
    display: inline-block;
}}
.kpi-change.positive {{ background: {p["acc_bg"]}; color: {p["accent"]} !important; }}
.kpi-change.negative {{ background: {p["dan_bg"]}; color: {p["danger"]} !important; }}
.kpi-change.neutral {{ background: {p["bg3"]}; color: {p["txt3"]} !important; }}

/* --- Alert Banner --------------------------------------- */
.alert-banner {{
    display: flex;
    align-items: flex-start;
    gap: 16px;
    padding: 18px 24px;
    border-radius: 10px;
    border: 1px solid;
    margin-bottom: 1.5rem;
}}
.alert-banner.warning {{
    background: {p["warn_bg"]};
    border-color: {p["warn"]};
}}
.alert-banner.danger {{
    background: {p["dan_bg"]};
    border-color: {p["danger"]};
}}
.alert-banner.success {{
    background: {p["acc_bg"]};
    border-color: {p["accent"]};
}}
.alert-icon {{
    font-size: 1.5rem;
    flex-shrink: 0;
}}
.alert-content {{
    flex: 1;
}}
.alert-title {{
    font-size: 0.95rem;
    font-weight: 700;
    color: {p["txt"]} !important;
    margin-bottom: 4px;
}}
.alert-text {{
    font-size: 0.85rem;
    color: {p["txt2"]} !important;
    line-height: 1.5;
}}

/* --- Chart Titles --------------------------------------- */
.chart-title {{
    font-size: 1rem;
    font-weight: 700;
    color: {p["txt"]} !important;
    margin-bottom: 16px;
    padding-bottom: 10px;
    border-bottom: 2px solid {p["border"]};
}}

/* --- Insight Cards -------------------------------------- */
.insight-card {{
    background: {p["card"]};
    border: 1px solid {p["border"]};
    border-radius: 10px;
    padding: 20px 24px;
    margin-bottom: 16px;
    position: relative;
    overflow: hidden;
    transition: all 0.2s ease;
}}
.insight-card:hover {{
    border-color: {p["accent"]};
    box-shadow: 0 4px 16px rgba(0,0,0,0.08);
}}
.insight-badge {{
    display: inline-block;
    padding: 3px 10px;
    background: {p["dan_bg"]};
    color: {p["danger"]};
    border: 1px solid {p["danger"]};
    border-radius: 100px;
    font-size: 0.6rem;
    font-weight: 700;
    letter-spacing: 0.08rem;
    text-transform: uppercase;
    margin-bottom: 10px;
}}
.insight-badge.success {{
    background: {p["acc_bg"]};
    color: {p["accent"]};
    border-color: {p["accent"]};
}}
.insight-title {{
    font-size: 1.05rem;
    font-weight: 700;
    color: {p["txt"]} !important;
    margin-bottom: 10px;
    line-height: 1.3;
}}
.insight-body {{
    font-size: 0.88rem;
    color: {p["txt2"]} !important;
    line-height: 1.7;
    margin-bottom: 12px;
}}
.insight-footer {{
    display: flex;
    gap: 20px;
    padding-top: 12px;
    border-top: 1px solid {p["border"]};
    font-size: 0.75rem;
}}
.insight-confidence {{
    color: {p["txt3"]} !important;
    font-weight: 600;
}}
.insight-source {{
    color: {p["txt3"]} !important;
}}

/* --- Quick Stats Card ------------------------------------ */
.quick-stats-card {{
    background: {p["card"]};
    border: 1px solid {p["border"]};
    border-radius: 10px;
    padding: 20px 24px;
    height: 100%;
}}
.quick-stats-title {{
    font-size: 0.9rem;
    font-weight: 700;
    color: {p["txt"]} !important;
    margin-bottom: 20px;
    text-transform: uppercase;
    letter-spacing: 0.05rem;
}}
.quick-stat-item {{
    padding: 14px 0;
    border-bottom: 1px solid {p["border"]};
}}
.quick-stat-item:last-child {{
    border-bottom: none;
}}
.quick-stat-value {{
    font-size: 1.8rem;
    font-weight: 700;
    color: {p["accent"]} !important;
    line-height: 1;
    margin-bottom: 4px;
}}
.quick-stat-label {{
    font-size: 0.75rem;
    color: {p["txt3"]} !important;
    text-transform: uppercase;
    letter-spacing: 0.05rem;
}}

/* --- Enhanced Nav Cards ---------------------------------- */
.nav-card {{
    background: {p["card"]};
    border: 1px solid {p["border"]};
    border-radius: 10px;
    padding: 24px 22px 20px 22px;
    height: 100%;
    transition: all 0.25s ease;
    position: relative;
    overflow: hidden;
}}
.nav-card:hover {{
    border-color: {p["accent"]};
    box-shadow: 0 8px 24px rgba(34, 197, 94, 0.15);
    transform: translateY(-4px);
}}
.nav-card::before {{
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 2px;
    background: linear-gradient(90deg, {p["accent"]}, {p["info"]});
    opacity: 0;
    transition: opacity 0.25s ease;
}}
.nav-card:hover::before {{
    opacity: 1;
}}
.nav-card-icon {{
    font-size: 2rem;
    margin-bottom: 12px;
}}
.nav-card-tag {{
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.1rem;
    text-transform: uppercase;
    color: {p["accent"]} !important;
    margin-bottom: 10px;
}}
.nav-card-title {{
    font-size: 1.05rem;
    font-weight: 700;
    color: {p["txt"]} !important;
    margin-bottom: 10px;
    line-height: 1.3;
}}
.nav-card-body {{
    font-size: 0.83rem;
    color: {p["txt3"]} !important;
    line-height: 1.65;
    margin-bottom: 14px;
}}

/* --- Enhanced Page Links as Buttons ---------------------- */
[data-testid="stPageLink"] {{
    margin-top: 8px;
}}
[data-testid="stPageLink"] a {{
    background: {p["accent"]} !important;
    color: #FFFFFF !important;
    border-radius: 6px !important;
    padding: 9px 18px !important;
    font-weight: 600 !important;
    font-size: 0.82rem;
    text-decoration: none !important;
    border: none !important;
    transition: all 0.2s ease !important;
    display: inline-block !important;
}}
[data-testid="stPageLink"] a:hover {{
    background: {p["acc_h"]} !important;
    transform: translateX(4px);
}}

/* --- Plotly Charts --------------------------------------- */
.js-plotly-plot {{
    border-radius: 8px;
    overflow: hidden;
}}

/* --- Section Headers: Enhanced --------------------------- */
.sec-label {{
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.12rem;
    text-transform: uppercase;
    color: {p["txt2"]} !important;
    margin: 2.25rem 0 1rem 0;
    padding-bottom: 8px;
    border-bottom: 2px solid {p["border"]};
    display: flex;
    align-items: center;
    gap: 8px;
}}

</style>
"""

def _palette() -> dict:
    return _DARK if st.session_state.get("_dark") else _LIGHT


def apply_theme() -> None:
    if "_dark" not in st.session_state:
        st.session_state["_dark"] = False
    st.markdown(_css(_palette()), unsafe_allow_html=True)


def theme_toggle(label_light: str = "Switch to Dark Mode",
                 label_dark: str = "Switch to Light Mode") -> None:
    """Render a theme toggle button. Call inside a sidebar block."""
    label = label_dark if st.session_state.get("_dark") else label_light
    st.markdown('<div class="theme-btn">', unsafe_allow_html=True)
    if st.button(label, use_container_width=True, key="_theme_toggle_btn"):
        st.session_state["_dark"] = not st.session_state.get("_dark", False)
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)


def status_card(label: str, value: str, desc: str = "", status: str = "ok") -> None:
    st.markdown(
        f'<div class="stat-strip">'
        f'<div class="stat-dot {status}"></div>'
        f'<div class="stat-lbl">{label}</div>'
        f'<div class="stat-val">{value}</div>'
        f'{"<div class=\"stat-desc\">" + desc + "</div>" if desc else ""}'
        f'</div>',
        unsafe_allow_html=True,
    )


def section_header(title: str, level: int = 3) -> None:
    st.markdown(f'<div class="sec-label">{title}</div>', unsafe_allow_html=True)


def empty_state(icon: str, title: str, subtitle: str = "") -> None:
    # icon param kept for API compat but not rendered
    st.markdown(
        f'<div class="empty-blk">'
        f'<div class="e-title">{title}</div>'
        f'{"<div class=\"e-sub\">" + subtitle + "</div>" if subtitle else ""}'
        f'</div>',
        unsafe_allow_html=True,
    )


def badge(text: str, color: str = "grey") -> str:
    """Return inline HTML badge. color: green | red | amber | grey"""
    p = _palette()
    colors = {
        "green": (p["acc_bg"], p["accent"], p["acc_bdr"]),
        "red": (p["dan_bg"], p["danger"], p["danger"]),
        "amber": (p["warn_bg"], p["warn"], p["warn"]),
        "grey": (p["bg3"], p["txt3"], p["border2"]),
    }
    bg, fg, bdr = colors.get(color, colors["grey"])
    return (
        f'<span style="display:inline-block;padding:2px 9px;border-radius:100px;'
        f'font-size:0.7rem;font-weight:600;letter-spacing:0.04rem;'
        f'background:{bg};color:{fg};border:1px solid {bdr}">{text}</span>'
    )
