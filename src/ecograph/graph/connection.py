"""
src/graph/connection.py - Neo4j driver and connection management

Provides:
  - Singleton driver instance
  - Connection pooling
  - Graceful error handling
  - Session management utilities
"""

import logging
from typing import Optional
from neo4j import GraphDatabase, Driver, Session

logger = logging.getLogger(__name__)

_driver: Optional[Driver] = None

def get_driver() -> Driver:
    """
    Get or create Neo4j driver singleton.
    
    Returns:
        neo4j.Driver instance
        
    Raises:
        ConnectionError: If Neo4j is unavailable
        EnvironmentError: If credentials not configured
    """
    global _driver
    
    if _driver is not None:
        return _driver
    
    # Import settings here to avoid circular imports
    from src import NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
    
    if not all([NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD]):
        raise EnvironmentError(
            "Neo4j credentials not configured. "
            "Set NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD in .env"
        )
    
    try:
        logger.info(f"Connecting to Neo4j: {NEO4J_URI}")
        _driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
            connection_timeout=30,
            max_pool_size=50,
        )
        
        # Test connection
        with _driver.session() as session:
            session.run("RETURN 1")
        
        logger.info("✅ Neo4j connection successful")
        return _driver
        
    except Exception as exc:
        logger.error(f"❌ Neo4j connection failed: {exc}")
        raise ConnectionError(f"Cannot connect to Neo4j at {NEO4J_URI}") from exc

def close_driver() -> None:
    """Close the global driver."""
    global _driver
    if _driver:
        _driver.close()
        _driver = None
        logger.info("Neo4j driver closed")

def get_session() -> Session:
    """
    Get a new Neo4j session.
    
    Usage:
        with get_session() as session:
            result = session.run("MATCH (n) RETURN n LIMIT 5")
    """
    return get_driver().session()

def run_cypher(cypher: str, params: dict = None, single: bool = False):
    """
    Execute a Cypher query and return results.
    
    Args:
        cypher: Cypher query string
        params: Query parameters
        single: If True, return first result only
        
    Returns:
        List of records or single record if single=True
    """
    with get_session() as session:
        result = session.run(cypher, params or {})
        records = result.data()
        return records[0] if single and records else records