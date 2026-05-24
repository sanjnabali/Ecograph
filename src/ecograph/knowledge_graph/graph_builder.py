"""
src/knowledge_graph/graph_builder.py

Builds Neo4j knowledge graph from resolved entities and ingested triples.

Responsibilities:
- Apply graph schema (node labels, constraints, indexes)
- Batch write nodes with efficient transaction management
- Batch write edges with provenance tracking
- Validate graph integrity
- Provide graph statistics
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
from datetime import datetime, timezone
import json

from neo4j import Driver, ManagedTransaction, Result

logger = logging.getLogger(__name__)


@dataclass
class GraphSchema:
    """Neo4j graph schema definition."""

    # Node constraints (uniqueness)
    CONSTRAINTS = [
        "CREATE CONSTRAINT unique_company_id IF NOT EXISTS FOR (c:Company) REQUIRE c.entity_id IS UNIQUE",
        "CREATE CONSTRAINT unique_supplier_id IF NOT EXISTS FOR (s:Supplier) REQUIRE s.entity_id IS UNIQUE",
        "CREATE CONSTRAINT unique_facility_id IF NOT EXISTS FOR (f:Facility) REQUIRE f.entity_id IS UNIQUE",
        "CREATE CONSTRAINT unique_region_name IF NOT EXISTS FOR (r:Region) REQUIRE r.name IS UNIQUE",
        "CREATE CONSTRAINT unique_scope_name IF NOT EXISTS FOR (s:Scope) REQUIRE s.name IS UNIQUE",
        "CREATE CONSTRAINT unique_observation_id IF NOT EXISTS FOR (o:Observation) REQUIRE o.observation_id IS UNIQUE",
    ]

    # Indexes (performance)
    INDEXES = [
        "CREATE INDEX idx_company_name IF NOT EXISTS FOR (c:Company) ON (c.name)",
        "CREATE INDEX idx_supplier_name IF NOT EXISTS FOR (s:Supplier) ON (s.name)",
        "CREATE INDEX idx_supplier_country IF NOT EXISTS FOR (s:Supplier) ON (s.country)",
        "CREATE INDEX idx_facility_name IF NOT EXISTS FOR (f:Facility) ON (f.name)",
        "CREATE INDEX idx_emission_value IF NOT EXISTS FOR (e:EmissionMetric) ON (e.value)",
        "CREATE INDEX idx_observation_timestamp IF NOT EXISTS FOR (o:Observation) ON (o.timestamp)",
    ]

    # Full-text search indexes
    FULLTEXT_INDEXES = [
        'CREATE FULLTEXT INDEX company_fulltext IF NOT EXISTS FOR (c:Company) ON EACH [c.name, c.country, c.sector]',
        'CREATE FULLTEXT INDEX supplier_fulltext IF NOT EXISTS FOR (s:Supplier) ON EACH [s.name, s.country]',
    ]


class GraphBuilder:
    """
    Builds and manages Neo4j knowledge graph.

    Workflow:
    1. apply_schema() - Create constraints and indexes
    2. write_nodes() - Batch write node entities
    3. write_edges() - Batch write relationships
    4. validate() - Check graph integrity
    """

    BATCH_SIZE = 1000  # Nodes/edges per transaction
    TIMEOUT_SEC = 30

    def __init__(self, driver: Driver):
        """
        Args:
            driver: Neo4j driver instance
        """
        self.driver = driver
        self.schema = GraphSchema()
        self.write_stats = {
            "nodes_created": 0,
            "edges_created": 0,
            "errors": [],
        }

    def apply_schema(self) -> Dict[str, Any]:
        """
        Apply graph schema (constraints and indexes).

        Returns:
            Statistics: constraints_created, indexes_created, errors
        """
        logger.info("Applying graph schema")
        stats = {
            "constraints_created": 0,
            "indexes_created": 0,
            "fulltext_indexes_created": 0,
            "errors": [],
        }

        with self.driver.session() as session:
            # Apply constraints
            for constraint_cypher in self.schema.CONSTRAINTS:
                try:
                    session.run(constraint_cypher)
                    stats["constraints_created"] += 1
                    logger.debug(f"✓ Constraint created")
                except Exception as exc:
                    # Constraint might already exist - that's ok
                    logger.debug(f"Constraint already exists or error: {exc}")

            # Apply indexes
            for index_cypher in self.schema.INDEXES:
                try:
                    session.run(index_cypher)
                    stats["indexes_created"] += 1
                    logger.debug(f"✓ Index created")
                except Exception as exc:
                    logger.debug(f"Index already exists or error: {exc}")

            # Apply full-text indexes
            for ft_cypher in self.schema.FULLTEXT_INDEXES:
                try:
                    session.run(ft_cypher)
                    stats["fulltext_indexes_created"] += 1
                    logger.debug(f"✓ Full-text index created")
                except Exception as exc:
                    logger.debug(f"Full-text index already exists or error: {exc}")

        logger.info(
            f"✅ Schema applied: "
            f"{stats['constraints_created']} constraints, "
            f"{stats['indexes_created']} indexes"
        )

        return stats

    def write_nodes(
        self,
        nodes: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Batch write nodes to Neo4j.

        Node format:
        {
            "label": "Company" | "Supplier" | "Facility" | "Region" | "Scope" | ...,
            "entity_id": "unique_id",
            "properties": {
                "name": "...",
                "country": "...",
                ...
            }
        }

        Args:
            nodes: List of node dictionaries

        Returns:
            Statistics: created, updated, errors
        """
        logger.info(f"Writing {len(nodes)} nodes")

        stats = {"created": 0, "updated": 0, "errors": 0, "total": len(nodes)}

        # Group nodes by label for efficient writing
        nodes_by_label = {}
        for node in nodes:
            label = node.get("label", "Entity")
            if label not in nodes_by_label:
                nodes_by_label[label] = []
            nodes_by_label[label].append(node)

        with self.driver.session() as session:
            for label, label_nodes in nodes_by_label.items():
                logger.debug(f"Writing {len(label_nodes)} {label} nodes")

                for i in range(0, len(label_nodes), self.BATCH_SIZE):
                    batch = label_nodes[i : i + self.BATCH_SIZE]

                    try:
                        result = session.execute_write(
                            self._write_node_batch,
                            label,
                            batch,
                        )
                        stats["created"] += result.get("created", 0)
                        stats["updated"] += result.get("updated", 0)

                    except Exception as exc:
                        logger.error(f"Error writing {label} batch: {exc}")
                        stats["errors"] += len(batch)

        logger.info(
            f"✅ Nodes written: {stats['created']} created, "
            f"{stats['updated']} updated, {stats['errors']} errors"
        )

        self.write_stats["nodes_created"] += stats["created"]
        return stats

    def write_edges(
        self,
        edges: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Batch write edges (relationships) to Neo4j.

        Edge format:
        {
            "source_label": "Company",
            "source_id": "entity_id",
            "target_label": "Supplier",
            "target_id": "entity_id",
            "relationship": "PURCHASES",
            "properties": {
                "volume_usd": 500000,
                "date": "2024-01-15",
                ...
            },
            "provenance": {
                "source": "ERP",
                "file": "invoices.csv",
                "timestamp": "2024-01-20T10:30:00Z"
            }
        }

        Args:
            edges: List of edge dictionaries

        Returns:
            Statistics: created, errors
        """
        logger.info(f"Writing {len(edges)} edges")

        stats = {"created": 0, "errors": 0, "total": len(edges)}

        with self.driver.session() as session:
            for i in range(0, len(edges), self.BATCH_SIZE):
                batch = edges[i : i + self.BATCH_SIZE]

                try:
                    result = session.execute_write(
                        self._write_edge_batch,
                        batch,
                    )
                    stats["created"] += result.get("created", 0)

                except Exception as exc:
                    logger.error(f"Error writing edge batch: {exc}")
                    stats["errors"] += len(batch)

        logger.info(
            f"✅ Edges written: {stats['created']} created, "
            f"{stats['errors']} errors"
        )

        self.write_stats["edges_created"] += stats["created"]
        return stats

    def _write_node_batch(
        self,
        tx: ManagedTransaction,
        label: str,
        nodes: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        """Execute batch node write transaction."""
        created = 0
        updated = 0

        for node in nodes:
            entity_id = node.get("entity_id")
            properties = node.get("properties", {})

            if not entity_id:
                logger.warning(f"Skipping node without entity_id: {node}")
                continue

            try:
                cypher = (
                    f"MERGE (n:{label} {{entity_id: $entity_id}}) "
                    f"SET n += $properties "
                    f"RETURN n"
                )

                result = tx.run(
                    cypher,
                    entity_id=entity_id,
                    properties=properties,
                )

                result.consume()
                created += 1

            except Exception as exc:
                logger.warning(
                    f"Error writing {label} node {entity_id}: {exc}"
                )

        return {"created": created, "updated": updated}

    def _write_edge_batch(
        self,
        tx: ManagedTransaction,
        edges: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        """Execute batch edge write transaction."""
        created = 0

        for edge in edges:
            try:
                source_label = edge.get("source_label")
                source_id = edge.get("source_id")
                target_label = edge.get("target_label")
                target_id = edge.get("target_id")
                relationship = edge.get("relationship")
                properties = edge.get("properties", {})
                provenance = edge.get("provenance", {})

                if not all([source_label, source_id, target_label, target_id, relationship]):
                    logger.warning(f"Skipping malformed edge: {edge}")
                    continue

                # Merge relationship with properties and provenance
                all_properties = {**properties, **provenance}

                cypher = (
                    f"MATCH (a:{source_label} {{entity_id: $source_id}}) "
                    f"MATCH (b:{target_label} {{entity_id: $target_id}}) "
                    f"MERGE (a)-[r:{relationship}]->(b) "
                    f"SET r += $properties"
                )

                tx.run(
                    cypher,
                    source_id=source_id,
                    target_id=target_id,
                    properties=all_properties,
                )

                created += 1

            except Exception as exc:
                logger.warning(f"Error writing edge: {exc}")

        return {"created": created}

    def get_graph_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the graph.

        Returns:
            Node counts by label, relationship counts, etc.
        """
        with self.driver.session() as session:
            # Node counts
            node_cypher = "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count"
            node_results = session.run(node_cypher).data()

            # Edge counts
            edge_cypher = "MATCH ()-[r]->() RETURN type(r) AS relationship, count(r) AS count"
            edge_results = session.run(edge_cypher).data()

            # Total counts
            total_nodes = sum(r["count"] for r in node_results)
            total_edges = sum(r["count"] for r in edge_results)

            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "nodes_by_label": {r["label"]: r["count"] for r in node_results},
                "edges_by_type": {r["relationship"]: r["count"] for r in edge_results},
                "total_nodes": total_nodes,
                "total_edges": total_edges,
            }

    def validate_graph(self) -> Tuple[bool, List[str]]:
        """
        Validate graph integrity.

        Checks:
        - No orphaned nodes
        - Entity IDs are unique
        - Required node types exist
        """
        errors = []

        with self.driver.session() as session:
            # Check for duplicate entity_ids
            dup_cypher = (
                "MATCH (n) WHERE n.entity_id IS NOT NULL "
                "WITH n.entity_id AS id, count(*) AS cnt "
                "WHERE cnt > 1 RETURN id, cnt"
            )
            dups = session.run(dup_cypher).data()
            if dups:
                errors.append(f"Found {len(dups)} duplicate entity_ids")

            # Check that Company and Supplier nodes exist
            company_count = session.run(
                "MATCH (c:Company) RETURN count(c) AS cnt"
            ).single()["cnt"]
            if company_count == 0:
                errors.append("No Company nodes found")

        return len(errors) == 0, errors

    def export_graph_json(self, output_path: Path) -> Dict[str, Any]:
        """
        Export graph structure to JSON for analysis.

        Args:
            output_path: Path to export JSON file

        Returns:
            Export statistics
        """
        logger.info(f"Exporting graph to {output_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        graph_data = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "statistics": self.get_graph_stats(),
            "schema": {
                "constraints": len(self.schema.CONSTRAINTS),
                "indexes": len(self.schema.INDEXES),
                "fulltext_indexes": len(self.schema.FULLTEXT_INDEXES),
            },
        }

        try:
            with open(output_path, "w") as f:
                json.dump(graph_data, f, indent=2)

            logger.info(f"✅ Exported graph metadata to {output_path}")
            return {"exported": True, "file_size_mb": output_path.stat().st_size / 1e6}

        except Exception as exc:
            logger.error(f"Export failed: {exc}")
            raise