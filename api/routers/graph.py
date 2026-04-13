
"""
api/routers/graph.py - Knowledge Graph exploration endpoints.

GET  /api/graph/nodes                  - paginated node list with optional label filter
GET  /api/graph/node/{name}            - single node with all its relationships
GET  /api/graph/search?q=              - full-text node name search
GET  /api/graph/subgraph/{name}        - ego-graph (node + N-hop neighbours)
GET  /api/graph/map                    - all geocoded nodes for map view
GET  /api/graph/supply-chain           - all HAS_SUPPLIER / SUPPLIES_TO edges
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Path, Query
from neo4j import Driver
from pydantic import BaseModel, Field

from api.deps import get_driver
from src.graph.schema import NodeLabel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/graph", tags=["Knowledge Graph"])

_VALID_LABELS = NodeLabel.ALL | {"Entity"}

class NodeOut(BaseModel):
    id:          str
    label:       str
    name:        str
    properties: Dict[str, Any] = Field(default_factory=dict)

class EdgeOut(BaseModel):
    source:      str
    target:      str
    type:        str
    properties: Dict[str, Any] = Field(default_factory=dict)

class NodeDetail(BaseModel):
    node:          NodeOut
    relationships: List[EdgeOut]

class SubGraph(BaseModel):
    nodes: List[NodeOut]
    edges: List[EdgeOut]

class GeoNode(BaseModel):
    label:     str
    name:      str
    latitude:  float
    longitude: float
    extra:     Dict[str, Any] = Field(default_factory=dict)

def _record_to_node(record: Any, node_key: str = "n") -> Optional[NodeOut]:
    """Safely converts a Neo4j node record into a NodeOut model."""
    try:
        node = record[node_key]
        labels = list(node.labels)
        label  = labels[0] if labels else "Entity"
        props  = dict(node)
        name   = props.get("name") or props.get("value") or str(node.element_id)
        return NodeOut(
            id         = str(node.element_id),
            label      = label,
            name       = name,
            properties = {k: v for k, v in props.items() if v is not None},
        )
    except Exception as exc:
        logger.warning(f"Could not parse node record: {exc}")
        return None

def _record_to_edge(record: Any) -> Optional[EdgeOut]:
    """Safely converts a Neo4j relationship record into an EdgeOut model."""
    try:
        rel    = record["r"]
        source = str(record["start_id"])
        target = str(record["end_id"])
        return EdgeOut(
            source     = source,
            target     = target,
            type       = rel.type,
            properties = {k: v for k, v in dict(rel).items() if v is not None},
        )
    except Exception as exc:
        logger.warning(f"Could not parse edge record: {exc}")
        return None

@router.get(
    "/nodes",
    response_model=List[NodeOut],
    summary="List nodes with optional label filter and pagination",
)
def list_nodes(
    label:  Optional[str] = Query(None, description="Filter by node label, e.g. 'Company'"),
    skip:   int           = Query(0,  ge=0,   description="Pagination offset"),
    limit:  int           = Query(50, ge=1,   le=500, description="Max nodes to return"),
    driver: Driver        = Depends(get_driver),
) -> List[NodeOut]:
    if label and label not in _VALID_LABELS:
        raise ValueError(
            f"Invalid label '{label}'. "
            f"Valid labels: {sorted(_VALID_LABELS)}"
        )

    if label:
        cypher = f"MATCH (n:{label}) RETURN n SKIP $skip LIMIT $limit"
    else:
        cypher = "MATCH (n) RETURN n SKIP $skip LIMIT $limit"

    nodes: List[NodeOut] = []
    with driver.session() as session:
        for record in session.run(cypher, skip=skip, limit=limit):
            node = _record_to_node(record)
            if node:
                nodes.append(node)
    return nodes

@router.get(
    "/search",
    response_model=List[NodeOut],
    summary="Full-text search over node names",
    description=(
        "Searches Company nodes by name using the full-text index. "
        "Falls back to CONTAINS for other labels."
    ),
)
def search_nodes(
    q:      str    = Query(..., min_length=1, max_length=200, description="Search term"),
    label:  str    = Query("Company", description="Node label to search"),
    limit:  int    = Query(20, ge=1, le=100),
    driver: Driver = Depends(get_driver),
) -> List[NodeOut]:
    q = q.strip()
    if not q:
        raise ValueError("Search query cannot be blank.")

    if label not in _VALID_LABELS:
        raise ValueError(f"Invalid label '{label}'. Valid: {sorted(_VALID_LABELS)}")

    # Use full-text index for Company (fastest), fallback CONTAINS for others
    if label == "Company":
        cypher = """
            CALL db.index.fulltext.queryNodes('company_fulltext', $q)
            YIELD node AS n, score
            RETURN n ORDER BY score DESC LIMIT $limit
        """
    else:
        prop   = "value" if label in ("EmissionMetric", "Year") else "name"
        cypher = (
            f"MATCH (n:{label}) WHERE toLower(n.{prop}) CONTAINS toLower($q) "
            f"RETURN n LIMIT $limit"
        )

    nodes: List[NodeOut] = []
    with driver.session() as session:
        try:
            for record in session.run(cypher, q=q, limit=limit):
                node = _record_to_node(record)
                if node:
                    nodes.append(node)
        except Exception as exc:
            # Full-text index may not exist yet - fall back gracefully
            logger.warning(f"Full-text search failed, falling back: {exc}")
            fallback = (
                f"MATCH (n:{label}) WHERE toLower(n.name) CONTAINS toLower($q) "
                f"RETURN n LIMIT $limit"
            )
            for record in session.run(fallback, q=q, limit=limit):
                node = _record_to_node(record)
                if node:
                    nodes.append(node)
    return nodes

@router.get(
    "/node/{name}",
    response_model=NodeDetail,
    summary="Get a single node with all its relationships",
)
def get_node(
    name:   str    = Path(..., min_length=1, max_length=300, description="Node name"),
    label:  str    = Query("Company", description="Label to look up"),
    driver: Driver = Depends(get_driver),
) -> NodeDetail:
    if label not in _VALID_LABELS:
        raise ValueError(f"Invalid label '{label}'.")

    prop   = "value" if label in ("EmissionMetric", "Year") else "name"
    cypher = f"""
        MATCH (n:{label} {{{prop}: $name}})
        OPTIONAL MATCH (n)-[r]-(neighbour)
        RETURN n,
               r,
               elementId(startNode(r)) AS start_id,
               elementId(endNode(r))   AS end_id
    """
    node_out: Optional[NodeOut] = None
    edges:    List[EdgeOut]     = []

    with driver.session() as session:
        records = list(session.run(cypher, name=name))

    if not records:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404,
            detail={
                "error":    "node_not_found",
                "message": f"No {label} node found with name='{name}'.",
            },
        )

    for record in records:
        if node_out is None:
            node_out = _record_to_node(record)
        if record["r"] is not None:
            edge = _record_to_edge(record)
            if edge:
                edges.append(edge)

    # _record_to_node can return None if the record is malformed
    if node_out is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error":    "node_not_found",
                "message": f"No {label} node found with name='{name}' (record parse failed).",
            },
        )

    return NodeDetail(node=node_out, relationships=edges)

@router.get(
    "/subgraph/{name}",
    response_model=SubGraph,
    summary="Ego-graph: node + all neighbours up to N hops",
    description=(
        "Returns a subgraph centred on the given node. "
        "hops=1 returns direct neighbours, hops=2 extends one level further. "
        "Capped at 200 nodes to prevent browser crashes."
    ),
)
def get_subgraph(
    name:   str    = Path(..., min_length=1, max_length=300),
    label:  str    = Query("Company"),
    hops:   int    = Query(1, ge=1, le=3, description="Number of hops (1-3)"),
    limit:  int    = Query(200, ge=1, le=200),
    driver: Driver = Depends(get_driver),
) -> SubGraph:
    if label not in _VALID_LABELS:
        raise ValueError(f"Invalid label '{label}'.")

    prop   = "value" if label in ("EmissionMetric", "Year") else "name"
    cypher = f"""
        MATCH path = (root:{label} {{{prop}: $name}})-[*1..{hops}]-(neighbour)
        WITH nodes(path) AS ns, relationships(path) AS rs
        UNWIND ns AS n
        WITH DISTINCT n, rs
        UNWIND rs AS r
        RETURN DISTINCT
            n,
            r,
            elementId(startNode(r)) AS start_id,
            elementId(endNode(r))   AS end_id
        LIMIT $limit
    """

    nodes_map: Dict[str, NodeOut] = {}
    edges:     List[EdgeOut]      = []

    with driver.session() as session:
        try:
            for record in session.run(cypher, name=name, limit=limit):
                node = _record_to_node(record)
                if node and node.id not in nodes_map:
                    nodes_map[node.id] = node
                edge = _record_to_edge(record)
                if edge:
                    edges.append(edge)
        except Exception as exc:
            logger.error(f"Subgraph query failed for '{name}': {exc}")
            raise

    if not nodes_map:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404,
            detail={"error": "node_not_found", "message": f"No {label} node '{name}'."},
        )

    # Deduplicate edges (bidirectional traversal can produce duplicates)
    seen_edges = set()
    unique_edges: List[EdgeOut] = []
    for e in edges:
        key = (e.source, e.target, e.type)
        if key not in seen_edges:
            seen_edges.add(key)
            unique_edges.append(e)

    return SubGraph(nodes=list(nodes_map.values()), edges=unique_edges)

@router.get(
    "/map",
    response_model=List[GeoNode],
    summary="All geocoded nodes for map visualisation",
)
def get_map_nodes(driver: Driver = Depends(get_driver)) -> List[GeoNode]:
    cypher = """
        MATCH (n)
        WHERE n.latitude IS NOT NULL AND n.longitude IS NOT NULL
        RETURN
            labels(n)[0]             AS label,
            COALESCE(n.name, n.value) AS name,
            n.latitude               AS lat,
            n.longitude              AS lon,
            properties(n)            AS props
        ORDER BY label, name
    """
    geo_nodes: List[GeoNode] = []
    with driver.session() as session:
        for r in session.run(cypher):
            try:
                extra = {
                    k: v for k, v in (r["props"] or {}).items()
                    if k not in ("latitude", "longitude", "name", "value", "_is_new", "_new_node")
                    and v is not None
                }
                geo_nodes.append(GeoNode(
                    label     = r["label"] or "Entity",
                    name      = r["name"] or "Unknown",
                    latitude  = float(r["lat"]),
                    longitude = float(r["lon"]),
                    extra     = extra,
                ))
            except (TypeError, ValueError) as exc:
                logger.warning(f"Skipping malformed geo node: {r.data()} - {exc}")
    return geo_nodes

@router.get(
    "/supply-chain",
    response_model=SubGraph,
    summary="Full supply chain graph (all HAS_SUPPLIER and SUPPLIES_TO edges)",
    description="Returns every supply chain relationship in the graph. Capped at 500 nodes.",
)
def get_supply_chain(
    limit:  int    = Query(500, ge=1, le=500),
    driver: Driver = Depends(get_driver),
) -> SubGraph:
    cypher = """
        MATCH (a:Company)-[r:HAS_SUPPLIER|SUPPLIES_TO]->(b:Company)
        RETURN
            a, b, r,
            elementId(a) AS start_id,
            elementId(b) AS end_id
        LIMIT $limit
    """
    nodes_map: Dict[str, NodeOut] = {}
    edges:     List[EdgeOut]      = []

    with driver.session() as session:
        for record in session.run(cypher, limit=limit):
            for key in ("a", "b"):
                node = _record_to_node(record, key)
                if node and node.id not in nodes_map:
                    nodes_map[node.id] = node
            edge = _record_to_edge(record)
            if edge:
                edges.append(edge)

    return SubGraph(nodes=list(nodes_map.values()), edges=edges)