"""
src/ecograph/computer_vision/flux_calculator.py

Cross-Sectional Flux (CSF) estimation of CO2 / CH4 emission rates from
TROPOMI plume masks.

The Cross-Sectional Flux method (Varon et al., 2018; Cusworth et al., 2019)
integrates the column enhancement perpendicular to the dominant wind
direction across a transect through the plume.

F = U_eff * SUM_i(dXCO2_i * dx_i * H_col)

Where:
    U_eff : effective wind speed at column centre (m/s)
    dXCO2_i : XCO2 enhancement above background at pixel i (mol/m2)
    dx_i : pixel width in metres
    H_col : total column height (integrated from surface to ~15 km)

This module also provides a simpler capacity-factor heuristic used as a
fallback when the ONNX model is absent or qa_coverage is too low.

Units: all internal calculations are in SI (mol, m, s).
Final output is in tCO2e/year (multiply mol CO2 by molar mass / 1e6 * 3.1536e7).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Physical constants
_CO2_MOLAR_MASS_KG = 44.01e-3  # kg/mol
_CH4_MOLAR_MASS_KG = 16.04e-3  # kg/mol
_AVOGADRO         = 6.022e23
_S_PER_YEAR       = 365.25 * 24 * 3600
_KM_PER_DEGREE    = 111.0  # approximate at equator

# Minimum qa-coverage fraction required for CSF; below this use heuristic
MIN_QA_COVERAGE = 0.30

# Heuristic emission factor: coal power plants
# Baseline: ~820 gCO2/kWh (IPCC AR6) * 8760 h/yr * 1e3 kW/MW * 1e-6 t/g
_COAL_TCO2_PER_MW_YEAR = 820 * 8760 * 1e3 * 1e-6  # ~ 7183 tCO2/MW/yr

# Capacity factor for coal: ~0.60 global average (IEA 2023)
_COAL_CAPACITY_FACTOR = 0.60


@dataclass
class FluxResult:
    """CO2 flux estimate from a TROPOMI plume analysis."""
    flux_tco2_per_year: float  # Primary result
    method: str  # "csf" | "heuristic_capacity_factor"
    wind_speed_ms: Optional[float] = None
    transect_enhancement: Optional[float] = None  # mol/m (integrated)
    uncertainty_fraction: float = 0.40  # CSF has ~40% uncertainty (Varon 2018)
    notes: str = ""


# ------------------------------------------------------------------------
# Cross-Sectional Flux
# ------------------------------------------------------------------------

def calculate_co2_flux(
    prob_map: np.ndarray,
    xco2_band: np.ndarray,
    lat_center: float,
    tile_size_km: float = 64.0,
    wind_speed_ms: float = 5.0,
    background_percentile: int = 10,
) -> FluxResult:
    """
    Cross-Sectional Flux estimation.

    Parameters
    ----------
    prob_map : (H, W) float32
        Plume probability map from PlumeInferenceEngine.
    xco2_band : (H, W) float32
        Normalised XCO2 channel from TropomiTile (band index 0).
        Values have been normalised to [0,1]; we treat them as relative
        column enhancements (unit: arbitrary).
    lat_center : float
        Latitude of tile centre (for pixel-size calculation).
    tile_size_km : float
        Real-world width of the tile in km.
    wind_speed_ms : float
        Effective wind speed. If ERA5 wind data is available it should
        be passed in here; otherwise the default 5 m/s is used (typical
        lower-troposphere daytime speed).
    background_percentile : int
        Percentile of XCO2 values used to define the background.

    Returns
    -------
    FluxResult
    """
    H, W = xco2_band.shape
    pixel_size_m = (tile_size_km * 1e3) / W  # metres per pixel

    # Background XCO2 (lowest percentile of off-plume pixels)
    background = np.nanpercentile(xco2_band, background_percentile)
    enhancement = np.maximum(xco2_band - background, 0.0)  # (H, W)

    # Weight enhancement by plume probability to reduce false positives
    weighted_enhancement = enhancement * prob_map  # (H, W)

    # Dominant wind direction: take mid-row transect (perpendicular to
    # assumed downwind axis = horizontal). In a production system the
    # wind direction from ERA5 should rotate the transect.
    mid_row = H // 2
    transect = weighted_enhancement[mid_row, :]  # (W,)
    transect_integral_mol_m = float(np.nansum(transect) * pixel_size_m)

    # Convert normalised units to mol/m2 (scale factor = typical XCO2
    # enhancement ~1 ppm = ~2.1e-5 mol/m2 at surface; here we use
    # 1.0 normalised unit ~ 0.004 mol/m2 typical for TROPOMI swath)
    scale_to_mol_m2 = 0.004
    transect_mol_m = transect_integral_mol_m * scale_to_mol_m2

    # Flux = wind_speed (m/s) * transect (mol/m) * molar_mass (kg/mol)
    # gives kg/s -> convert to tonnes/year
    flux_kg_s = wind_speed_ms * transect_mol_m * _CO2_MOLAR_MASS_KG
    flux_t_yr = flux_kg_s * _S_PER_YEAR / 1e3

    if flux_t_yr < 0:
        flux_t_yr = 0.0

    return FluxResult(
        flux_tco2_per_year=flux_t_yr,
        method="csf",
        wind_speed_ms=wind_speed_ms,
        transect_enhancement=transect_mol_m,
        uncertainty_fraction=0.40,
        notes=(
            f"CSF from TROPOMI; background_pct={background_percentile}; "
            f"pixel_size={pixel_size_m:.0f}m; lat={lat_center:.2f}"
        ),
    )


# ------------------------------------------------------------------------
# Heuristic fallback
# ------------------------------------------------------------------------

def heuristic_flux_from_capacity(
    installed_capacity_mw: float,
    fuel_type: str = "coal",
    capacity_factor: Optional[float] = None,
) -> FluxResult:
    """
    Estimate annual CO2 emissions from installed generation capacity.

    Used as fallback when TROPOMI data is unavailable or qa_coverage is
    below MIN_QA_COVERAGE.

    Parameters
    ----------
    installed_capacity_mw :
        Nameplate capacity in MW.
    fuel_type :
        One of "coal", "gas", "oil". Default emission factors per MW.
    capacity_factor :
        Override the default capacity factor [0, 1].
    Returns
    -------
    FluxResult
    """
    _EF = {
        "coal": (7183.0, 0.60),  # tCO2/MW/yr at 100%, capacity_factor
        "gas": (3672.0, 0.50),  # combined cycle natural gas (IPCC AR6)
        "oil": (5480.0, 0.40),
    }
    ef_per_mw, default_cf = _EF.get(fuel_type.lower(), _EF["coal"])
    cf = capacity_factor if capacity_factor is not None else default_cf

    flux = installed_capacity_mw * ef_per_mw * cf

    return FluxResult(
        flux_tco2_per_year=flux,
        method="heuristic_capacity_factor",
        uncertainty_fraction=0.30,
        notes=(
            f"Capacity-based estimate; {installed_capacity_mw:.0f} MW {fuel_type}; "
            f"EF={ef_per_mw:.0f} tCO2/MW/yr; CF={cf:.2f}"
        )
    )


# ------------------------------------------------------------------------
# Main entry point used by satellite_intel.py
# ------------------------------------------------------------------------

def estimate_facility_flux(
    prob_map: Optional[np.ndarray],
    xco2_band: Optional[np.ndarray],
    lat_center: float,
    installed_capacity_mw: float = 0.0,
    fuel_type: str = "coal",
    qa_coverage: float = 0.0,
    wind_speed_ms: float = 5.0,
) -> FluxResult:
    """
    Choose between CSF and heuristic depending on data quality.

    If qa_coverage >= MIN_QA_COVERAGE and prob_map/xco2_band are provided,
    uses the Cross-Sectional Flux method. Otherwise falls back to the
    capacity heuristic.
    """
    if (
        prob_map is not None
        and xco2_band is not None
        and qa_coverage >= MIN_QA_COVERAGE
    ):
        try:
            return calculate_co2_flux(
                prob_map=prob_map,
                xco2_band=xco2_band,
                lat_center=lat_center,
                wind_speed_ms=wind_speed_ms,
            )
        except Exception as exc:
            logger.warning("CSF calculation failed (%s); using heuristic.", exc)

    if installed_capacity_mw > 0:
        return heuristic_flux_from_capacity(installed_capacity_mw, fuel_type)

    # No data at all - return zero with explicit note
    return FluxResult(
        flux_tco2_per_year=0.0,
        method="no_data",
        uncertainty_fraction=1.0,
        notes="Neither TROPOMI data nor capacity data available.",
    )