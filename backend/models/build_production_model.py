"""
build_production_model.py
─────────────────────────
Builds a production-grade plant disease detector using transfer learning.

Architecture
────────────
  Base  : MobileNetV2  — pretrained on ImageNet (1.28 M images, 1000 classes).
          Backbone weights are FROZEN; only the classification head is trained.
  Head  : GlobalAveragePooling → BatchNorm → Dense(256, relu) → Dropout(0.3)
          → Dense(4, softmax)

Preprocessing (built INTO the model)
─────────────────────────────────────
  Input from route  : float32 array  in [0, 1]  shape (1, 224, 224, 3)
  Rescaling layer   : [0, 1]  →  [-1, 1]   (MobileNetV2 internal standard)
  MobileNetV2 base  : applies its own normalisation internally

  Because preprocessing is inside the model, routes/disease.py does NOT need
  any changes — its existing /255 normalisation stays exactly as-is.

Output
──────
  Softmax over 4 disease classes (must match LABELS in routes/disease.py):
    0  Leaf Blight
    1  Powdery Mildew
    2  Rust
    3  Healthy

Fine-tuning note
────────────────
  The backbone has real ImageNet pretrained weights.
  The 4-class head is randomly initialised until you fine-tune.
  To fine-tune with a real dataset:
    1. Supply labelled plant disease images (PlantVillage or similar).
    2. Uncomment "base.trainable = True" in _build().
    3. Use a very small learning rate (1e-5) to avoid destroying pretrained weights.
    4. Run model.fit() for 10-20 epochs.
    5. Save the fine-tuned model to models/disease_model.h5.

Run from backend/ directory
────────────────────────────
    python models/build_production_model.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ── Add backend/ to sys.path ──────────────────────────────────────────────────
_HERE    = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

import numpy as np

MODEL_OUT = _HERE / "disease_model.h5"
META_OUT  = _HERE / "disease_model_meta.json"

LABELS       = ["Leaf Blight", "Powdery Mildew", "Rust", "Healthy"]
INPUT_SHAPE  = (224, 224, 3)
INPUT_HEIGHT = INPUT_SHAPE[0]
INPUT_WIDTH  = INPUT_SHAPE[1]


# ── Build model ───────────────────────────────────────────────────────────────

def _build():
    try:
        import tensorflow as tf
        from tensorflow import keras
        from tensorflow.keras import layers
    except ImportError:
        print("[Error] TensorFlow not installed. Run:  pip install tensorflow")
        sys.exit(1)

    print("[Build] Downloading MobileNetV2 ImageNet weights (first run only) ...")

    # ── Pretrained backbone ──────────────────────────────────────────────────
    base = keras.applications.MobileNetV2(
        weights="imagenet",          # downloads ~14 MB on first run
        include_top=False,           # drop the 1000-class ImageNet head
        input_shape=INPUT_SHAPE,
    )
    base.trainable = False           # freeze backbone — use as feature extractor
    print(f"[Build] MobileNetV2 loaded  params={base.count_params():,}  trainable=False")

    # ── Model with preprocessing built in ────────────────────────────────────
    # The route sends float32 in [0,1].  MobileNetV2 expects [-1,1].
    # We handle the conversion inside the model with a Rescaling layer so the
    # route never needs to know which model is loaded.

    inputs = keras.Input(shape=INPUT_SHAPE, name="image_input")

    # [0, 1]  →  [-1, 1]  (MobileNetV2 requirement)
    x = layers.Rescaling(scale=2.0, offset=-1.0, name="rescale_to_minus1_1")(inputs)

    # Feature extraction (frozen ImageNet weights)
    x = base(x, training=False)

    # Classification head (randomly initialised — fine-tune for real accuracy)
    x = layers.GlobalAveragePooling2D(name="gap")(x)
    x = layers.BatchNormalization(name="head_bn")(x)
    x = layers.Dense(256, activation="relu", name="head_dense")(x)
    x = layers.Dropout(0.30, name="head_dropout")(x)
    outputs = layers.Dense(
        len(LABELS), activation="softmax", name="predictions"
    )(x)

    model = keras.Model(inputs=inputs, outputs=outputs, name="plant_disease_mobilenetv2")
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=1e-4),
        loss="categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model


# ── Metadata ──────────────────────────────────────────────────────────────────

def _save_meta(model) -> None:
    meta = {
        "labels":       LABELS,
        "input_shape":  list(INPUT_SHAPE),
        "n_classes":    len(LABELS),
        "backbone":     "MobileNetV2",
        "backbone_weights": "imagenet",
        "preprocessing": "route divides by 255 → model rescales [0,1] to [-1,1]",
        "head_trained":  False,
        "note": (
            "Backbone has real ImageNet pretrained weights. "
            "Classification head is randomly initialised. "
            "Fine-tune on PlantVillage data for production accuracy."
        ),
    }
    META_OUT.write_text(json.dumps(meta, indent=2))
    print(f"[Build] Metadata saved -> {META_OUT}")


# ── Smoke test ────────────────────────────────────────────────────────────────

def _smoke_test(model) -> None:
    dummy = np.random.rand(1, *INPUT_SHAPE).astype("float32")   # [0,1] input
    preds = model.predict(dummy, verbose=0)
    assert preds.shape == (1, len(LABELS)), f"Bad output shape: {preds.shape}"
    idx  = int(np.argmax(preds[0]))
    conf = float(np.max(preds[0]))
    print(f"[Smoke] Inference OK -> {LABELS[idx]}  ({conf:.0%})")

    # Verify preprocessing layer is present
    layer_names = [l.name for l in model.layers]
    assert "rescale_to_minus1_1" in layer_names, "Rescaling layer missing!"
    print(f"[Smoke] Preprocessing layer verified (rescale_to_minus1_1)")
    print(f"[Smoke] Total layers: {len(model.layers)}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 62)
    print("  KrishiSetu — Production Disease Model (MobileNetV2)")
    print("=" * 62)

    import tensorflow as tf
    print(f"[Info] TensorFlow version: {tf.__version__}")

    model = _build()

    total  = model.count_params()
    frozen = sum(
        w.numpy().size
        for l in model.layers if not l.trainable
        for w in l.weights
    )
    trainable = total - frozen
    print(f"\n[Build] Model params: {total:,}  "
          f"(frozen={frozen:,}  trainable={trainable:,})")

    # Always delete any existing file first.
    # If an old .h5 file is present, TF appends new data without overwriting
    # the legacy root 'model_config' attribute — causing a load failure on
    # the next startup.  A fresh file guarantees a clean save.
    if MODEL_OUT.exists():
        MODEL_OUT.unlink()
        print(f"[Build] Removed stale {MODEL_OUT.name}")

    print(f"[Build] Saving model -> {MODEL_OUT}")
    model.save(str(MODEL_OUT))
    size_kb = MODEL_OUT.stat().st_size // 1024
    print(f"[Build] Saved  ({size_kb:,} KB)")

    _save_meta(model)
    _smoke_test(model)

    model.summary(line_length=80, expand_nested=False)

    print()
    print("[Done] disease_model.h5 upgraded to MobileNetV2 backbone.")
    print("       Backbone weights: ImageNet pretrained (real).")
    print("       Head weights:     randomly initialised (fine-tune for accuracy).")
    print()
    print("  To fine-tune on real plant disease data:")
    print("  1. Prepare labelled images in  data/plant_diseases/{class_name}/")
    print("  2. Edit build_production_model.py -> set  base.trainable = True")
    print("  3. Run  python models/build_production_model.py  again")


if __name__ == "__main__":
    main()
