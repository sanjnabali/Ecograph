"""
src/ecograph/graph/connection.py

Neo4j driver lifecycle management.

Design decisions:
- Module-level singleton (_driver) so we create one connection pool per
  process, not one per request. Neo4j recommends this pattern explicitly.
- get_driver() does not automatically create the driver; callers must call
  init_driver() first. This makes the dependency explicit and testable —
  unit tests can call init_driver(driver=mock_driver) with a mock.
- session() is a thin context manager wrapper so callers never import
  neo4j directly; they only import from this module.
- execute() / execute_one() cover 90% of query needs without callers
  managing session lifecycle. For transactions that span multiple queries,
  callers get a session via session() and manage it themselves.
- Errors from Neo4j are re-raised as domain-specific exceptions so
  callers do not need to import neo4j exception classes.
"""

import logging
import threading
from contextlib import contextmanager
from typing import Any, Generator, Optional

from neo4j import Driver, GraphDatabase, Session
from neo4j.exceptions import (
    AuthError,
    ServiceUnavailable,
    SessionExpired,
    Neo4jError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state — protected by a lock for thread safety
# ---------------------------------------------------------------------------

_driver: Optional[Driver] = None
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Domain exceptions — callers catch these, not neo4j internals
# ---------------------------------------------------------------------------

class Neo4jConnectionError(RuntimeError):
    """Raised when the driver cannot connect to Neo4j."""


class Neo4jAuthenticationError(RuntimeError):
    """Raised when Neo4j rejects the supplied credentials."""


class Neo4jQueryError(RuntimeError):
    """Raised when a Cypher query fails at the database level."""


# ---------------------------------------------------------------------------
# Driver lifecycle
# ---------------------------------------------------------------------------

def init_driver(
    uri: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    database: Optional[str] = None,
    max_pool_size: int = 50,
    timeout: int = 30,
    driver: Optional[Driver] = None,
) -> Driver:
    """
    Initialise (or replace) the module-level driver singleton.

    Parameters
    ----------
    uri, username, password, database :
        Connection details. When omitted, values are read from
        ecograph.config.settings. Passing them explicitly is useful in
        tests and scripts that want to target a different instance.
    max_pool_size :
        Neo4j connection pool size. Default 50 is suitable for a
        single-process application with concurrent async requests.
    timeout :
        Socket-level connection timeout in seconds.
    driver :
        Inject a pre-built Driver (e.g. a mock in tests). When provided,
        all other parameters are ignored and no verification call is made.

    Returns
    -------
    Driver
        The newly initialised driver.

    Raises
    ------
    Neo4jAuthenticationError
        If the credentials are rejected by the server.
    Neo4jConnectionError
        If the server is unreachable or the URI is malformed.
    """
    global _driver

    with _lock:
        # Allow test injection of a pre-built driver
        if driver is not None:
            if _driver is not None:
                _driver.close()
            _driver = driver
            logger.debug("Neo4j driver injected (test/override mode).")
            return _driver

        # Read from settings when parameters are not provided
        if uri is None or username is None or password is None:
            from ecograph.config import settings as _s
            uri      = uri      or _s.NEO4J_URI
            username = username or _s.NEO4J_USERNAME
            password = password or _s.NEO4J_PASSWORD
            database = database or _s.NEO4J_DATABASE
            max_pool_size = _s.NEO4J_MAX_POOL
            timeout       = _s.NEO4J_TIMEOUT

        if not uri or not password:
            raise Neo4jConnectionError(
                "NEO4J_URI and NEO4J_PASSWORD must be set before initialising "
                "the driver. Call settings.validate() at startup."
            )

        logger.info("Initialising Neo4j driver.", extra={"uri": uri})

        try:
            new_driver = GraphDatabase.driver(
                uri,
                auth=(username, password),
                database=database,
                connection_timeout=timeout,
                max_connection_pool_size=max_pool_size,
            )
            # Verify the connection is actually usable
            new_driver.verify_connectivity()
        except AuthError as exc:
            raise Neo4jAuthenticationError(
                f"Neo4j rejected credentials for user '{username}' at '{uri}'. "
                "Check NEO4J_USERNAME and NEO4J_PASSWORD in your .env file."
            ) from exc
        except ServiceUnavailable as exc:
            raise Neo4jConnectionError(
                f"Cannot reach Neo4j at '{uri}'. "
                "Verify the instance is running and NEO4J_URI is correct."
            ) from exc
        except Exception as exc:
            raise Neo4jConnectionError(
                f"Unexpected error while connecting to Neo4j: {exc}"
            ) from exc

        # Close old driver if we are replacing it
        if _driver is not None:
            try:
                _driver.close()
            except Exception:
                pass   # best-effort

        _driver = new_driver
        logger.info("Neo4j driver initialised successfully.")
        return _driver


def get_driver() -> Driver:
    """
    Return the current driver singleton.

    Raises
    ------
    Neo4jConnectionError
        If init_driver() has not been called yet.
    """
    if _driver is None:
        raise Neo4jConnectionError(
            "Neo4j driver has not been initialised. "
            "Call init_driver() before using the database."
        )
    return _driver


def close_driver() -> None:
    """
    Close and discard the current driver singleton.

    Safe to call even if no driver has been initialised.
    Typically called in application shutdown hooks.
    """
    global _driver
    with _lock:
        if _driver is not None:
            try:
                _driver.close()
                logger.info("Neo4j driver closed.")
            except Exception as exc:
                logger.warning("Error closing Neo4j driver: %s", exc)
            finally:
                _driver = None


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

@contextmanager
def session(**kwargs: Any) -> Generator[Session, None, None]:
    """
    Context manager that yields a Neo4j Session.

    Any keyword arguments are forwarded to driver.session() — e.g.
    database="mydb", fetch_size=200.

    Usage:
        with connection.session() as s:
            result = s.run("MATCH (n:Company) RETURN n LIMIT 10")
            data = result.data()

    Raises
    ------
    Neo4jConnectionError
        If the driver is not initialised.
    Neo4jQueryError
        If the session cannot be acquired (pool exhausted, network failure).
    """
    driver = get_driver()
    try:
        with driver.session(**kwargs) as s:
            yield s
    except (ServiceUnavailable, SessionExpired) as exc:
        raise Neo4jConnectionError(
            f"Neo4j session unavailable: {exc}"
        ) from exc
    except Neo4jError as exc:
        raise Neo4jQueryError(
            f"Neo4j session error: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Query execution helpers
# ---------------------------------------------------------------------------

def execute(
    cypher: str,
    parameters: Optional[dict] = None,
    **session_kwargs: Any,
) -> list[dict]:
    """
    Execute a Cypher query and return all results as a list of dicts.

    Parameters
    ----------
    cypher :
        Cypher query string. Use $param_name syntax for parameters.
    parameters :
        Dict of query parameters. Never format values directly into the
        query string — always use parameters to prevent injection.
    **session_kwargs :
        Forwarded to driver.session() (e.g. database=...).

    Returns
    -------
    list[dict]
        Each element is one row returned by Neo4j, as a plain Python dict.
        Property values are Python-native types (int, float, str, list, etc.).

    Raises
    ------
    Neo4jQueryError
        If the Cypher is invalid or the query fails at the DB level.
    Neo4jConnectionError
        If the driver is not available.
    """
    params = parameters or {}
    try:
        with session(**session_kwargs) as s:
            result = s.run(cypher, params)
            return result.data()
    except (Neo4jConnectionError, Neo4jQueryError):
        raise
    except Neo4jError as exc:
        raise Neo4jQueryError(
            f"Cypher execution failed.\n"
            f"Query (first 200 chars): {cypher[:200]}\n"
            f"Neo4j error: {exc}"
        ) from exc
    except Exception as exc:
        raise Neo4jQueryError(
            f"Unexpected error executing Cypher: {exc}"
        ) from exc


def execute_one(
    cypher: str,
    parameters: Optional[dict] = None,
    **session_kwargs: Any,
) -> Optional[dict]:
    """
    Execute a Cypher query and return the first result row, or None.

    Convenience wrapper for queries that are expected to return 0 or 1 rows.

    Returns
    -------
    dict | None
    """
    rows = execute(cypher, parameters, **session_kwargs)
    return rows[0] if rows else None


def execute_write(
    cypher: str,
    parameters: Optional[dict] = None,
    **session_kwargs: Any,
) -> list[dict]:
    """
    Execute a write (CREATE / MERGE / SET / DELETE) Cypher query.

    Identical to execute() but semantically signals write intent to callers,
    and uses an explicit write transaction which neo4j routes to the primary
    node in a clustered setup.
    """
    params = parameters or {}
    try:
        with session(**session_kwargs) as s:
            result = s.execute_write(
                lambda tx: tx.run(cypher, params).data()
            )
            return result or []
    except (Neo4jConnectionError, Neo4jQueryError):
        raise
    except Neo4jError as exc:
        raise Neo4jQueryError(
            f"Cypher write failed.\n"
            f"Query (first 200 chars): {cypher[:200]}\n"
            f"Neo4j error: {exc}"
        ) from exc


def health_check() -> bool:
    """
    Return True if Neo4j is reachable and responds to a trivial query.

    Safe to call from health-check endpoints — never raises, returns bool.
    """
    try:
        result = execute_one("RETURN 1 AS ok")
        return result is not None and result.get("ok") == 1
    except Exception:
        return False