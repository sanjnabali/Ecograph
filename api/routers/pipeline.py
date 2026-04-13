"""
api/routers/pipeline.py - Pipeline trigger and status endpoints.

POST /api/pipeline/run         - trigger a full or partial pipeline run (background)
GET  /api/pipeline/status      - current run status
GET  /api/pipeline/last-result - result of the most recent completed run

The pipeline runs in a background thread so the HTTP response returns
immediately. Status polling keeps the frontend in sync.

Safety:
  - Only one run allowed at a time (idempotent guard)
  - All stages wrapped in try/except so a failure in one stage
    doesn't silently kill the background thread
"""

import logging
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from neo4j import Driver
from pydantic import BaseModel

from api.deps import get_driver

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/pipeline", tags=["Pipeline"])

# -----------------------------------------------------------------------------
# In-memory run state  (single-process; sufficient for this app)
# -----------------------------------------------------------------------------

class RunStatus(str, Enum):
    IDLE      = "idle"
    RUNNING   = "running"
    SUCCEEDED = "succeeded"
    FAILED    = "failed"

class _RunState:
    """Thread-safe run state container."""

    def __init__(self):
        self._lock    = threading.Lock()
        self.status   : RunStatus      = RunStatus.IDLE
        self.stage    : str            = ""
        self.started  : Optional[str]  = None
        self.finished : Optional[str]  = None
        self.result   : Dict[str, Any] = {}
        self.errors   : List[str]      = []

    def start(self, stages: List[str]) -> None:
        with self._lock:
            self.status   = RunStatus.RUNNING
            self.stage    = stages[0] if stages else "starting"
            self.started  = datetime.now(timezone.utc).isoformat()
            self.finished = None
            self.result   = {}
            self.errors   = []

    def set_stage(self, stage: str) -> None:
        with self._lock:
            self.stage = stage

    def finish(self, result: Dict[str, Any], errors: List[str], warnings: List[str]) -> None:
        with self._lock:
            # Only hard errors (extraction abort / Neo4j failure) mark as FAILED.
            # Non-fatal warnings (geo, erp, resolution) -> SUCCEEDED with warnings.
            self.status   = RunStatus.FAILED if errors else RunStatus.SUCCEEDED
            self.finished = datetime.now(timezone.utc).isoformat()
            self.result   = result
            self.errors   = errors + ([f"[warning] {w}" for w in warnings] if warnings else [])
            self.stage    = "done"

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "status":   self.status,
                "stage":    self.stage,
                "started":  self.started,
                "finished": self.finished,
                "result":   self.result,
                "errors":   self.errors,
            }

_state = _RunState()

# -----------------------------------------------------------------------------
# Request / Response models
# -----------------------------------------------------------------------------

class PipelineRunRequest(BaseModel):
    skip_extract:  bool = False
    skip_neo4j:    bool = False
    skip_erp:      bool = False
    skip_geo:      bool = False
    skip_resolve:  bool = False

class PipelineStatusResponse(BaseModel):
    status:   RunStatus
    stage:    str
    started:  Optional[str]
    finished: Optional[str]
    errors:   List[str]

class PipelineResultResponse(BaseModel):
    status:   RunStatus
    started:  Optional[str]
    finished: Optional[str]
    result:   Dict[str, Any]
    errors:   List[str]

# -----------------------------------------------------------------------------
# Background runner
# -----------------------------------------------------------------------------

