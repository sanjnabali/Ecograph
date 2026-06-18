"""
src/ecograph/computer_vision/model_registry.py

Persistent model registry for EcoGraphUNet.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_DEFAULT_REGISTRY_ROOT = Path(__file__).parent / "model" / "registry"
_MANIFEST_FILE = "manifest.json"
_PRODUCTION_KEY = "production"


@dataclass
class ModelVersion:
    version: str
    created_at: str
    epochs: int
    final_loss: float
    n_tiles: int
    batch_size: int
    learning_rate: float
    device: str
    onnx_int8_path: str
    onnx_fp32_path: str
    pth_path: str
    onnx_int8_sha256: str
    notes: str = ""
    tags: list = field(default_factory=list)


@dataclass
class RegistryManifest:
    versions: list = field(default_factory=list)
    production: Optional[str] = None


def _load_manifest(root: Path) -> RegistryManifest:
    path = root / _MANIFEST_FILE
    if not path.exists():
        return RegistryManifest()
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
        versions = [ModelVersion(**v) for v in raw.get("versions", [])]
        return RegistryManifest(versions=versions, production=raw.get("production"))


def _save_manifest(root: Path, manifest: RegistryManifest) -> None:
    root.mkdir(parents=True, exist_ok=True)
    path = root / _MANIFEST_FILE
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "versions": [asdict(v) for v in manifest.versions],
                "production": manifest.production,
            },
            fh,
            indent=2,
        )


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _next_version(manifest: RegistryManifest) -> str:
    return f"v{len(manifest.versions) + 1}"


class ModelNotFoundError(FileNotFoundError):
    """Raised when no suitable model is found in the registry."""


class ModelRegistry:
    """Manages saved model versions and provides fast inference loading."""

    def __init__(self, root: Optional[Path] = None):
        self._root = Path(root) if root else _DEFAULT_REGISTRY_ROOT
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._engine = None

    def save(
        self,
        pth_path: Path,
        onnx_fp32_path: Path,
        onnx_int8_path: Path,
        epochs: int,
        final_loss: float,
        n_tiles: int,
        batch_size: int,
        learning_rate: float,
        device: str = "cpu",
        notes: str = "",
        tags: Optional[list] = None,
        auto_promote: bool = False,
    ) -> ModelVersion:
        with self._lock:
            manifest = _load_manifest(self._root)
            version = _next_version(manifest)
            ver_dir = self._root / version
            ver_dir.mkdir(parents=True, exist_ok=True)

            dst_pth = ver_dir / "ecograph_unet.pth"
            dst_fp32 = ver_dir / "ecograph_unet_fp32.onnx"
            dst_int8 = ver_dir / "ecograph_unet_int8.onnx"

            shutil.copy2(pth_path, dst_pth)
            shutil.copy2(onnx_fp32_path, dst_fp32)
            shutil.copy2(onnx_int8_path, dst_int8)

            int8_hash = _sha256(dst_int8)

            ver = ModelVersion(
                version=version,
                created_at=datetime.now(timezone.utc).isoformat(),
                epochs=epochs,
                final_loss=final_loss,
                n_tiles=n_tiles,
                batch_size=batch_size,
                learning_rate=learning_rate,
                device=device,
                onnx_int8_path=str(dst_int8),
                onnx_fp32_path=str(dst_fp32),
                pth_path=str(dst_pth),
                onnx_int8_sha256=int8_hash,
                notes=notes,
                tags=tags or [],
            )

            manifest.versions.append(ver)

            if auto_promote or manifest.production is None:
                manifest.production = version
                logger.info("Auto-promoted %s to production.", version)

            _save_manifest(self._root, manifest)

            with open(ver_dir / "meta.json", "w", encoding="utf-8") as fh:
                json.dump(asdict(ver), fh, indent=2)

            logger.info("Saved model %s loss=%.4f epochs=%d tiles=%d", version, final_loss, epochs, n_tiles)

            self._engine = None
            return ver

    def promote(self, version: str) -> None:
        with self._lock:
            manifest = _load_manifest(self._root)
            versions = {v.version for v in manifest.versions}
            if version not in versions:
                raise ValueError(f"Version '{version}' not found in registry.")
            manifest.production = version
            _save_manifest(self._root, manifest)
            self._engine = None
            logger.info("Promoted %s to production.", version)

    def list_versions(self) -> list:
        manifest = _load_manifest(self._root)
        return list(reversed(manifest.versions))

    def get_version(self, version: str) -> Optional[ModelVersion]:
        manifest = _load_manifest(self._root)
        for v in manifest.versions:
            if v.version == version:
                return v
        return None

    def production_version(self) -> Optional[ModelVersion]:
        manifest = _load_manifest(self._root)
        if not manifest.production:
            return None
        return self.get_version(manifest.production)

    def best_version(self, metric: str = "final_loss") -> Optional[ModelVersion]:
        manifest = _load_manifest(self._root)
        if not manifest.versions:
            return None
        return min(manifest.versions, key=lambda v: getattr(v, metric, float("inf")))

    def print_summary(self) -> None:
        versions = self.list_versions()
        prod = _load_manifest(self._root).production
        if not versions:
            print("Registry is empty.")
            return
        header = f"{'Ver':<6} {'Loss':>8} {'Epochs':>7} {'Tiles':>7} {'Created':<26} {'Tags'}"
        print(header)
        print("-" * len(header))
        for v in versions:
            marker = " *PROD*" if v.version == prod else ""
            tags = ",".join(v.tags) if v.tags else "-"
            print(
                f"{v.version:<6} {v.final_loss:>8.4f} {v.epochs:>7} "
                f"{v.n_tiles:>7} {v.created_at[:19]:<26} {tags}{marker}"
            )

    def get_engine(
        self,
        version: Optional[str] = None,
        confidence_threshold: float = 0.5,
    ) -> "CachedInferenceEngine":
        with self._lock:
            if self._engine is not None:
                return self._engine

            ver = (
                self.get_version(version) if version
                else self.production_version()
            )

            if ver is None:
                raise ModelNotFoundError(
                    "No model registered. Run training first:\n"
                    "  python -m ecograph.computer_vision.train --data-dir <dir>"
                )

            onnx_path = Path(ver.onnx_int8_path)
            if not onnx_path.exists():
                raise ModelNotFoundError(
                    f"ONNX file missing: {onnx_path}\n"
                    "Registry entry may be stale. Re-train or re-register."
                )

            actual_hash = _sha256(onnx_path)
            if ver.onnx_int8_sha256 and actual_hash != ver.onnx_int8_sha256:
                logger.warning(
                    "ONNX file hash mismatch for %s! File may be corrupted. Proceeding anyway.",
                    ver.version,
                )

            self._engine = CachedInferenceEngine(
                onnx_path=onnx_path,
                version=ver.version,
                confidence_threshold=confidence_threshold,
            )
            logger.info("Inference engine loaded from registry %s (loss=%.4f)", ver.version, ver.final_loss)
            return self._engine


class CachedInferenceEngine:
    """Ultra-fast ONNX Runtime inference engine backed by the model registry."""

    def __init__(
        self,
        onnx_path: Path,
        version: str = "unknown",
        confidence_threshold: float = 0.5,
    ):
        self.path = onnx_path
        self.version = version
        self.threshold = confidence_threshold
        self.session = None
        self.input_name = ""
        self.load_time_ms: float = 0.0
        self.call_count: int = 0
        self.total_inference_ms: float = 0.0

        self._init_session()

    def _init_session(self) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise ImportError(
                "onnxruntime is required. Install: pip install onnxruntime"
            ) from exc

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = max(1, (os.cpu_count() or 4) - 2)
        opts.intra_op_num_threads = max(1, (os.cpu_count() or 4) - 2)
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.enable_mem_pattern = True
        opts.enable_cpu_mem_arena = True
        opts.add_session_config_entry("session.mmap_enable", "1")

        t0 = time.perf_counter()
        self.session = ort.InferenceSession(
            str(self.path),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self.load_time_ms = (time.perf_counter() - t0) * 1000
        self.input_name = self.session.get_inputs()[0].name

        logger.info(
            "CachedInferenceEngine initialized from %s in %.1f ms",
            self.path.name,
            self.load_time_ms,
        )

    def infer(self, tile: np.ndarray) -> dict:
        """Run inference on a single (4, H, W) float32 tile."""
        return self.infer_batch(tile[np.newaxis])[0]

    def infer_batch(self, tiles: np.ndarray) -> list:
        """Run inference on a batch (B, 4, H, W). Returns list[dict]."""
        assert tiles.ndim == 4 and tiles.shape[1] == 4, (
            f"Expected (B, 4, H, W), got {tiles.shape}"
        )

        t0 = time.perf_counter()
        feed = {self.input_name: tiles.astype(np.float32)}
        outputs = self.session.run(None, feed)
        elapsed = (time.perf_counter() - t0) * 1000

        self.call_count += 1
        self.total_inference_ms += elapsed

        prob_batch = outputs[0]  # (B, 1, H, W)
        results = []
        for i in range(prob_batch.shape[0]):
            prob = prob_batch[i, 0]
            mask = prob >= self.threshold
            plume_px = prob[mask]
            results.append({
                "mask": mask,
                "prob_map": prob,
                "plume_fraction": float(mask.mean()),
                "confidence": float(plume_px.mean()) if plume_px.size > 0 else 0.0,
                "inference_ms": elapsed / prob_batch.shape[0],
            })
        return results

    def stats(self) -> dict:
        avg_ms = (
            self.total_inference_ms / self.call_count
            if self.call_count > 0 else 0.0
        )
        return {
            "version": self.version,
            "model_path": str(self.path),
            "load_time_ms": round(self.load_time_ms, 1),
            "call_count": self.call_count,
            "avg_inference_ms": round(avg_ms, 2),
            "total_inference_ms": round(self.total_inference_ms, 1),
        }

    def __repr__(self) -> str:
        return (
            f"CachedInferenceEngine(version={self.version}, "
            f"load={self.load_time_ms:.0f}ms, calls={self.call_count})"
        )


# Process-level singleton
_registry_instance: Optional[ModelRegistry] = None
_registry_lock = threading.Lock()


def get_registry(root: Optional[Path] = None) -> ModelRegistry:
    """Return the process-level ModelRegistry singleton."""
    global _registry_instance
    if _registry_instance is not None:
        return _registry_instance
    with _registry_lock:
        if _registry_instance is None:
            _registry_instance = ModelRegistry(root)
        return _registry_instance


def get_inference_engine(
    version: Optional[str] = None,
    confidence_threshold: float = 0.5,
) -> CachedInferenceEngine:
    """Convenience one-liner: get the ready-to-use inference engine."""
    return get_registry().get_engine(version, confidence_threshold)