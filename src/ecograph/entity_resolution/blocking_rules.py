"""
src/ecograph/entity_resolution/blocking_rules.py

Splink blocking rules for entity resolution of supplier records.

Blocking is the first stage of probabilistic record linkage. Instead of
comparing every record pair (O(n^2)), we only generate comparison candidates
that share at least one blocking key. Multiple blocking rules are combined
with OR logic so that any pair matching ANY rule is a candidate.

Rules are ordered from most-restrictive (smallest blocks, highest precision)
to least-restrictive (larger blocks, highest recall).

Reference: Splink documentation - https://moj-analytical-services.github.io/splink/
"""

from __future__ import annotations

from typing import Final

# -------------------------------------------------------------------------
# Individual blocking rule strings (Splink SQL syntax)
# -------------------------------------------------------------------------

# Exact match on normalised legal entity name
BLOCK_ON_EXACT_NAME: Final[str] = "l.name_normalised = r.name_normalised"

# Match on first token of the name (handles "Foxconn" vs "Foxconn Technology")
BLOCK_ON_NAME_TOKEN: Final[str] = (
    "substr(l.name_normalised, 1, instr(l.name_normalised || ' ', ' ') - 1) = "
    "substr(r.name_normalised, 1, instr(r.name_normalised || ' ', ' ') - 1)"
)

# Match on country + first 5 chars of name
BLOCK_ON_COUNTRY_NAME_PREFIX: Final[str] = (
    "l.country_code = r.country_code AND "
    "substr(l.name_normalised, 1, 5) = substr(r.name_normalised, 1, 5)"
)

# Match on postal code
BLOCK_ON_POSTAL_CODE: Final[str] = (
    "l.postal_code IS NOT NULL AND l.postal_code = r.postal_code"
)

# Match on OpenStreetMap place_id
BLOCK_ON_OSM_ID: Final[str] = (
    "l.osm_place_id IS NOT NULL AND l.osm_place_id = r.osm_place_id"
)

# Match on DUNS / LEI / VAT identifier (exact)
BLOCK_ON_LEGAL_ID: Final[str] = (
    "l.legal_id IS NOT NULL AND l.legal_id = r.legal_id"
)

# -------------------------------------------------------------------------
# Canonical list consumed by splink_model.py
# -------------------------------------------------------------------------

DEFAULT_BLOCKING_RULES: Final[list[str]] = [
    BLOCK_ON_LEGAL_ID,
    BLOCK_ON_EXACT_NAME,
    BLOCK_ON_OSM_ID,
    BLOCK_ON_POSTAL_CODE,
    BLOCK_ON_COUNTRY_NAME_PREFIX,
    BLOCK_ON_NAME_TOKEN,
]