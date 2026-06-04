"""
scripts/export_report.py

Standalone CLI to generate an EcoGraph audit report for a given query
without running the full interactive Streamlit app.

Useful for:
- Scheduled automated reporting (cron / GitHub Actions)
- CI smoke tests
- Generating reports from existing graph data

Usage:
    python scripts/export_report.py \
        --query "Supply chain emission hotspots for Q1 2025" \
        --out reports/q1_2025.pdf

The script invokes the full agent pipeline and saves both the Markdown
and PDF versions of the report.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("export_report")

_DEFAULT_OUT = Path("reports") / f"ecograph_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an EcoGraph audit report")
    parser.add_argument(
        "--query",
        required=True,
        help="Natural language query / topic for the report",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT,
        help="Output path for the PDF report",
    )
    parser.add_argument(
        "--markdown-only",
        action="store_true",
        help="Save Markdown instead of PDF (no ReportLab required)",
    )

    args = parser.parse_args()

    # Validate credentials
    try:
        from ecograph.config.settings import settings
        settings.validate()
    except Exception as exc:
        logger.error("Credential validation failed: %s", exc)
        sys.exit(1)

    # Run agent pipeline
    logger.info("Running EcoGraph agent pipeline for query: '%s'", args.query)
    try:
        from ecograph.agents.graph import get_agent
        agent = get_agent()
        state = agent.invoke({
            "query": args.query,
            "iteration_count": 0,
            "errors": [],
        })
    except Exception as exc:
        logger.error("Agent pipeline failed: %s", exc)
        sys.exit(1)

    # Determine output path and format
    out_path = args.out
    if args.markdown_only:
        out_path = out_path.with_suffix(".md")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Check if PDF was already written by the reporter agent
    agent_pdf = state.get("report_path")
    if agent_pdf and Path(agent_pdf).exists() and not args.markdown_only:
        import shutil
        shutil.copy(agent_pdf, out_path)
        logger.info("Report copied from agent output to: %s", out_path)
    elif state.get("report_markdown"):
        md = state["report_markdown"]
        if args.markdown_only or out_path.suffix == ".md":
            out_path.write_text(md, encoding="utf-8")
            logger.info("Markdown report saved to: %s", out_path)
        else:
            # Try to write PDF directly
            try:
                from ecograph.agents.reporter import _write_pdf
                _write_pdf(md, str(out_path))
                logger.info("PDF report saved to: %s", out_path)
            except Exception as exc:
                logger.warning("PDF generation failed (%s) - saving as Markdown.", exc)
                md_path = out_path.with_suffix(".md")
                md_path.write_text(md, encoding="utf-8")
                logger.info("Markdown fallback saved to: %s", md_path)
    else:
        logger.error("No report content produced by the agent pipeline.")
        if state.get("errors"):
            for err in state["errors"]:
                logger.error("  Agent error: %s", err)
        sys.exit(1)

    logger.info("Export complete.")


if __name__ == "__main__":
    main()