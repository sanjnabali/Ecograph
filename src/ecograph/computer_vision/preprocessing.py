
"""
src/ecograph/computer_vision/preprocessing.py

TROPOMI L2 NetCDF -> normalized numpy array pipeline.

Sentinel-5P TROPOMI Level-2 XCO2 files follow the naming pattern:
S5P_OFFL_L2_CO____<start>_<end>_<orbit>_<version>.nc

This module:
1. Discovers the temporally-nearest available TROPOMI scene for a 
   given (lat, lon, date) query.
2. Extracts a spatial tile of configurable radius (default 64 km).
3. Stacks four bands: [XCO2, SIF, reflectance_670, reflectance_757].
4. Applies quality-flag masking (qa_value >= 0.5 per ESA recommendation).
5. Returns a float32 numpy array shaped (4, tile_px, tile_px) ready 
   for CNN inference, plus associated metadata.

If the requested scene is not available, a synthetic tile of NaNs is 
returned and the caller should fall back to the heuristic estimator.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Default base directory for TROPOMI files; overridden by settings
_DEFAULT_TROPOMI_DIR = Path(__file__).parents[4] / "data" / "raw" / "satellite" / "tropomi_monthly"

# Band configuration
BAND_NAMES = ["XCO2", "SIF", "reflectance_670", "reflectance_757"]
TILE_SIZE_PX = 64
KM_PER_DEGREE = 111.0 # approximate at equator

@dataclass
class TropomiTile:
    """Pre-processed TROPOMI tile ready for model inference."""
    array: np.ndarray          # float32 (4, TILE_SIZE_PX, TILE_SIZE_PX)
    lat_center: float
    lon_center: float
    scene_date: date
    source_file: str
    qa_coverage: float         # fraction of pixels that passed QA filter
    is_synthetic: bool = False # True when no real file was found

# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------

def _find_nearest_file(
    tropomi_dir: Path, target_date: date, max_days_back: int = 45
) -> Optional[Path]:
    """
    Walk `tropomi_dir` and return the NetCDF file whose date is closest
    (but not after) the target_date. Searches up to `max_days_back` days.

    Returns None if no file is found.
    """
    if not tropomi_dir.exists():
        return None
    
    nc_files = sorted(tropomi_dir.glob("*.nc"))
    if not nc_files:
        return None

    # Parse dates from filenames: S5P_..._YYYYMMDDTHHMMSS_...nc
    candidates: list[tuple[date, Path]] = []
    for p in nc_files:
        parts = p.stem.split("_")
        for part in parts:
            if len(part) == 15 and part[8] == 'T' and part[:8].isdigit():
                try:
                    file_date = date(int(part[:4]), int(part[4:6]), int(part[6:8]))
                    if target_date - timedelta(days=max_days_back) <= file_date <= target_date:
                        candidates.append((file_date, p))
                except ValueError:
                    pass
                break

    if not candidates:
        return None

    # Return the file with the most recent date <= target
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]

def _extract_tile(
    nc_path: Path,
    lat: float,
    lon: float,
    tile_size: int = TILE_SIZE_PX,
) -> TropomiTile:
    """
    Open a TROPOMI L2 NetCDF file and extract a spatial tile centred on
    (lat, lon).

    Returns TropomiTile with real data or a synthetic (NaN-filled) tile
    when the file cannot be opened or the location is outside coverage.
    """
    try:
        import netCDF4 as nc # type: ignore[import]
    except ImportError:
        logger.warning("netCDF4 not installed - returning synthetic tile.")
        return _synthetic_tile(lat, lon)
    
    try:
        ds = nc.Dataset(str(nc_path), "r")
    except Exception as exc:
        logger.error("Cannot open TROPOMI file %s: %s", nc_path, exc)
        return _synthetic_tile(lat, lon)
        
    try:
        # ESA L2 product paths (may vary slightly across processor versions)
        grp = ds["PRODUCT"]
        lats = np.array(grp["latitude"][:])
        lons = np.array(grp["longitude"][:])
        xco2 = np.ma.filled(grp["carbonmonoxide_total_column"][:], np.nan).astype(np.float32)
        qa = np.ma.filled(grp["qa_value"][:], 0.0).astype(np.float32)

        # SIF and reflectances may be absent in some processor versions
        def _safe(varname: str) -> np.ndarray:
            try:
                return np.ma.filled(grp[varname][:], np.nan).astype(np.float32)
            except Exception:
                return np.full_like(xco2, np.nan)

        sif = _safe("fluorescence_offset")
        r670 = _safe("reflectance_670")
        r757 = _safe("reflectance_757")

    except Exception as exc:
        logger.error("Variable read error in %s: %s", nc_path, exc)
        ds.close()
        return _synthetic_tile(lat, lon)
    finally:
        ds.close()

    # Flatten 2-D scanline arrays to (N,)
    lats = lats.ravel()
    lons = lons.ravel()
    xco2 = xco2.ravel()
    qa = qa.ravel()
    sif = sif.ravel()
    r670 = r670.ravel()
    r757 = r757.ravel()

    # Spatial window: ±(tile_size/2) pixels in angular degrees
    half_deg = (tile_size / 2) / KM_PER_DEGREE
    mask = (
        (np.abs(lats - lat) <= half_deg) &
        (np.abs(lons - lon) <= half_deg)
    )
    idx = np.where(mask)[0]
    if len(idx) < 4:
        logger.warning("Insufficient coverage at (%s, %s) in %s.", lat, lon, nc_path.name)
        return _synthetic_tile(lat, lon)

    # Build regular grid via nearest-neighbour resampling
    lat_grid = np.linspace(lat - half_deg, lat + half_deg, tile_size)
    lon_grid = np.linspace(lon - half_deg, lon + half_deg, tile_size)
    LON, LAT = np.meshgrid(lon_grid, lat_grid)

    def _grid_band(values: np.ndarray) -> np.ndarray:
        from scipy.interpolate import griddata # type: ignore[import]
        pts = np.column_stack([lons[idx], lats[idx]])
        return griddata(pts, values[idx], (LON, LAT), method="nearest").astype(np.float32)

    # QA mask
    qa_grid = _grid_band(qa)
    qa_ok = qa_grid >= 0.5
    qa_coverage = float(qa_ok.mean())

    stacked = np.stack([
        _grid_band(xco2),
        _grid_band(sif),
        _grid_band(r670),
        _grid_band(r757)
    ], axis=0) # (4, H, W)

    # Mask low-quality pixels with NaN
    stacked[:, ~qa_ok] = np.nan

    # Per-band robust normalisation (clip outliers then scale to [0,1])
    for b in range(stacked.shape[0]):
        band = stacked[b]
        finite = band[np.isfinite(band)]
        if finite.size == 0:
            continue
        p2, p98 = np.percentile(finite, [2, 98])
        if p98 > p2:
            stacked[b] = np.clip((band - p2) / (p98 - p2), 0.0, 1.0)

    # Replace remaining NaN with 0 (will be ignored by dropout in training)
    stacked = np.nan_to_num(stacked, nan=0.0)

    # Parse scene date from filename
    scene_date = _parse_date_from_filename(nc_path.name)

    return TropomiTile(
        array=stacked,
        lat_center=lat,
        lon_center=lon,
        scene_date=scene_date,
        source_file=nc_path.name,
        qa_coverage=qa_coverage
    )

def _synthetic_tile(lat: float, lon: float) -> TropomiTile:
    """Return a zero-filled tile flagged as synthetic."""
    arr = np.zeros((4, TILE_SIZE_PX, TILE_SIZE_PX), dtype=np.float32)
    return TropomiTile(
        array=arr,
        lat_center=lat,
        lon_center=lon,
        scene_date=date.today(),
        source_file="",
        qa_coverage=0.0,
        is_synthetic=True,
    )

def _parse_date_from_filename(name: str) -> date:
    """Extract scene date from SSP filename, fallback to today."""
    for part in name.split("_"):
        if len(part) == 15 and part[8] == 'T' and part[:8].isdigit():
            try:
                return date(int(part[:4]), int(part[4:6]), int(part[6:8]))
            except ValueError:
                pass
    return date.today()


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def load_nearest_tropomi_scene(
    lat: float,
    lon: float,
    query_date: Optional[date] = None,
    tropomi_dir: Optional[Path] = None,
) -> TropomiTile:
    """
    Return the nearest TROPOMI tile for the given location and date.

    This is the primary entry point called by satellite_intel.py.

    Parameters
    ----------
    lat, lon:
        Facility coordinates in decimal degrees.
    query_date:
        Target date. Defaults to today.
    tropomi_dir:
        Directory containing *.nc files. Defaults to
        data/raw/satellite/tropomi_monthly/.

    Returns
    -------
    TropomiTile:
        Normalised (4, 64, 64) float32 array + metadata.
        If is_synthetic=True, no real file was found and the caller
        should fall back to the heuristic flux estimator.
    """
    if query_date is None:
        query_date = date.today()

    base_dir = tropomi_dir or _DEFAULT_TROPOMI_DIR
    nc_path = _find_nearest_file(base_dir, query_date)

    if nc_path is None:
        logger.warning(
            "No TROPOMI scene found for (%s, %s) on %s - using synthetic tile.",
            lat, lon, query_date,
        )
        return _synthetic_tile(lat, lon)

    logger.info("Loading TROPOMI scene: %s", nc_path.name)
    return _extract_tile(nc_path, lat, lon)