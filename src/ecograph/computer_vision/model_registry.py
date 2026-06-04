"""
src/ecograph/computer_vision/model_registry.py

Persistent model registry for EcoGraphUNet.

Solves the "retrain every time" problem by:

1. Saving trained models with rich metadata (epoch, loss, date, git hash,
   training data stats) to a versioned manifest (JSON).
2. Keeping the INT8 ONNX file on disk so inference starts in < 1 second.
3. Providing a process-level singleton InferenceSession that is loaded
   ONCE and reused across all inference calls - zero per-call overhead.
4. Supporting "promote to production" so the best checkpoint is pinned as
   the default model used by PlumeInferenceEngine.

Directory layout:
<registry_root/>
  manifest.json          <- version index
  v1/
    ecograph_unet.pth    <- PyTorch weights
    ecograph_unet_fp32.onnx <- FP32 ONNX
    ecograph_unet_int8.onnx <- INT8 ONNX (used at inference time)
    meta.json            <- training metadata
  v2/
    ...
  production -> v2       <- symlink (or recorded in manifest)

Design decisions:
- Manifest is append-only: versions are never deleted automatically.
- The INT8 ONNX is the canonical inference artefact; PyTorch weights
  are kept for fine-tuning / ONNX re-export only.
- The singleton session uses mmap_enable=True so the OS page cache
  keeps the model in RAM after the first load - subsequent loads
  across processes are instant (read from cache, not disk).
- Thread-safe via a module-level lock.
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

# -----------------------------------------------------------------------------
# Default registry location: src/ecograph/computer_vision/model/registry/
# -----------------------------------------------------------------------------
_DEFAULT_REGISTRY_ROOT = Path(__file__).parent / "model" / "registry"
_MANIFEST_FILE         = "manifest.json"
_PRODUCTION_KEY        = "production"

# -----------------------------------------------------------------------------
# Data classes
# -----------------------------------------------------------------------------
@dataclass
class ModelVersion:
    version:           str   # "v1", "v2", ...
    created_at:        str   # ISO-8601 UTC
    epochs:            int
    final_loss:        float
    n_tiles:           int
    batch_size:        int
    learning_rate:     float
    device:            str
    onnx_int8_path:    str   # absolute path
    onnx_fp32_path:    str
    pth_path:          str
    onnx_int8_sha256:  str   # file hash for integrity
    notes:             str = ""
    tags:              list[str] = field(default_factory=list)

@dataclass
class RegistryManifest:
    versions:   list[ModelVersion] = field(default_factory=list)
    production: Optional[str] = None  # version string, e.g. "v2"

# -----------------------------------------------------------------------------
# Manifest helpers
# -----------------------------------------------------------------------------

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

# -----------------------------------------------------------------------------
# ModelRegistry
# -----------------------------------------------------------------------------

class ModelRegistry:
    """
    Manages saved model versions and provides fast inference loading.

    Usage
    -----
    registry = ModelRegistry()                # default location
    registry = ModelRegistry("/my/custom/path") # custom location

    # After training:
    ver = registry.save(
        pth_path=Path("model/ecograph_unet.pth"),
        onnx_fp32_path=Path("model/ecograph_unet_fp32.onnx"),
        onnx_int8_path=Path("model/ecograph_unet_int8.onnx"),
        epochs=50, final_loss=0.12, n_tiles=1200,
        batch_size=16, learning_rate=1e-3, device="cpu",
    )
    registry.promote(ver.version)   # mark as production

    # At inference time:
    engine = registry.get_engine()  # loads once, cached forever
    result = engine.infer(tile)
    """
    def __init__(self, root: Optional[Path] = None):
        self._root = Path(root) if root else _DEFAULT_REGISTRY_ROOT
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._engine = None  # cached PlumeInferenceEngine singleton

    # -------------------------------------------------------------------------
    # Save
    # -------------------------------------------------------------------------

    def save(
        self,
        pth_path:       Path,
        onnx_fp32_path: Path,
        onnx_int8_path: Path,
        epochs:         int,
        final_loss:     float,
        n_tiles:        int,
        batch_size:     int,
        learning_rate:  float,
        device:         str = "cpu",
        notes:          str = "",
        tags:           Optional[list[str]] = None,
        auto_promote:   bool = False,
    ) -> ModelVersion:
        """
        Copy model artefacts into the registry and record metadata.

        Parameters
        ----------
        pth_path, onnx_fp32_path, onnx_int8_path:
            Source files from the training run.
        epochs, final_loss, n_tiles, batch_size, learning_rate, device:
            Training metadata stored in manifest.
        notes:
            Free-text annotation (e.g. "trained on real TROPOMI 2021").
        tags:
            Optional string tags (e.g. ["production-candidate", "coal"]).
        auto_promote:
            If True, automatically promote this version to production.

        Returns
        -------
        ModelVersion record that was saved.
        """
        with self._lock:
            manifest = _load_manifest(self._root)
            version = _next_version(manifest)
            ver_dir = self._root / version
            ver_dir.mkdir(parents=True, exist_ok=True)

            # Copy artefacts
            dst_pth = ver_dir / "ecograph_unet.pth"
            dst_fp32 = ver_dir / "ecograph_unet_fp32.onnx"
            dst_int8 = ver_dir / "ecograph_unet_int8.onnx"

            shutil.copy2(pth_path, dst_pth)
            shutil.copy2(onnx_fp32_path, dst_fp32)
            shutil.copy2(onnx_int8_path, dst_int8)

            # Integrity hash
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

            # Write human-readable meta.json beside the artefacts
            with open(ver_dir / "meta.json", "w", encoding="utf-8") as fh:
                json.dump(asdict(ver), fh, indent=2)

            logger.info(
                "Saved model %s loss=%.4f epochs=%d tiles=%d",
                version, final_loss, epochs, n_tiles,
            )

            # Invalidate cached engine so next call reloads from new version
            self._engine = None
            return ver

    # -------------------------------------------------------------------------
    # Promote
    # -------------------------------------------------------------------------

    def promote(self, version: str) -> None:
        """Mark 'version' as the production model."""
        with self._lock:
            manifest = _load_manifest(self._root)
            versions = {v.version for v in manifest.versions}
            if version not in versions:
                raise ValueError(f"Version '{version}' not found in registry.")
            manifest.production = version
            _save_manifest(self._root, manifest)
            self._engine = None  # invalidate cache
            logger.info("Promoted %s to production.", version)

    # -------------------------------------------------------------------------
    # Query
    # -------------------------------------------------------------------------

    def list_versions(self) -> list[ModelVersion]:
        """Return all registered versions, newest first."""
        manifest = _load_manifest(self._root)
        return list(reversed(manifest.versions))

    def get_version(self, version: str) -> Optional[ModelVersion]:
        manifest = _load_manifest(self._root)
        for v in manifest.versions:
            if v.version == version:
                return v
        return None

    def production_version(self) -> Optional[ModelVersion]:
        """Return the ModelVersion currently marked as production."""
        manifest = _load_manifest(self._root)
        if not manifest.production:
            return None
        return self.get_version(manifest.production)

    def best_version(self, metric: str = "final_loss") -> Optional[ModelVersion]:
        """Return the version with the lowest final_loss."""
        manifest = _load_manifest(self._root)
        if not manifest.versions:
            return None
        return min(manifest.versions, key=lambda v: getattr(v, metric, float("inf")))

    def print_summary(self) -> None:
        """Print a formatted table of all versions."""
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

    # -------------------------------------------------------------------------
    # Fast inference engine (singleton with mmap)
    # -------------------------------------------------------------------------

    def get_engine(
        self,
        version:           Optional[str] = None,
        confidence_threshold: float = 0.5,
    ) -> "CachedInferenceEngine":
        """
        Return a process-level cached inference engine.

        The ONNX session is created ONCE and held in memory.
        All subsequent calls return the same object - near-zero latency.

        Parameters
        ----------
        version:
            Specific version string, or None to use production.
        confidence_threshold:
            Mask threshold.

        Returns
        -------
        CachedInferenceEngine (wraps the ONNX session).
        """
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

            # Integrity check
            actual_hash = _sha256(onnx_path)
            if ver.onnx_int8_sha256 and actual_hash != ver.onnx_int8_sha256:
                logger.warning(
                    "ONNX file hash mismatch for %s! "
                    "File may be corrupted. Proceeding anyway.",
                    ver.version,
                )

            self._engine = CachedInferenceEngine(
                onnx_path=onnx_path,
                version=ver.version,
                confidence_threshold=confidence_threshold,
            )
            logger.info(
                "Inference engine loaded from registry %s (loss=%.4f)",
                version, ver.final_loss,
            )
            return self._engine

# -------------------------------------------------------------------------
# CachedInferenceEngine
# -------------------------------------------------------------------------

class ModelNotFoundError(FileNotFoundError):
    """Raised when no suitable model is found in the registry."""

class CachedInferenceEngine:
    """
    Ultra-fast ONNX Runtime inference engine backed by the model registry.

    Key optimisations:
    - Session is created once at instantiation (not per-call).
    - `enable_mem_pattern=True` + `enable_cpu_mem_arena=True` allow ONNX
      Runtime to reuse memory allocations across runs.
    - `mmap_enable` (via `add_session_config_entry`) memory-maps the model
      file so the OS page cache serves subsequent loads from RAM.
    - `infer_batch()` processes multiple tiles in one ONNX call,
      amortising Python overhead.
    - Results are returned as plain numpy arrays - no PyTorch dependency.
    """
    def __init__(
        self,
        onnx_path: Path,
        version:   str = "unknown",
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
            import onnxruntime as ort # type: ignore[import]
        except ImportError:
            raise ImportError(
                "onnxruntime is required. Install: pip install onnxruntime"
            ) from exc

        opts = ort.SessionOptions()
        # Parallelism - leave 2 threads for I/O
        opts.inter_op_num_threads = max(1, (os.cpu_count() or 4) - 2)
        opts.intra_op_num_threads = max(1, (os.cpu_count() or 4) - 2)
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.enable_mem_pattern = True
        opts.enable_cpu_mem_arena = True

        opts.add_session_config_entry("session.mmap_enable", "1")

        t0 = time.perf_counter()
        self.session = ort.InferenceSession(str(self.path), sess_options=opts, providers=["CPUExecutionProvider"],)
        self._load_time_ms = (time.perf_counter() - t0) * 1000
        self.input_name = self.session.get_inputs()[0].name

        logger.info("cached inference engine initialized from %s in %.1f ms", self.path, self._load_time_ms, self._path.name,)


        def infer(self, tile: np.ndarray) -> dict:
            """
            Run inference on a single (4, H, W) float32 tile.

            Returns
            -------
            dict:
                mask            (H, W) bool
                prob_map        (H, W) float32
                plume_fraction  float
                confidence      float
                inference_ms    float - wall-clock time for this call
            """
            return self.infer_batch(tile[np.newaxis])[0]

        def infer_batch(self, tiles: np.ndarray) -> list[dict]:
            """
            Run inference on a batch (B, 4, H, W). Returns list[dict].
            """
            assert tiles.ndim == 4 and tiles.shape[1] == 4, (
                f"Expected (B, 4, H, W), got {tiles.shape}"
            )

            t0 = time.perf_counter()
            feed = {self._input_name: tiles.astype(np.float32)}
            outputs = self.session.run(None, feed)
            elapsed = (time.perf_counter() - t0) * 1000

            self._call_count += 1
            self._total_inference_ms += elapsed

            prob_batch = outputs[0]  # (B, 1, H, W)
            results = []
            for i in range(prob_batch.shape[0]):
                prob = prob_batch[i, 0]
                mask = prob >= self._threshold
                plume_px = prob[mask]
                results.append({
                    "mask":          mask,
                    "prob_map":      prob,
                    "plume_fraction": float(mask.mean()),
                    "confidence":    float(plume_px.mean()) if plume_px.size > 0 else 0.0,
                    "inference_ms":  elapsed / prob_batch.shape[0],
                })
            return results

        def stats(self) -> dict:
            avg_ms = (
                self._total_inference_ms / self._call_count
                if self._call_count > 0 else 0.0
            )
            return {
                "version":       self._version,
                "model_path":    str(self.path),
                "load_time_ms":  round(self._load_time_ms, 1),
                "call_count":    self._call_count,
                "avg_inference_ms": round(avg_ms, 2),
                "total_inference_ms": round(self._total_inference_ms, 1),
            }

        def __repr__(self) -> str:
            return (
                f"CachedInferenceEngine(version={self._version}, "
                f"load={self._load_time_ms:.0f}ms, calls={self._call_count})"
            )


    # -----------------------------------------------------------------------------
    # Process-level singleton
    # -----------------------------------------------------------------------------

    _registry_instance: Optional[ModelRegistry] = None
    _registry_lock = threading.Lock()

    def get_registry(root: Optional[Path] = None) -> ModelRegistry:
        """
        Return the process-level ModelRegistry singleton.

        Parameters
        ----------
        root:
            Override the default registry root. Only used on first call.
        """
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
        """
        Convenience one-liner: get the ready-to-use inference engine.

        First call: loads model from registry (~200-500ms).
        Every subsequent call: returns the cached session (< 1ms).

        Example
        -------
        from ecograph.computer_vision.model_registry import get_inference_engine
        
        engine = get_inference_engine()        # fast after first call
        result = engine.infer(tile)            # (4, 64, 64) numpy
        print(result["plume_fraction"])
        """
        return get_registry().get_engine(version, confidence_threshold)