# app/components/ui_components.py - Reusable professional UI components for EcoGraph dashboard

from __future__ import annotations
import streamlit as st
from typing import Optional, Literal


def kpi_card(
    label: str,
    value: str,
    unit: str = "",
    change: str = "",
    change_type: Literal["positive", "negative", "neutral"] = "neutral",
    card_type: Literal["primary", "success", "info", "warning"] = "primary",
) -> None:
    """
    Render a professional KPI card with gradient border and hover effects.

    Args:
        label: Card label (uppercase)
        value: Main value to display
        unit: Unit description
        change: Change description (e.g., "↑ 2.3% from last month")
        change_type: Type of change indicator
        card_type: Visual style of card
    """
    st.markdown(
        f'<div class="kpi-card kpi-{card_type}">'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>'
        f'<div class="kpi-unit">{unit}</div>'
        f'<div class="kpi-change {change_type}">{change}</div>' if change else ""
        f'</div>',
        unsafe_allow_html=True,
    )


def alert_banner(
    title: str,
    message: str,
    alert_type: Literal["warning", "danger", "success"] = "warning",
    icon: str = "⚠️",
) -> None:
    """
    Render a prominent alert banner for important notifications.

    Args:
        title: Alert title
        message: Alert message (can include HTML)
        alert_type: Visual style
        icon: Icon emoji
    """
    st.markdown(
        f'<div class="alert-banner {alert_type}">'
        f'<div class="alert-icon">{icon}</div>'
        f'<div class="alert-content">'
        f'<div class="alert-title">{title}</div>'
        f'<div class="alert-text">{message}</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def insight_card(
    title: str,
    body: str,
    badge_text: str = "",
    badge_type: Literal["success", "default"] = "default",
    confidence: str = "",
    sources: str = "",
) -> None:
    """
    Render an AI insight card with optional confidence and source information.

    Args:
        title: Insight title
        body: Insight body text (can include HTML)
        badge_text: Optional badge text
        badge_type: Badge style
        confidence: Confidence level text
        sources: Data sources text
    """
    badge_html = ""
    if badge_text:
        badge_class = f"insight-badge {badge_type}" if badge_type != "default" else "insight-badge"
        badge_html = f'<div class="{badge_class}">{badge_text}</div>'

    footer_html = ""
    if confidence or sources:
        footer_items = []
        if confidence:
            footer_items.append(f'<span class="insight-confidence">{confidence}</span>')
        if sources:
            footer_items.append(f'<span class="insight-source">{sources}</span>')
        footer_html = f'<div class="insight-footer">{" • ".join(footer_items)}</div>'

    st.markdown(
        f'<div class="insight-card">'
        f'{badge_html}'
        f'<div class="insight-title">{title}</div>'
        f'<div class="insight-body">{body}</div>'
        f'{footer_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def quick_stats_card(title: str, stats: list[tuple[str, str]]) -> None:
    """
    Render a quick stats card with multiple stat items.

    Args:
        title: Card title
        stats: List of (value, label) tuples
    """
    stats_html = ""
    for value, label in stats:
        stats_html += (
            f'<div class="quick-stat-item">'
            f'<div class="quick-stat-value">{value}</div>'
            f'<div class="quick-stat-label">{label}</div>'
            f'</div>'
        )

    st.markdown(
        f'<div class="quick-stats-card">'
        f'<div class="quick-stats-title">{title}</div>'
        f'{stats_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def nav_card(
    icon: str,
    tag: str,
    title: str,
    description: str,
) -> None:
    """
    Render a navigation card with hover effects.

    Args:
        icon: Icon emoji
        tag: Category tag (uppercase)
        title: Card title
        description: Card description
    """
    st.markdown(
        f'<div class="nav-card">'
        f'<div class="nav-card-icon">{icon}</div>'
        f'<div class="nav-card-tag">{tag}</div>'
        f'<div class="nav-card-title">{title}</div>'
        f'<div class="nav-card-body">{description}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def dashboard_hero(
    badge_text: str,
    title: str,
    subtitle: str,
) -> None:
    """
    Render a dashboard hero section with badge and titles.

    Args:
        badge_text: Hero badge text (uppercase)
        title: Main page title
        subtitle: Page subtitle
    """
    st.markdown(
        f'<div class="dashboard-hero">'
        f'<div class="hero-badge">{badge_text}</div>'
        f'<div class="pg-title">{title}</div>'
        f'<div class="pg-sub">{subtitle}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def chart_title(title: str) -> None:
    """
    Render a styled chart title with bottom border.

    Args:
        title: Chart title
    """
    st.markdown(
        f'<div class="chart-title">{title}</div>',
        unsafe_allow_html=True,
    )


def loading_spinner(message: str = "Loading...") -> st.spinner:
    """
    Return a context manager for a loading spinner.

    Args:
        message: Loading message

    Returns:
        Streamlit spinner context manager
    """
    return st.spinner(f"{message}")


def status_indicator(
    status: Literal["online", "offline", "warning"],
    label: str,
) -> str:
    """
    Return HTML for a status indicator dot.

    Args:
        status: Status type
        label: Status label

    Returns:
        HTML string
    """
    color_map = {
        "online": "#22C55E",
        "offline": "#EF4444",
        "warning": "#F59E0B",
    }
    color = color_map.get(status, "#94A3B8")
    return (
        f'<span style="display: inline-flex; align-items: center; gap: 6px;">'
        f'<span style="width: 8px; height: 8px; border-radius: 50%; background: {color};"></span>'
        f'{label}'
        f'</span>'
    )


def metric_comparison_card(
    label: str,
    current_value: str,
    previous_value: str,
    unit: str = "",
    is_positive_good: bool = True,
) -> None:
    """
    Render a metric card with comparison to previous period.

    Args:
        label: Metric label
        current_value: Current period value
        previous_value: Previous period value
        unit: Unit of measurement
        is_positive_good: Whether increase is positive
    """
    try:
        current = float(current_value.replace(",", "").replace("M", "e6").replace("B", "e9"))
        previous = float(previous_value.replace(",", "").replace("M", "e6").replace("B", "e9"))
        change_pct = ((current - previous) / previous) * 100

        arrow = "↑" if change_pct > 0 else "↓" if change_pct < 0 else ""
        change_type = "positive" if (change_pct > 0) == is_positive_good else "negative" if change_pct != 0 else "neutral"
        change_text = f"{arrow} {abs(change_pct):.1f}% vs. previous"
    except:
        change_text = "- No comparison"
        change_type = "neutral"

    kpi_card(
        label=label,
        value=current_value,
        unit=unit,
        change=change_text,
        change_type=change_type,
    )


def data_quality_badge(score: float) -> str:
    """
    Return HTML badge for data quality score.

    Args:
        score: Quality score (0-100)

    Returns:
        HTML string
    """
    if score >= 90:
        color = "green"
        label = "High Quality"
    elif score >= 70:
        color = "amber"
        label = "Medium Quality"
    else:
        color = "red"
        label = "Low Quality"

    from app.theme import badge
    return badge(f"{score:.1f}% {label}", color)


def progress_indicator(
    label: str,
    current: int,
    total: int,
    color: str = "#22C55E",
) -> None:
    """
    Render a custom progress indicator.

    Args:
        label: Progress label
        current: Current value
        total: Total/target value
        color: Progress bar color
    """
    pct = (current / total * 100) if total > 0 else 0

    st.markdown(
        f'<div style="margin-bottom: 16px;">'
        f'<div style="display: flex; justify-content: space-between; margin-bottom: 6px;">'
        f'<span style="font-size: 0.85rem; font-weight: 600;">{label}</span>'
        f'<span style="font-size: 0.85rem; color: #94A3B8;">{current}/{total}</span>'
        f'</div>'
        f'<div style="width: 100%; height: 8px; background: #334155; border-radius: 4px; overflow: hidden;">'
        f'<div style="width: {pct}%; height: 100%; background: {color}; transition: width 0.3s ease;"></div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def spacer(size: Literal["small", "medium", "large"] = "medium") -> None:
    """
    Add vertical spacing.

    Args:
        size: Spacing size
    """
    size_map = {
        "small": "1rem",
        "medium": "2rem",
        "large": "3rem",
    }
    height = size_map.get(size, "2rem")
    st.markdown(f'<div style="margin-top: {height};"></div>', unsafe_allow_html=True)