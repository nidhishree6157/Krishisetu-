"""
create_pest_model.py
────────────────────
Quick-setup script: builds pest_model.h5 using MobileNetV2 transfer learning.

Architecture (Sequential)
──────────────────────────
  MobileNetV2 (ImageNet, frozen) → GlobalAveragePooling2D
  → Dense(128, relu) → Dense(5, softmax)

Classes (order = model output index)
──────────────────────────────────────
  0  Aphids
  1  Armyworm
  2  Whitefly
  3  Leafhopper
  4  Healthy

Run from backend/ directory
────────────────────────────
    python models/create_pest_model.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE    = Path(__file__).resolve().parent          # backend/models/
_BACKEND = _HERE.parent                             # backend/
sys.path.insert(0, str(_BACKEND))

import os
import json
import numpy as np

# ── Save paths ────────────────────────────────────────────────────────────────
MODEL_OUT = _HERE / "pest_model.h5"
META_OUT  = _HERE / "pest_model_meta.json"

LABELS      = ["Aphids", "Armyworm", "Whitefly", "Leafhopper", "Healthy"]
INPUT_SHAPE = (224, 224, 3)
N_CLASSES   = len(LABELS)


def build_model():
    import tensorflow as tf
    from tensorflow.keras.applications import MobileNetV2
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import Dense, GlobalAveragePooling2D

    print(f"[Build] TensorFlow {tf.__version__}")
    print("[Build] Loading MobileNetV2 (ImageNet weights, frozen) ...")

    base_model = MobileNetV2(
        input_shape=INPUT_SHAPE,
        include_top=False,
        weights="imagenet",
    )
    base_model.trainable = False

    model = Sequential([
        base_model,
        GlobalAveragePooling2D(),
        Dense(128, activation="relu"),
        Dense(N_CLASSES, activation="softmax"),
    ])

    model.compile(
        optimizer="adam",
        loss="categorical_crossentropy",
        metrics=["accuracy"],
    )

    total     = model.count_params()
    trainable = sum(w.numpy().size for l in model.layers if l.trainable for w in l.weights)
    print(f"[Build] Params: {total:,}  trainable={trainable:,}  frozen={total - trainable:,}")
    return model


def save_meta() -> None:
    meta = {
        "labels":       LABELS,
        "input_shape":  list(INPUT_SHAPE),
        "n_classes":    N_CLASSES,
        "backbone":     "MobileNetV2",
        "weights":      "imagenet",
        "note": (
            "MobileNetV2 backbone has real ImageNet pretrained weights. "
            "Classification head (Dense 128 + Dense 5) is randomly initialised. "
            "Fine-tune on labelled pest images for production accuracy."
        ),
    }
    META_OUT.write_text(json.dumps(meta, indent=2))
    print(f"[Build] Metadata  -> {META_OUT}")


def smoke_test(model) -> None:
    dummy = np.random.rand(1, *INPUT_SHAPE).astype("float32")
    preds = model.predict(dummy, verbose=0)
    assert preds.shape == (1, N_CLASSES), f"Unexpected output shape: {preds.shape}"
    idx   = int(np.argmax(preds[0]))
    conf  = float(np.max(preds[0]))
    print(f"[Smoke] Inference OK -> {LABELS[idx]}  ({conf:.0%})")


def main() -> None:
    print("=" * 58)
    print("  KrishiSetu — Pest Detection Model (create_pest_model)")
    print("=" * 58)

    model = build_model()

    # Always delete stale file before saving to prevent HDF5 corruption
    if MODEL_OUT.exists():
        MODEL_OUT.unlink()
        print(f"[Build] Removed stale {MODEL_OUT.name}")

    print(f"[Build] Saving -> {MODEL_OUT}")
    model.save(str(MODEL_OUT))
    size_kb = MODEL_OUT.stat().st_size // 1024
    print(f"[Build] Saved  ({size_kb:,} KB)")

    save_meta()
    smoke_test(model)

    print()
    print("Input shape :", model.input_shape)
    print("Output shape:", model.output_shape)
    print()
    print("pest_model.h5 created successfully!")
    print("Labels:", LABELS)


if __name__ == "__main__":
    main()
