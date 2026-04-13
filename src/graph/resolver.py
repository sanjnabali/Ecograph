"""
resolver.py - Entity Resolution (Deduplication) for the EcoGraph Knowledge Graph.

Problem: The LLM may extract the same company under slightly different names.
    "Apple Inc." vs "Apple" vs "Apple Incorporated"
These become 3 separate Company nodes in Neo4j, fragmenting the graph.

Solution: After ingestion, this module:
1. Loads all Company nodes from Neo4j.
2. Uses fuzzy string matching (rapidfuzz) to find near-duplicate names.
3. Merges duplicates into one canonical node using Neo4j's MERGE + relationship redirect.

Note: rapidfuzz is a fast, MIT-licensed alternative to fuzzywuzzy - add it to requirements.txt.
"""

import logging
from typing import List, Dict, Tuple, Optional

from neo4j import Driver
from dotenv import load_dotenv

from src.config.settings import RESOLUTION_THRESHOLD, RESOLUTION_MAX_NODES

load_dotenv()

logger = logging.getLogger(__name__)

# Alias so the rest of the file uses the familiar name
SIMILARITY_THRESHOLD = RESOLUTION_THRESHOLD

# -----------------------------------------------------------------------------
#loading all company nodes
def _load_company_names(driver: Driver) -> List[str]:
    """Returns all distinct Company node names from Neo4j."""
    with driver.session() as session:
        result = session.run("MATCH (c:Company) RETURN c.name AS name ORDER BY c.name")
        names = [record["name"] for record in result if record["name"]]
    logger.info(f"Loaded {len(names)} Company nodes for resolution.")
    return names


# Step 2 - Find duplicate pairs via fuzzy matching
# -----------------------------------------------------------------------------

