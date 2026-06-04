"""
src/ecograph/knowledge_graph/neo4j_client.py

Neo4j AuraDB client using the HTTP Query API (v2).

Uses HTTPS port 443 instead of the Bolt protocol (port 7687) because
many ISPs/networks/firewalls block port 7687 or interfere with the
Bolt routing discovery handshake.

The Query API endpoint is:
https://<instance-id>.databases.neo4j.io/db/<instance-id>/query/v2

This works everywhere HTTPS works - no special ports needed.
"""
from __future__ import annotations

import base64
import json
import logging
import threading
from typing import Any, Optional

import requests

from ecograph.config import settings

logger = logging.getLogger(__name__)


class Neo4jConnectionError(RuntimeError):
    """Raised when the database is unreachable or credentials are invalid."""


class Neo4jQueryError(RuntimeError):
    """Raised when a Cypher query fails."""


class Neo4jClient:
    """
    Neo4j AuraDB client via the HTTP Query API v2.

    Usage:
        client = Neo4jClient()
        records = client.execute_read(
            "MATCH (s:Supplier) RETURN s.name AS name LIMIT 10"
        )
    """

    def __init__(
        self,
        query_api_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ) -> None:
        self._api_url = query_api_url or settings.NEO4J_QUERY_API
        self._username = username or settings.NEO4J_USERNAME
        self._password = password or settings.NEO4J_PASSWORD
        self._database = database or settings.NEO4J_DATABASE
        self._session = requests.Session()
        self._connected = False

        if not self._api_url:
            raise Neo4jConnectionError(
                "NEO4J_QUERY_API is not set in .env. "
                "Get it from console.neo4j.io -> instance -> Query API URL."
            )

        # Set auth header
        creds = base64.b64encode(
            f"{self._username}:{self._password}".encode()
        ).decode()
        self._session.headers.update({
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def connect(self) -> None:
        """Verify connectivity via a simple query."""
        if self._connected:
            return
        try:
            result = self._run_cypher("RETURN 1 AS ok")
            if result and result[0].get("ok") == 1:
                self._connected = True
                logger.info("Neo4j connected via Query API: %s", self._api_url)
            else:
                raise Neo4jConnectionError("Unexpected response from Neo4j Query API")
        except Neo4jConnectionError:
            raise
        except Exception as exc:
            raise Neo4jConnectionError(f"Neo4j connection failed: {exc}") from exc

    def close(self) -> None:
        self._session.close()
        self._connected = False

    def __enter__(self) -> "Neo4jClient":
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # -------------------------------------------------------------------------
    # Public query methods
    # -------------------------------------------------------------------------

    def execute_read(self, cypher: str, parameters: Optional[dict] = None) -> list[dict]:
        self._ensure_connected()
        return self._run_cypher(cypher, parameters)

    def execute_write(self, cypher: str, parameters: Optional[dict] = None) -> list[dict]:
        self._ensure_connected()
        return self._run_cypher(cypher, parameters)

    def execute_write_many(
        self,
        cypher: str,
        rows: list[dict],
        batch_size: int = 500,
    ) -> dict[str, int]:
        """Batch write using UNWIND $rows AS row ..."""
        self._ensure_connected()
        written = 0
        errors = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i: i + batch_size]
            try:
                self._run_cypher(cypher, {"rows": batch})
                written += len(batch)
            except Exception as exc:
                errors += len(batch)
                logger.error("Batch write error at row %d: %s", i, exc)
        return {"written": written, "batches": (len(rows) + batch_size - 1) // batch_size, "errors": errors}

    def health_check(self) -> bool:
        try:
            self._ensure_connected()
            result = self.execute_read("RETURN 1 AS ok")
            return bool(result and result[0].get("ok") == 1)
        except Exception as exc:
            logger.warning("Neo4j health check failed: %s", exc)
            return False

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        if not self._connected:
            self.connect()

    def _run_cypher(self, cypher: str, parameters: Optional[dict] = None) -> list[dict]:
        """Execute Cypher via the HTTP Query API v2 and return list of dicts."""
        payload = {
            "statement": cypher,
        }
        if parameters:
            payload["parameters"] = parameters

        try:
            resp = self._session.post(self._api_url, json=payload, timeout=30)
        except requests.exceptions.ConnectionError as exc:
            raise Neo4jConnectionError(
                f"Cannot reach Neo4j Query API at {self._api_url}: {exc}"
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise Neo4jConnectionError(f"Neo4j Query API timeout: {exc}") from exc

        if resp.status_code == 401:
            raise Neo4jConnectionError(
                "Neo4j authentication failed (401). Wrong password.\n"
                "Fix: Go to console.neo4j.io -> instance -> reset credentials."
            )
        if resp.status_code == 404:
            raise Neo4jConnectionError(
                f"Neo4j Query API endpoint not found (404): {self._api_url}\n"
                "Check NEO4J_QUERY_API in .env matches what's shown in console.neo4j.io"
            )

        if resp.status_code not in (200, 202):
            raise Neo4jQueryError(
                f"Neo4j Query API returned HTTP {resp.status_code}:\n{resp.text[:500]}"
            )

        # Parse response
        try:
            body = resp.json()
        except json.JSONDecodeError:
            raise Neo4jQueryError(f"Invalid JSON from Neo4j: {resp.text[:300]}")

        # Check for Cypher errors in the response
        if "errors" in body and body["errors"]:
            err = body["errors"][0]
            raise Neo4jQueryError(
                f"Cypher error [{err.get('code', '?')}]: {err.get('message', '?')}"
            )

        # Extract results - the v2 API returns data in different formats
        # Handle the "data" format
        if "data" in body:
            return self._parse_data_format(body)

        # Handle "results" array format
        if "results" in body:
            results = body["results"]
            if not results:
                return []
            return self._parse_results_format(results[0])

        # Single result format with "keys" and "values"
        if "keys" in body and "values" in body:
            return self._parse_keys_values(body["keys"], body["values"])

        # Fallback - return empty
        return []

    def _parse_data_format(self, body: dict) -> list[dict]:
        """Parse the Query API v2 'data' format response."""
        data = body.get("data", {})
        keys = data.get("fields", [])
        values_list = data.get("values", [])

        records = []
        for row in values_list:
            record = {}
            for i, key in enumerate(keys):
                if i < len(row):
                    record[key] = self._unwrap_value(row[i])
            records.append(record)
        return records

    def _parse_results_format(self, result: dict) -> list[dict]:
        """Parse the 'results' array format."""
        columns = result.get("columns", [])
        data_rows = result.get("data", [])
        records = []
        for data_row in data_rows:
            row_values = data_row.get("row", data_row.get("values", []))
            record = {}
            for i, col in enumerate(columns):
                if i < len(row_values):
                    record[col] = self._unwrap_value(row_values[i])
            records.append(record)
        return records

    def _parse_keys_values(self, keys: list, values: list) -> list[dict]:
        """Parse simple keys/values format."""
        records = []
        for row in values:
            if isinstance(row, list):
                record = {keys[i]: self._unwrap_value(row[i]) for i in range(min(len(keys), len(row)))}
            else:
                record = {keys[0]: self._unwrap_value(row)}
            records.append(record)
        return records

    @staticmethod
    def _unwrap_value(val: Any) -> Any:
        """Unwrap Neo4j typed values from the API response."""
        if isinstance(val, dict):
            # Node or relationship with properties
            if "properties" in val:
                props = val["properties"]
                if "labels" in val:
                    props["_labels"] = val["labels"]
                if "elementId" in val:
                    props["_element_id"] = val["elementId"]
                return props
            # Typed value wrapper (e.g. {"$type": "Integer", "$value": 1})
            if "$value" in val:
                return val["$value"]
        return val


# -----------------------------------------------------------------------------
# Process singleton
# -----------------------------------------------------------------------------

_singleton: Optional[Neo4jClient] = None
_singleton_lock = threading.Lock()


def get_neo4j_client() -> Neo4jClient:
    """Return the process-singleton Neo4jClient (connected)."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = Neo4jClient()
                _singleton.connect()
    return _singleton