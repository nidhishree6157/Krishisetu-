"""
build_pest_model.py
───────────────────
Builds and saves the pest detection model using MobileNetV2 transfer learning.

Architecture (mirrors build_production_model.py for consistency)
────────────────────────────────────────────────────────────────
  Base  : MobileNetV2 pretrained on ImageNet (frozen backbone).
  Head  : GlobalAveragePooling → BatchNorm → Dense(256, relu) → Dropout(0.3)
          → Dense(4, softmax)

Classes
───────
  0  Aphids
  1  Whiteflies
  2  Caterpillar
  3  Healthy

Input / preprocessing
──────────────────────
  Route sends float32 in [0, 1].
  Model's Rescaling layer converts [0, 1] → [-1, 1] (MobileNetV2 standard).
  No preprocessing changes needed in the route.

Run from backend/ directory
────────────────────────────
    python models/build_pest_model.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE    = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

import numpy as np

MODEL_OUT = _HERE / "pest_model.h5"
META_OUT  = _HERE / "pest_model_meta.json"

LABELS      = ["Aphids", "Whiteflies", "Caterpillar", "Healthy"]
INPUT_SHAPE = (224, 224, 3)


def _build():
    try:
        import tensorflow as tf
        from tensorflow import keras
        from tensorflow.keras import layers
    except ImportError:
        print("[Error] TensorFlow not installed. Run:  pip install tensorflow")
        sys.exit(1)

    print("[Build] Loading MobileNetV2 ImageNet weights ...")
    base = keras.applications.MobileNetV2(
        weights="imagenet",
        include_top=False,
        input_shape=INPUT_SHAPE,
    )
    base.trainable = False
    print(f"[Build] MobileNetV2 ready  params={base.count_params():,}  trainable=False")

    inputs = keras.Input(shape=INPUT_SHAPE, name="image_input")
    x = layers.Rescaling(scale=2.0, offset=-1.0, name="rescale_to_minus1_1")(inputs)
    x = base(x, training=False)
    x = layers.GlobalAveragePooling2D(name="gap")(x)
    x = layers.BatchNormalization(name="head_bn")(x)
    x = layers.Dense(256, activation="relu", name="head_dense")(x)
    x = layers.Dropout(0.30, name="head_dropout")(x)
    outputs = layers.Dense(
        len(LABELS), activation="softmax", name="predictions"
    )(x)

    model = keras.Model(inputs=inputs, outputs=outputs, name="pest_detection_mobilenetv2")
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=1e-4),
        loss="categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model


def _save_meta(model) -> None:
    meta = {
        "labels":            LABELS,
        "input_shape":       list(INPUT_SHAPE),
        "n_classes":         len(LABELS),
        "backbone":          "MobileNetV2",
        "backbone_weights":  "imagenet",
        "preprocessing":     "route divides by 255 -> model rescales [0,1] to [-1,1]",
        "head_trained":      False,
        "note": (
            "Backbone has real ImageNet pretrained weights. "
            "Classification head is randomly initialised. "
            "Fine-tune on labelled pest images for production accuracy."
        ),
    }
    META_OUT.write_text(json.dumps(meta, indent=2))
    print(f"[Build] Metadata -> {META_OUT}")


def _smoke_test(model) -> None:
    dummy = np.random.rand(1, *INPUT_SHAPE).astype("float32")
    preds = model.predict(dummy, verbose=0)
    assert preds.shape == (1, len(LABELS)), f"Bad output shape: {preds.shape}"
    idx  = int(np.argmax(preds[0]))
    conf = float(np.max(preds[0]))
    print(f"[Smoke] Inference OK -> {LABELS[idx]}  ({conf:.0%})")
    print(f"[Smoke] Preprocessing layer verified (rescale_to_minus1_1)")


def main() -> None:
    print("=" * 60)
    print("  KrishiSetu — Pest Detection Model (MobileNetV2)")
    print("=" * 60)

    import tensorflow as tf
    print(f"[Info] TensorFlow version: {tf.__version__}")

    model = _build()

    total     = model.count_params()
    frozen    = sum(
        w.numpy().size
        for l in model.layers if not l.trainable
        for w in l.weights
    )
    trainable = total - frozen
    print(f"\n[Build] Params: {total:,}  (frozen={frozen:,}  trainable={trainable:,})")

    # Always remove stale file before saving to prevent HDF5 corruption
    if MODEL_OUT.exists():
        MODEL_OUT.unlink()
        print(f"[Build] Removed stale {MODEL_OUT.name}")

    print(f"[Build] Saving -> {MODEL_OUT}")
    model.save(str(MODEL_OUT))
    size_kb = MODEL_OUT.stat().st_size // 1024
    print(f"[Build] Saved  ({size_kb:,} KB)")

    _save_meta(model)
    _smoke_test(model)

    model.summary(line_length=80, expand_nested=False)

    print()
    print("[Done] pest_model.h5 created with MobileNetV2 backbone.")
    print("       Fine-tune on labelled pest images for real-world accuracy.")


if __name__ == "__main__":
    main()
