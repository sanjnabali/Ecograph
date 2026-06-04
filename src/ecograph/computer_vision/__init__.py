"""
src/ecograph/computer_vision
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Public API for the computer-vision sub-package.
"""

from ecograph.computer_vision.inference import (
    PlumeInferenceEngine,
    ModelNotFoundError,
    run_plume_inference,
)
from ecograph.computer_vision.model_registry import (
    get_registry,
    get_inference_engine,
    ModelRegistry,
    CachedInferenceEngine,
)
from ecograph.computer_vision.flux_calculator import (
    calculate_co2_flux,
    estimate_facility_flux,
)
from ecograph.computer_vision.preprocessing import load_nearest_tropomi_scene

__all__ = [
    # inference
    "PlumeInferenceEngine",
    "ModelNotFoundError",
    "run_plume_inference",
    # registry
    "get_registry",
    "get_inference_engine",
    "ModelRegistry",
    "CachedInferenceEngine",
    # flux
    "calculate_co2_flux",
    "estimate_facility_flux",
    # preprocessing
    "load_nearest_tropomi_scene",
]