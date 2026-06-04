"""
src/ecograph/evaluation/plume_detection_iou.py

CNN plume detection benchmark: Intersection-over-Union (IoU) @ threshold.

Target from README: IoU > 80% on the TROPOMI test set.

Test set expected at:
data/evaluation/plume_tiles/images/ - *.npy (4, 64, 64) float32
data/evaluation/plume_tiles/masks/ - *.npy (1, 64, 64) float32 binary

The benchmark loads the ONNX INT8 model via PlumeInferenceEngine,
runs inference on all test tiles, and reports mean IoU.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_DEFAULT_TEST_DIR = Path(__file__).parents[4] / "data" / "evaluation" / "plume_tiles"
_DEFAULT_MODEL = Path(__file__).parents[2] / "computer_vision" / "model" / "ecograph_unet_int8.onnx"

@dataclass
class PlumeDetectionMetrics:
    mean_iou: float
    mean_dice: float
    n_tiles: int
    target_met: bool

def _iou(pred_mask: np.ndarray, true_mask: np.ndarray, eps: float = 1e-6) -> float:
    pred = pred_mask.astype(bool)
    truth = true_mask.astype(bool)
    inter = float((pred & truth).sum())
    union = float((pred | truth).sum())
    return (inter + eps) / (union + eps)

def _dice(pred_mask: np.ndarray, true_mask: np.ndarray, eps: float = 1e-6) -> float:
    pred = pred_mask.astype(bool)
    truth = true_mask.astype(bool)
    inter = float((pred & truth).sum())
    return (2 * inter + eps) / (pred.sum() + truth.sum() + eps)

def run_plume_benchmark(
    test_dir: Optional[Path] = None,
    model_path: Optional[Path] = None,
    threshold: float = 0.5,
) -> PlumeDetectionMetrics:
    """
    Evaluate the CNN plume detector on the test tile set.

    Parameters
    ----------
    test_dir:
        Root directory containing images/ and masks/ sub-directories.
    model_path:
        Path to INT8 ONNX model. Defaults to the production model.
    threshold:
        Probability threshold for binary mask generation.

    Returns
    -------
    PlumeDetectionMetrics
    """
    from ecograph.computer_vision.inference import PlumeInferenceEngine, ModelNotFoundError

    root = test_dir or _DEFAULT_TEST_DIR
    images_dir = root / "images"
    masks_dir = root / "masks"

    if not images_dir.exists():
        logger.warning("Test image directory not found: %s", images_dir)
        return PlumeDetectionMetrics(0.0, 0.0, 0, False)

    image_files = sorted(images_dir.glob("*.npy"))
    if not image_files:
        logger.warning("No .npy test tiles found in %s", images_dir)
        return PlumeDetectionMetrics(0.0, 0.0, 0, False)

    iou_scores: list[float] = []
    dice_scores: list[float] = []

    try:
        engine = PlumeInferenceEngine(model_path, confidence_threshold=threshold)
        engine.load()
    except ModelNotFoundError as exc:
        logger.error("Cannot run plume benchmark: %s", exc)
        return PlumeDetectionMetrics(0.0, 0.0, 0, False)
    except Exception as exc:
        logger.error("Failed to load inference engine: %s", exc)
        return PlumeDetectionMetrics(0.0, 0.0, 0, False)

    for img_path in image_files:
        try:
            image = np.load(img_path).astype(np.float32)  # (4, 64, 64)
            mask_path = masks_dir / img_path.name
            if not mask_path.exists():
                continue
            true_mask = np.load(mask_path).astype(np.float32)[0]  # (64, 64)

            result = engine.infer(image)
            pred_mask = result["mask"]  # (64, 64) bool

            iou_scores.append(_iou(pred_mask, true_mask))
            dice_scores.append(_dice(pred_mask, true_mask))

        except Exception as exc:
            logger.warning("Tile %s failed: %s", img_path.name, exc)

    if not iou_scores:
        return PlumeDetectionMetrics(0.0, 0.0, 0, False)

    mean_iou = sum(iou_scores) / len(iou_scores)
    mean_dice = sum(dice_scores) / len(dice_scores)
    met = mean_iou >= 0.80

    if met:
        logger.info("Plume benchmark PASSED: mean_IoU=%.3f", mean_iou)
    else:
        logger.warning("Plume benchmark FAILED: mean_IoU=%.3f (target 0.80)", mean_iou)

    return PlumeDetectionMetrics(
        mean_iou=mean_iou,
        mean_dice=mean_dice,
        n_tiles=len(iou_scores),
        target_met=met,
    )