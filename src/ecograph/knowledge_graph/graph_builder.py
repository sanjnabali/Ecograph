"""
src/knowledge_graph/graph_builder.py - Load triples into Neo4j

Takes resolved entities + triples and writes them as nodes/edges to Neo4j.
Implements batch writing for performance.
"""

import logging
import json
from pathlib import Path
from typing import List
from neo4j import Driver

logger = logging.getLogger(__name__)

class GraphBuilder:
    """Build Neo4j graph from GraphTriple objects."""
    
    BATCH_SIZE = 500  # Write nodes/edges in batches
    
    def __init__(self, driver: Driver):
        self.driver = driver
    
    def write_nodes(self, entities: List[dict]) -> dict:
        """
        Write entity nodes to Neo4j.
        
        Args:
            entities: List of entity dicts with: label, entity_id, name, properties
            
        Returns:
            Stats dict with counts
        """
        logger.info(f"Writing {len(entities)} entity nodes to Neo4j")
        
        stats = {"created": 0, "updated": 0, "errors": 0}
        
        cypher = """
            MERGE (n {label: $label, entity_id: $entity_id})
            SET n += $properties
            RETURN n
        """
        
        with self.driver.session() as session:
            for i in range(0, len(entities), self.BATCH_SIZE):
                batch = entities[i : i + self.BATCH_SIZE]
                for entity in batch:
                    try:
                        # Handle label as a set (Neo4j multiple labels)
                        label = entity.get("label", "Entity")
                        result = session.run(
                            f"MERGE (n:{label} {{entity_id: $entity_id}}) "
                            f"SET n += $properties",
                            entity_id=entity.get("entity_id"),
                            properties={
                                k: v for k, v in entity.items()
                                if k not in ("label", "entity_id") and v is not None
                            }
                        )
                        stats["created"] += 1
                    except Exception as exc:
                        logger.error(f"Error writing node {entity}: {exc}")
                        stats["errors"] += 1
        
        logger.info(f"✅ Wrote {stats['created']} nodes")
        return stats
    
    def write_edges(self, triples: List[dict]) -> dict:
        """Write relationship edges from triples."""
        logger.info(f"Writing {len(triples)} edges to Neo4j")
        
        stats = {"created": 0, "errors": 0}
        
        with self.driver.session() as session:
            for i in range(0, len(triples), self.BATCH_SIZE):
                batch = triples[i : i + self.BATCH_SIZE]
                for triple in batch:
                    try:
                        s = triple["subject"]
                        o = triple["object"]
                        cypher = f"""
                            MATCH (a:{s['label']} {{entity_id: $s_id}})
                            MATCH (b:{o['label']} {{entity_id: $o_id}})
                            MERGE (a)-[r:{triple['relationship']}]->(b)
                            SET r += $props
                        """
                        session.run(
                            cypher,
                            s_id=s["id"],
                            o_id=o["id"],
                            props=triple.get("properties", {})
                        )
                        stats["created"] += 1
                    except Exception as exc:
                        logger.error(f"Error writing edge: {exc}")
                        stats["errors"] += 1
        
        logger.info(f"✅ Wrote {stats['created']} edges")
        return stats
    
    def apply_schema(self) -> dict:
        """Apply constraints and indexes."""
        from src.ecograph.graph.schema import apply_schema
        return apply_schema(self.driver)