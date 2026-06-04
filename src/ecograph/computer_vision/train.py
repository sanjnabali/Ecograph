"""
src/ecograph/computer_vision/train.py

Training loop for EcoGraphUNet plume detection model.

Workflow:
1. Load synthetic or real TROPOMI tiles from disk.
2. Train EcoGraphUNet with BCELoss + Dice loss for 50 epochs.
3. Save PyTorch checkpoint (.pth).
4. Export to ONNX FP32.
5. Quantise to INT8 using ONNX Runtime dynamic quantisation.

Run with:
python -m ecograph.computer_vision.train \
--data-dir data/raw/satellite/tiles \
--out-dir src/ecograph/computer_vision/model \
--epochs 50 --batch 16 --lr 1e-3

The INT8 ONNX model is the file consumed by PlumeInferenceEngine.
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Optional
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Loss functions
# --------------------------------------------------------------------------

def _dice_loss(pred, target, eps: float = 1e-6):
    """Soft Dice loss for binary segmentation."""
    import torch
    p = pred.view(-1)
    t = target.view(-1)
    intersection = (p * t).sum()
    return 1.0 - (2.0 * intersection + eps) / (p.sum() + t.sum() + eps)

def _combined_loss(pred, target):
    """BCE + Dice (equal weight)."""
    import torch
    import torch.nn.functional as F
    bce = F.binary_cross_entropy(pred, target)
    dice = _dice_loss(pred, target)
    return bce + dice

# --------------------------------------------------------------------------
# Dataset
# --------------------------------------------------------------------------

class TropomiTileDataset:
    """
    Simple numpy-based dataset loader.

    Expects two sub-directories under 'root':
    images/ : *.npy files, each (4, 64, 64) float32
    masks/  : *.npy files, each (1, 64, 64) float32 binary masks
              (same filename as the corresponding image)
    """

    def __init__(self, root: Path):
        self.image_dir = root / "images"
        self.mask_dir = root / "masks"
        self.files = sorted(self.image_dir.glob("*.npy"))
        if not self.files:
            raise FileNotFoundError(f"No .npy tile files found under {self.image_dir}")
        logger.info("Dataset: %d tiles found.", len(self.files))

    def __len__(self) -> int:
        return len(self.files)

    def __getitem__(self, idx: int):
        import torch
        img_path = self.files[idx]
        mask_path = self.mask_dir / img_path.name
        image = np.load(img_path).astype(np.float32)
        mask = np.load(mask_path).astype(np.float32) if mask_path.exists() else np.zeros((1, 64, 64), dtype=np.float32)
        return torch.from_numpy(image), torch.from_numpy(mask)

# --------------------------------------------------------------------------
# Training loop
# --------------------------------------------------------------------------

def train(
    data_dir: Path,
    out_dir: Path,
    epochs: int = 50,
    batch: int = 16,
    lr: float = 1e-3,
    device: str = "cpu",
    register: bool = True,
    auto_promote: bool = True,
    notes: str = "",
    tags: Optional[list[str]] = None,
) -> Path:
    """
    Train EcoGraphUNet, export to INT8 ONNX, and register in ModelRegistry.

    After training completes the model is saved once to the registry so it
    can be loaded in < 1 second on every subsequent run - no retraining needed.

    Parameters
    ----------
    data_dir: Directory with images/ and masks/ sub-directories.
    out_dir: Staging directory for raw artefacts (pth, onnx).
    epochs: Training epochs.
    batch: Batch size.
    lr: Learning rate.
    device: "cpu" or "cuda".
    register: If True, save to ModelRegistry after training.
    auto_promote: If True, automatically mark new version as production.
    notes: Free-text annotation stored in manifest.
    tags: Optional tags (e.g. ["synthetic", "coal"]).

    Returns path to the INT8 ONNX file.
    """
    try:
        import torch
        import torch.utils.data as data
    except ImportError:
        raise ImportError("PyTorch is required for training.") from exc

    from ecograph.computer_vision.model.unet import EcoGraphUNet

    out_dir.mkdir(parents=True, exist_ok=True)

    dataset = TropomiTileDataset(data_dir)
    loader = data.DataLoader(dataset, batch_size=batch, shuffle=True, num_workers=0)
    model = EcoGraphUNet(pretrained_encoder=True).to(device)
    optimiser = torch.optim.Adam(model.parameters(), lr=lr)

    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=epochs)

    model.train()
    final_loss = 0.0
    for epoch in range(1, epochs + 1):
        epoch_loss = 0.0
        for images, masks in loader:
            images = images.to(device)
            masks = masks.to(device)
            optimiser.zero_grad()
            preds = model(images)
            loss = _combined_loss(preds, masks)
            loss.backward()
            optimiser.step()
            epoch_loss += loss.item()
        scheduler.step()
        final_loss = epoch_loss / max(len(loader), 1)
        if epoch % 10 == 0 or epoch == 1:
            logger.info("Epoch %d/%d loss=%.4f", epoch, epochs, final_loss)

    # Save PyTorch checkpoint
    pth_path = out_dir / "ecograph_unet.pth"
    torch.save(model.state_dict(), pth_path)
    logger.info("Checkpoint saved: %s", pth_path)

    # Export to ONNX FP32
    onnx_fp32 = out_dir / "ecograph_unet_fp32.onnx"
    _export_onnx(model, onnx_fp32, device)

    # Quantise to INT8
    onnx_int8 = out_dir / "ecograph_unet_int8.onnx"
    _quantise_onnx(onnx_fp32, onnx_int8)

    # Register in ModelRegistry so future runs skip training
    if register:
        try:
            from ecograph.computer_vision.model_registry import get_registry
            registry = get_registry()
            ver = registry.save(
                pth_path=pth_path,
                onnx_fp32_path=onnx_fp32,
                onnx_int8_path=onnx_int8,
                epochs=epochs,
                final_loss=float(final_loss),
                n_tiles=len(dataset),
                batch_size=batch,
                learning_rate=lr,
                device=device,
                notes=notes,
                tags=tags or [],
                auto_promote=auto_promote,
            )
            logger.info("Model registered as %s (auto_promote=%s).", ver.version, auto_promote)
        except Exception as exc:
            logger.warning("ModelRegistry save failed (non-fatal): %s", exc)

    return onnx_int8

def _export_onnx(model, path: Path, device: str) -> None:
    """Export PyTorch model to ONNX FP32."""
    import torch
    model.eval()
    dummy = torch.zeros(1, 4, 64, 64, device=device)
    torch.onnx.export(
        model,
        dummy,
        str(path),
        input_names=["tile"],
        output_names=["prob_map"],
        dynamic_axes={"tile": {0: "batch"}, "prob_map": {0: "batch"}},
        opset_version=17,
    )
    logger.info("ONNX FP32 exported: %s", path)

def _quantise_onnx(fp32_path: Path, int8_path: Path) -> None:
    """Apply ONNX Runtime dynamic quantisation."""
    try:
        from onnxruntime.quantization import quantize_dynamic, QuantType # type: ignore[import]
        quantize_dynamic(str(fp32_path), str(int8_path), weight_type=QuantType.QUInt8)
        logger.info("INT8 quantised model: %s", int8_path)
    except ImportError:
        logger.warning(
            "onnxruntime.quantization not available - copying FP32 as INT8 placeholder."
        )
        import shutil
        shutil.copy(fp32_path, int8_path)

# --------------------------------------------------------------------------
# CLI entry-point
# --------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Train EcoGraph plume detection CNN")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("src/ecograph/computer_vision/model"))
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--no-register", action="store_true", help="Skip ModelRegistry save")
    parser.add_argument("--no-promote", action="store_true", help="Do not auto-promote to production")
    parser.add_argument("--notes", type=str, default="", help="Annotation stored in manifest")
    parser.add_argument("--tags", nargs="*", default=[], help="Tags e.g. synthetic coal")
    args = parser.parse_args()

    onnx_path = train(
        data_dir=args.data_dir,
        out_dir=args.out_dir,
        epochs=args.epochs,
        batch=args.batch,
        lr=args.lr,
        device=args.device,
        register=not args.no_register,
        auto_promote=not args.no_promote,
        notes=args.notes,
        tags=args.tags,
    )
    print(f"Training complete. INT8 model: {onnx_path}")

if __name__ == "__main__":
    main()