def _run_pipeline_background(
    request: PipelineRunRequest,
    driver:  Driver,
) -> None:
    """
    Runs the full pipeline in a background thread.
    Updates _state so the /status endpoint stays live.
    """
    errors: List[str]   = []    # fatal - marks run as FAILED
    warnings: List[str] = []    # non-fatal - run still SUCCEEDED
    result: Dict[str, Any] = {}

    # --- Stage 1: LLM Extraction ---
    if not request.skip_extract:
        _state.set_stage("extraction")
        try:
            from src.agents.extractor import Scope3Extractor
            extractor = Scope3Extractor()
            extractor.process_all_documents()
            logger.info("Pipeline: extraction stage complete.")
        except ValueError as exc:
            # Missing API key - abort immediately
            errors.append(f"Extraction failed (missing API key): {exc}")
            _state.finish(result, errors, warnings)
            return
        except Exception as exc:
            errors.append(f"Extraction error: {exc}")
            logger.error(f"Pipeline extraction error: {exc}", exc_info=True)
            # Continue - partial triples may still be usable

    # --- Stage 2: Neo4j Load ---
    if not request.skip_neo4j:
        _state.set_stage("neo4j_load")
        try:
            from src.graph.store import apply_schema, ingest_all_triples
            apply_schema(driver)
            neo4j_stats = ingest_all_triples(driver)
            result["neo4j"] = neo4j_stats
            logger.info(f"Pipeline: Neo4j stage complete - {neo4j_stats}")
        except Exception as exc:
            errors.append(f"Neo4j load error: {exc}")
            logger.error(f"Pipeline Neo4j error: {exc}", exc_info=True)

    # --- Stage 3: Entity Resolution ---
    if not request.skip_neo4j and not request.skip_resolve:
        _state.set_stage("resolution")
        try:
            from src.graph.resolver import resolve_entities
            resolution_stats = resolve_entities(driver)
            result["resolution"] = resolution_stats
            logger.info(f"Pipeline: resolution stage complete - {resolution_stats}")
        except Exception as exc:
            warnings.append(f"Resolution non-fatal: {exc}")
            logger.warning(f"Pipeline resolution error (non-fatal): {exc}")

    # --- Stage 4: ERP Load ---
    if not request.skip_erp:
        _state.set_stage("erp_load")
        try:
            from src.ingestion.erp_loader import load_erp_suppliers
            erp_stats = load_erp_suppliers(driver)
            result["erp"] = erp_stats
            logger.info(f"Pipeline: ERP stage complete - {erp_stats}")
        except Exception as exc:
            warnings.append(f"ERP load non-fatal: {exc}")
            logger.warning(f"Pipeline ERP error: {exc}")

    # --- Stage 5: Geo Enrichment ---
    if not request.skip_geo:
        _state.set_stage("geo_enrichment")
        try:
            from src.ingestion.geo_loader import enrich_regions, enrich_facilities
            region_stats   = enrich_regions(driver)
            facility_stats = enrich_facilities(driver)
            result["geo"] = {"regions": region_stats, "facilities": facility_stats}
            logger.info(f"Pipeline: geo stage complete - {result['geo']}")
        except Exception as exc:
            warnings.append(f"Geo enrichment non-fatal: {exc}")
            logger.warning(f"Pipeline geo error: {exc}")

    _state.finish(result, errors, warnings)
    logger.info(
        f"Pipeline run complete - "
        f"status={_state.status} fatal={len(errors)} warnings={len(warnings)}"
    )

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

@router.post(
    "/run",
    response_model=PipelineStatusResponse,
    status_code=202,
    summary="Trigger a pipeline run (async, returns immediately)",
    description=(
        "Starts a background pipeline run. Returns 202 Accepted immediately. "
        "Poll GET /api/pipeline/status to check progress. "
        "Returns 409 if a run is already in progress."
    ),
)
def trigger_run(
    payload: PipelineRunRequest = PipelineRunRequest(),
    driver:  Driver             = Depends(get_driver),
) -> PipelineStatusResponse:
    # Guard: only one run at a time
    if _state.status == RunStatus.RUNNING:
        raise HTTPException(
            status_code=409,
            detail={
                "error":   "run_in_progress",
                "message": "A pipeline run is already in progress. Poll /status to track it.",
                "stage":   _state.stage,
            },
        )

    # Determine which stages will run
    stages = []
    if not payload.skip_extract:  stages.append("extraction")
    if not payload.skip_neo4j:    stages.append("neo4j_load")
    if not payload.skip_resolve:  stages.append("resolution")
    if not payload.skip_erp:      stages.append("erp_load")
    if not payload.skip_geo:      stages.append("geo_enrichment")

    if not stages:
        raise HTTPException(
            status_code=400,
            detail={
                "error":   "nothing_to_run",
                "message": "All stages are skipped. Enable at least one stage.",
            },
        )

    _state.start(stages)

    thread = threading.Thread(
        target=_run_pipeline_background,
        args=(payload, driver),
        daemon=True,
        name="ecograph-pipeline",
    )
    thread.start()
    logger.info(f"Pipeline thread started. Stages: {stages}")

    return PipelineStatusResponse(**_state.to_dict())

@router.get(
    "/status",
    response_model=PipelineStatusResponse,
    summary="Current pipeline run status",
    description="Poll this endpoint to track progress of a running pipeline.",
)
def get_status() -> PipelineStatusResponse:
    return PipelineStatusResponse(**_state.to_dict())

@router.get(
    "/last-result",
    response_model=PipelineResultResponse,
    summary="Result of the most recent completed pipeline run",
)
def get_last_result() -> PipelineResultResponse:
    state = _state.to_dict()
    if state["status"] == RunStatus.RUNNING:
        raise HTTPException(
            status_code=409,
            detail={
                "error":   "run_in_progress",
                "message": "Run is still in progress.",
                "stage":   state["stage"],
            },
        )
    return PipelineResultResponse(**state)