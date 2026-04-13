"""
api/main.py - FastAPI application factory.

This is the entry point for the EcoGraph backend API.

Run locally:
    uvicorn api.main:app --reload --port 8000

Endpoints:
    GET  /                               - welcome + version
    GET  /api/stats/health               - DB health check
    GET  /api/stats/summary              - node/rel counts
    GET  /api/stats/emissions            - emissions by company
    GET  /api/stats/categories           - category breakdown
    GET  /api/stats/targets              - net-zero targets
    GET  /api/graph/nodes                - paginated node list
    GET  /api/graph/search               - full-text node search
    GET  /api/graph/node/{name}          - single node + relationships
    GET  /api/graph/subgraph/{name}      - ego-graph
    GET  /api/graph/map                  - geocoded nodes for map
    GET  /api/graph/supply-chain         - supply chain edges
    POST /api/chat/message               - AI chat (Gemini + graph context)
    GET  /api/chat/suggestions           - example questions
    POST /api/pipeline/run               - trigger pipeline (async)
    GET  /api/pipeline/status            - pipeline run status
    GET  /api/pipeline/last-result       - last run result
    GET  /docs                           - Swagger UI (auto-generated)
    GET  /redoc                          - ReDoc UI (auto-generated)
"""

import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.deps import lifespan
from api.errors import register_error_handlers
from api.routers import chat, graph, pipeline, stats
from src.config.logging_config import setup_logging
from src.config.settings import LOG_FILE

# --- Logging - must be first -------------------------------------------------
setup_logging(log_file=LOG_FILE)
logger = logging.getLogger(__name__)

# --- App ---------------------------------------------------------------------
app = FastAPI(
    title       = "EcoGraph API",
    description = (
        "AI-powered ESG Knowledge Graph API for Scope 3 carbon emissions analysis. "
        "Backed by Neo4j, powered by Gemini."
    ),
    version     = "1.0.0",
    docs_url    = "/docs",
    redoc_url   = "/redoc",
    lifespan    = lifespan,
)

# --- CORS - allow the Next.js frontend on any localhost port + Vercel ---
_RAW_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:3001,https://*.vercel.app",
)
_CORS_ORIGINS = [o.strip() for o in _RAW_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins      = _CORS_ORIGINS,
    allow_credentials  = True,
    allow_methods      = ["GET", "POST", "OPTIONS"],
    allow_headers      = ["*"],
)

# --- Global error handlers ---------------------------------------------------
register_error_handlers(app)

# --- Routers -----------------------------------------------------------------
app.include_router(stats.router)
app.include_router(graph.router)
app.include_router(chat.router)
app.include_router(pipeline.router)

# --- Root endpoint -----------------------------------------------------------
@app.get("/", include_in_schema=False)
def root():
    return JSONResponse({
        "name":    "EcoGraph API",
        "version": "1.0.0",
        "status":  "running",
        "time":    datetime.now(timezone.utc).isoformat(),
        "docs":    "/docs",
    })