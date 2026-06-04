"""
scripts/download_tropomi.py

Download Sentinel-5P TROPOMI L2 XCO2 monthly files from the Copernicus
Data Space Ecosystem (CDSE) S3-compatible API.

Requirements:
    CDSE_USER   - Copernicus username (email)
    CDSE_PASS   - Copernicus password
    Set in .env or as environment variables.

Files are stored in:
    data/raw/satellite/tropomi_monthly/

Usage:
    python scripts/download_tropomi.py \
        --start 2024-01-01 --end 2024-03-31 \
        --bbox "-10,35,40,70"  # lon_min,lat_min,lon_max,lat_max

The script uses the CDSE OData REST API (no Copernicus Hub library required).
See: https://documentation.dataspace.copernicus.eu/APIs/OData.html
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("download_tropomi")

_CDSE_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
_CDSE_ODATA_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1"
_OUT_DIR = Path("data/raw/satellite/tropomi_monthly")

# TROPOMI L2 XCO2 product type
_PRODUCT_TYPE = "L2__CO____"

# ----------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------

def _get_access_token(username: str, password: str) -> str:
    import requests
    resp = requests.post(
        _CDSE_TOKEN_URL,
        data={
            "grant_type": "password",
            "username": username,
            "password": password,
            "client_id": "cdse-public",
        },
        timeout=30,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("No access_token in CDSE response.")
    return token

# ----------------------------------------------------------------------
# Search
# ----------------------------------------------------------------------

def _search_products(
    token: str,
    start_date: date,
    end_date: date,
    bbox: Optional[str] = None,
) -> list[dict]:
    """
    Query CDSE OData for TROPOMI L2 products in the date range.
    
    Returns list of dicts: {id, name, size, downloadUrl}
    """
    import requests
    
    date_filter = (
        f"ContentDate/Start gt {start_date.isoformat()}T00:00:00.000Z and "
        f"ContentDate/Start lt {end_date.isoformat()}T23:59:59.999Z"
    )
    type_filter = f"Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq '{_PRODUCT_TYPE}')"
    filter_str = f"({date_filter}) and ({type_filter})"
    
    if bbox:
        parts = [float(x) for x in bbox.split(",")]
        if len(parts) == 4:
            lon_min, lat_min, lon_max, lat_max = parts
            poly = (
                f"POLYGON(({lon_min} {lat_min},{lon_max} {lat_min},"
                f"{lon_max} {lat_max},{lon_min} {lat_max},{lon_min} {lat_min}))"
            )
            filter_str += f" and OData.CSC.Intersects(area=geography'SRID=4326;{poly}')"
            
    params = {
        "$filter": filter_str,
        "$top": 100,
        "$orderby": "ContentDate/Start desc",
    }
    headers = {"Authorization": f"Bearer {token}"}
    
    resp = requests.get(
        f"{_CDSE_ODATA_URL}/Products",
        params=params,
        headers=headers,
        timeout=60,
    )
    resp.raise_for_status()
    items = resp.json().get("value", [])
    logger.info("Found %d TROPOMI products.", len(items))
    return items

# ----------------------------------------------------------------------
# Download
# ----------------------------------------------------------------------

def _download_product(product: dict, token: str, out_dir: Path) -> Optional[Path]:
    import requests
    
    product_id = product.get("Id") or product.get("id")
    product_name = product.get("Name") or product.get("name") or product_id
    out_path = out_dir / f"{product_name}.NC"
    
    if out_path.exists():
        logger.info("Already downloaded: %s", out_path.name)
        return out_path
        
    url = f"{_CDSE_ODATA_URL}/Products({product_id})/$value"
    headers = {"Authorization": f"Bearer {token}"}
    
    logger.info("Downloading %s ...", product_name)
    try:
        with requests.get(url, headers=headers, stream=True, timeout=600) as resp:
            resp.raise_for_status()
            out_dir.mkdir(parents=True, exist_ok=True)
            with open(out_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    fh.write(chunk)
        logger.info("Saved: %s (%.1f MB)", out_path.name, out_path.stat().st_size / 1e6)
        return out_path
    except Exception as exc:
        logger.error("Download failed for %s: %s", product_name, exc)
        if out_path.exists():
            out_path.unlink()
        return None

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Download TROPOMI L2 XCO2 data from CDSE")
    parser.add_argument("--start", required=True, help='Start date YYYY-MM-DD')
    parser.add_argument("--end", required=True, help='End date YYYY-MM-DD')
    parser.add_argument("--bbox", default=None, help='lon_min,lat_min,lon_max,lat_max')
    parser.add_argument("--out", type=Path, default=_OUT_DIR, help='Output directory')
    args = parser.parse_args()
    
    username = os.environ.get("CDSE_USER") or os.environ.get("COPERNICUS_USER", "")
    password = os.environ.get("CDSE_PASS") or os.environ.get("COPERNICUS_PASS", "")
    
    if not username or not password:
        logger.error(
            "CDSE_USER and CDSE_PASS environment variables must be set. \n"
            "Register free at https://dataspace.copernicus.eu/"
        )
        sys.exit(1)
        
    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)
    
    logger.info("Authenticating with Copernicus CDSE...")
    try:
        token = _get_access_token(username, password)
    except Exception as exc:
        logger.error("Authentication failed: %s", exc)
        sys.exit(1)
        
    products = _search_products(token, start_date, end_date, args.bbox)
    n_ok = 0
    for product in products:
        path = _download_product(product, token, args.out)
        if path:
            n_ok += 1
            
    logger.info("Download complete: %d/%d files saved to %s", n_ok, len(products), args.out)

if __name__ == "__main__":
    main()