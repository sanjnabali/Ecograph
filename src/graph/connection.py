"""
graph/connection.py  - Neo4j driver factory

Single responsibility: create, verify, and return a Neo4j driver.
All other graph modules import get_driver() from here - no one
duplicates the connection logic.
"""

import logging
import os

from dotenv import load_dotenv
from neo4j import GraphDatabase, Driver
from neo4j import exceptions as neo4j_exc

from src.config.settings import NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD


load_dotenv()
logger = logging.getLogger(__name__)


def get_driver() -> Driver:
    """
    Creates and verifies a Neo4j Driver using credentials from settings / .env
    
    Raises
    ------
    EnvironmentError   -  if NEO4J_URI or NEO4J_PASSWORD are not set.
    ConnectionError    -  if the database is unreachable.
    PermissionError    -  if credentials are wrong
    """
    missing = [
        name for name, val in
        [("NEO4J_URI", NEO4J_URI), ("NEO4J_PASSWORD", NEO4J_PASSWORD)]
        if not val
    ]
    if missing:
        raise EnvironmentError(
            f"Missing Neo4j env variable(s): {', '.join(missing)}"
            "add them to your .env file."
        )
    
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
        driver.verify_connectivity()
        logger.info(f"Neo4j connected uri={NEO4J_URI} user={NEO4J_USERNAME}")
        return driver
    
    except neo4j_exc.ServiceUnavailable as exc:
        raise ConnectionError(
            f"Cannot reach Neo4j at '{NEO4J_URI}."
            "Is Neo4j Desktop / AuthDB running? \n"
            f"Original error: {exc}"
        ) from exc
    
    except neo4j_exc.AuthError as exc:
        raise PermissionError(
            "Neo4j authentication failed."
            "check NEO4J_USERNAME and NEO4J_PASSWORD in your .env file."
        ) from exc