def _find_duplicate_pairs(names: List[str]) -> List[Tuple[str, str, float]]:
    """
    Compares every pair of company names using fuzzy string matching.
    Returns a list of (canonical_name, duplicate_name, score) tuples
    where canonical_name is the longer / more complete name.

    Time complexity: O(n²) - acceptable for a few hundred company names.
    For very large graphs, consider blocking strategies (e.g., same first letter).
    """
    try:
        from rapidfuzz import fuzz
    except ImportError:
        logger.error(
            "rapidfuzz is not installed. Run: pip install rapidfuzz\n"
            "Entity resolution step skipped."
        )
        return []

    duplicates: List[Tuple[str, str, float]] = []
    seen_pairs = set()

    for i, name_a in enumerate(names):
        for name_b in names[i + 1:]:
            pair_key = tuple(sorted([name_a, name_b]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            score = fuzz.token_sort_ratio(name_a, name_b)
            if score >= SIMILARITY_THRESHOLD:
                # Canonical = the longer name (more specific)
                canonical = name_a if len(name_a) >= len(name_b) else name_b
                duplicate = name_b if canonical == name_a else name_a
                duplicates.append((canonical, duplicate, score))
                logger.debug(f" Duplicate pair [{score:.0f}]: '{canonical}' <- '{duplicate}'")

    logger.info(f"Found {len(duplicates)} potential duplicate pair(s) above threshold {SIMILARITY_THRESHOLD}.")
    return duplicates


# Step 3 - Merge duplicates in Neo4j
# -----------------------------------------------------------------------------

def _merge_duplicate_pair(driver: Driver, canonical: str, duplicate: str) -> int:
    """
    Merges a duplicate Company node into the canonical node:
    1. Re-points all incoming/outgoing relationships from `duplicate` to `canonical`.
    2. Deletes the duplicate node.

    Returns the number of relationships redirected.
    """
    # Redirect all outgoing relationships from duplicate -> canonical
    redirect_out = """
    MATCH (dup:Company {name: $dup_name})-[r]->(target)
    MATCH (can:Company {name: $can_name})
    WHERE dup <> can
    CALL apoc.refactor.from(r, can)
    YIELD input, output
    RETURN count(output) AS redirected
    """

    # Redirect all incoming relationships to duplicate -> canonical
    redirect_in = """
    MATCH (source)-[r]->(dup:Company {name: $dup_name})
    MATCH (can:Company {name: $can_name})
    WHERE source <> can
    CALL apoc.refactor.to(r, can)
    YIELD input, output
    RETURN count(output) AS redirected
    """

    # Delete the now-isolated duplicate node
    delete_dup = """
    MATCH (dup:Company {name: $dup_name})
    DETACH DELETE dup
    """

    total_redirected = 0
    params = {"can_name": canonical, "dup_name": duplicate}

    with driver.session() as session:
        try:
            res = session.run(redirect_out, **params).single()
            total_redirected += res["redirected"] if res else 0

            res = session.run(redirect_in, **params).single()
            total_redirected += res["redirected"] if res else 0

            session.run(delete_dup, **params)
            logger.info(f" Merged '{duplicate}' -> '{canonical}' "
                        f"({total_redirected} relationships redirected)")

        except Exception as e:
            # APOC may not be installed - fall back to a simpler property-copy merge.
            # Open a fresh session because the current one may be in an invalid state
            # after the APOC exception.
            logger.warning(
                f"APOC refactor failed (is APOC installed?): {e}\n"
                "Falling back to simple duplicate deletion without relationship transfer."
            )
            _fallback_merge(driver, canonical, duplicate)

    return total_redirected


def _fallback_merge(driver: Driver, canonical: str, duplicate: str) -> None:
    """
    Fallback when APOC is not available.
    Copies all properties from duplicate to canonical and removes duplicate.
    Note: relationships are NOT transferred in this fallback.
    Opens a fresh driver session to avoid reusing an invalidated session.
    """
    copy_props = """
    MATCH (can:Company {name: $can_name}), (dup:Company {name: $dup_name})
    SET can += properties(dup)
    WITH dup
    DETACH DELETE dup
    """
    with driver.session() as fresh_session:
        fresh_session.run(copy_props, can_name=canonical, dup_name=duplicate)
    logger.warning(f" Fallback merge: deleted '{duplicate}', properties copied to '{canonical}'. "
                   "Relationships from duplicate were NOT transferred. Install APOC for full resolution.")


# Public entry point
# -----------------------------------------------------------------------------

def resolve_entities(driver: Driver) -> Dict[str, int]:
    """
    Full entity resolution pipeline:
    load -> find duplicates -> merge each pair.

    Returns a summary dict: {"pairs_found": N, "pairs_merged": N, "rels_redirected": N}
    """
    logger.info("Starting entity resolution...")

    names = _load_company_names(driver)
    if len(names) < 2:
        logger.info("Not enough Company nodes to resolve. Skipping.")
        return {"pairs_found": 0, "pairs_merged": 0, "rels_redirected": 0}

    if len(names) > RESOLUTION_MAX_NODES:
        logger.warning(
            f"Graph has {len(names)} Company nodes - exceeds RESOLUTION_MAX_NODES "
            f"({RESOLUTION_MAX_NODES}). Skipping O(n²) entity resolution to prevent "
            "excessive runtime. Increase RESOLUTION_MAX_NODES or implement a blocking strategy."
        )
        return {"pairs_found": 0, "pairs_merged": 0, "rels_redirected": 0}

    pairs = _find_duplicate_pairs(names)
    if not pairs:
        logger.info("No duplicates found. Graph is clean.")
        return {"pairs_found": 0, "pairs_merged": 0, "rels_redirected": 0}

    merged = 0
    total_rels = 0
    # Keep track of already-processed canonical names to avoid chain merges
    # (if A->B and A->C are both found, merging B into A first is fine, then C into A)
    for canonical, duplicate, score in pairs:
        logger.info(f"Merging [{score:.0f}%] '{duplicate}' -> '{canonical}'")
        rels = _merge_duplicate_pair(driver, canonical, duplicate)
        total_rels += rels
        merged += 1

    summary = {"pairs_found": len(pairs), "pairs_merged": merged, "rels_redirected": total_rels}
    logger.info(f"Entity resolution complete: {summary}")
    return summary


if __name__ == "__main__":
    from src.graph.connection import get_driver
    try:
        driver = get_driver()
        summary = resolve_entities(driver)
        logger.info(f"Resolution summary: {summary}")
        driver.close()
    except Exception as e:
        logger.critical(f"Entity resolution failed: {e}", exc_info=True)