"""
api/deps.py - FastAPI dependency injection.

Provides a managed Neo4j driver that is:
  - Created once at app startup (lifespan)
  - Shared across requests via app.state
  - Properly closed at shutdown
  - Injected into route handlers via Depends(get_driver)

Never import get_driver() from src directly inside a route -
always use the Depends pattern so the driver lifecycle is centralised.
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from neo4j import Driver

from src.graph.connection import get_driver as _create_driver

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# App Lifespan - driver created once, closed on shutdown
# -----------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.
    Runs startup logic before `yield` and shutdown logic after.
    """
    # --- Startup -------------------------------------------------------------
    logger.info("EcoGraph API starting up...")
    try:
        driver = _create_driver()
        app.state.driver = driver
        logger.info("Neo4j driver initialised and stored in app.state.")
    except (EnvironmentError, ConnectionError, PermissionError) as exc:
        # Log clearly but don't crash - routes will return 503 gracefully
        logger.error(f"Neo4j unavailable at startup: {exc}")
        app.state.driver = None

    yield    # <- app is running here

    # --- Shutdown ------------------------------------------------------------
    logger.info("EcoGraph API shutting down...")
    driver = getattr(app.state, "driver", None)
    if driver:
        driver.close()
        logger.info("Neo4j driver closed.")

# -----------------------------------------------------------------------------
# Dependency: inject driver into route handlers
# -----------------------------------------------------------------------------

def get_driver(request: Request) -> Driver:
    """
    FastAPI dependency that injects the shared Neo4j driver.

    Raises HTTP 503 if:
      - Driver was never created (bad env vars / Neo4j unreachable at startup)
      - Driver connection was lost during runtime

    Usage in a route:
        @router.get("/something")
        def my_route(driver: Driver = Depends(get_driver)):
            ...
    """
    driver: Driver = getattr(request.app.state, "driver", None)

    if driver is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "database_unavailable",
                "message": (
                    "Neo4j is not connected. "
                    "Check NEO4J_URI and NEO4J_PASSWORD in your .env file "
                    "and make sure Neo4j is running."
                ),
            },
        )

    # Lightweight liveness check: trivial Cypher instead of verify_connectivity()
    # which opens a full new TCP handshake on every request.
    try:
        with driver.session() as _s:
            _s.run("RETURN 1").consume()
    except Exception as exc:
        logger.error(f"Neo4j liveness check failed: {exc}")
        raise HTTPException(
            status_code=503,
            detail={
                "error": "database_connection_lost",
                "message": "Lost connection to Neo4j. Please retry.",
            },
        )

    return driver