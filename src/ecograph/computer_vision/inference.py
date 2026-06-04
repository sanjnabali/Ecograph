"""
src/ecograph/computer_vision/inference.py

ONNX Runtime inference engine for plume detection.

Preferred usage (registry-backed, loads once, < 1 ms per subsequent call):

from ecograph.computer_vision.model_registry import get_inference_engine
engine = get_inference_engine()  # first call: ~300 ms
result = engine.infer(tile)      # every call after: ~20 ms

Legacy usage (explicit ONNX path):

engine = PlumeInferenceEngine("/path/to/model.onnx")
result = engine.infer(tile)

The registry-backed engine is strongly preferred in production because it:
1. Loads the production-pinned model version automatically.
2. Reuses the ONNX session across all calls in the same process.
3. Memory-maps the model so the OS page cache keeps it in RAM.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_DEFAULT_MODEL_PATH = (
    Path(__file__).parent / "model" / "ecograph_unet_int8.onnx"
)

class ModelNotFoundError(FileNotFoundError):
    """Raised when the ONNX model file does not exist on disk."""

class PlumeInferenceEngine:
    """
    Wraps an ONNX Runtime InferenceSession for plume binary segmentation.

    Parameters
    ----------
    model_path:
        Path to the INT8-quantized ONNX file. Defaults to
        src/ecograph/computer_vision/model/ecograph_unet_int8.onnx.
    confidence_threshold:
        Pixel-level probability threshold above which a pixel is
        classified as 'plume'. Default 0.5.
    """

    def __init__(
        self,
        model_path: Optional[Path] = None,
        confidence_threshold: float = 0.5,
    ):
        self.model_path = Path(model_path) if model_path else _DEFAULT_MODEL_PATH
        self.threshold = confidence_threshold
        self._session = None
        self._input_name: str = ""

    # Context manager
    # --------------------------------------------------------------------------

    def __enter__(self) -> PlumeInferenceEngine:
        self._load()
        return self

    def __exit__(self, *_) -> None:
        self._session = None

    # Lazy loading
    # --------------------------------------------------------------------------

    def _load(self) -> None:
        if self._session is not None:
            return

        effective_path = self.model_path

        # If the configured path doesn't exist, try the ModelRegistry
        if not effective_path.exists():
            try:
                from ecograph.computer_vision.model_registry import get_registry  # noqa: PLC0415
                reg = get_registry()
                ver = reg.production_version()
                if ver:
                    effective_path = Path(ver.onnx_int8_path)
                    logger.info(
                        "PlumeInferenceEngine: falling back to registry version %s",
                        ver.version,
                    )
            except Exception:  # registry not available / no version registered yet
                pass

        if not effective_path.exists():
            raise ModelNotFoundError(
                f"ONNX model not found at {self.model_path} and no "
                "production version is registered. "
                "Run 'python -m ecograph.computer_vision.train' to generate one."
            )

        self.model_path = effective_path  # use the resolved path for the session

        try:
            import onnxruntime as ort  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "onnxruntime is required for inference. "
                "Install it with: pip install onnxruntime"
            ) from exc

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 2
        opts.intra_op_num_threads = 4
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self._session = ort.InferenceSession(
            str(self.model_path),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self._input_name = self._session.get_inputs()[0].name
        logger.info("ONNX model loaded from %s.", self.model_path)

    # Inference
    # --------------------------------------------------------------------------

    def infer(self, tile: np.ndarray) -> dict:
        """
        Run inference on a single (4, H, W) float32 tile.

        Returns
        -------
        dict with:
            mask        : (H, W) bool - binary plume mask
            prob_map    : (H, W) float32 - per-pixel probability
            plume_fraction: float - fraction of pixels classified as plume
            confidence  : float - mean probability over predicted plume pixels
        """
        self._load()
        return self.infer_batch(np.expand_dims(tile, 0))[0]

    def infer_batch(self, tiles: np.ndarray) -> list[dict]:
        """
        Returns a list of dicts (one per tile) with the same keys as `infer`.
        """
        self._load()
        assert tiles.ndim == 4 and tiles.shape[1] == 4, (
            f"Expected (B, 4, H, W), got {tiles.shape}"
        )

        feed = {self._input_name: tiles.astype(np.float32)}
        outputs = self._session.run(None, feed)
        prob_batch = outputs[0]  # (B, 1, H, W)

        results = []
        for i in range(prob_batch.shape[0]):
            prob = prob_batch[i, 0]  # (H, W)
            mask = prob >= self.threshold  # (H, W) bool
            plume_px = prob[mask]
            results.append({
                "mask": mask,
                "prob_map": prob,
                "plume_fraction": float(mask.mean()),
                "confidence": float(plume_px.mean()) if plume_px.size > 0 else 0.0,
            })
        return results

# Convenience function (used by satellite_intel.py)
# --------------------------------------------------------------------------

def run_plume_inference(
    tile: np.ndarray,
    model_path: Optional[Path] = None,
    confidence_threshold: float = 0.5,
) -> dict:
    """
    One-shot helper: run inference on a single tile.

    Resolution order:
    1. If `model_path` is given explicitly, use PlumeInferenceEngine directly.
    2. Otherwise, try the ModelRegistry production version (fast, cached).
    3. Fallback to the default ONNX file path on disk.

    Raises ModelNotFoundError if no model is available anywhere.
    """
    if model_path is not None:
        engine = PlumeInferenceEngine(model_path, confidence_threshold)
        return engine.infer(tile)

    # Try registry (preferred - returns cached singleton)
    try:
        from ecograph.computer_vision.model_registry import get_inference_engine
        return get_inference_engine(confidence_threshold=confidence_threshold).infer(tile)
    except Exception:
        pass

    # Final fallback: bare ONNX file
    engine = PlumeInferenceEngine(_DEFAULT_MODEL_PATH, confidence_threshold)
    return engine.infer(tile)