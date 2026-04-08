"""
create_disease_model.py
───────────────────────
Builds and saves a lightweight CNN for plant disease detection.

The model has the correct architecture and input/output shape, with
randomly-initialised weights.  It will produce consistent (though not
agronomically meaningful) predictions immediately.  Replace it with a
real pre-trained model (e.g. PlantVillage ResNet-50) to improve accuracy.

Input  : (224, 224, 3)  — RGB image, pixel values normalised to [0, 1]
Output : (4,)           — softmax over 4 disease classes

Classes (index → label)
  0  Leaf Blight
  1  Powdery Mildew
  2  Rust
  3  Healthy

Run from backend/ directory:
    python models/create_disease_model.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ── Ensure backend/ is on the path ───────────────────────────────────────────
_HERE    = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

import numpy as np

# ── Output paths ─────────────────────────────────────────────────────────────
MODEL_OUT = _HERE / "disease_model.h5"
META_OUT  = _HERE / "disease_model_meta.json"

LABELS = ["Leaf Blight", "Powdery Mildew", "Rust", "Healthy"]
INPUT_SHAPE = (224, 224, 3)


def build_model():
    """Build a small MobileNet-style CNN suitable for leaf disease classification."""
    try:
        from tensorflow import keras
        from tensorflow.keras import layers
    except ImportError:
        print("[Error] TensorFlow is not installed.")
        print("        Run:  pip install tensorflow")
        sys.exit(1)

    inp = keras.Input(shape=INPUT_SHAPE, name="image_input")

    # Block 1
    x = layers.Conv2D(32, 3, padding="same", activation="relu")(inp)
    x = layers.BatchNormalization()(x)
    x = layers.MaxPooling2D(2)(x)

    # Block 2
    x = layers.Conv2D(64, 3, padding="same", activation="relu")(x)
    x = layers.BatchNormalization()(x)
    x = layers.MaxPooling2D(2)(x)

    # Block 3
    x = layers.Conv2D(128, 3, padding="same", activation="relu")(x)
    x = layers.BatchNormalization()(x)
    x = layers.MaxPooling2D(2)(x)

    # Block 4
    x = layers.Conv2D(256, 3, padding="same", activation="relu")(x)
    x = layers.BatchNormalization()(x)
    x = layers.GlobalAveragePooling2D()(x)

    # Head
    x = layers.Dense(256, activation="relu")(x)
    x = layers.Dropout(0.4)(x)
    out = layers.Dense(len(LABELS), activation="softmax", name="predictions")(x)

    model = keras.Model(inputs=inp, outputs=out, name="plant_disease_detector")
    model.compile(
        optimizer="adam",
        loss="categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model


def save_meta(model) -> None:
    meta = {
        "labels":       LABELS,
        "input_shape":  list(INPUT_SHAPE),
        "n_classes":    len(LABELS),
        "architecture": "custom_cnn_4class",
        "note": (
            "Randomly-initialised weights. Replace disease_model.h5 with a "
            "real pre-trained model (PlantVillage ResNet-50 recommended) for "
            "production accuracy."
        ),
    }
    META_OUT.write_text(json.dumps(meta, indent=2))
    print(f"[Info] Metadata saved -> {META_OUT}")


def smoke_test(model) -> None:
    """Verify model runs inference without errors."""
    dummy = np.random.rand(1, *INPUT_SHAPE).astype("float32")
    preds = model.predict(dummy, verbose=0)
    assert preds.shape == (1, len(LABELS)), f"Unexpected output shape: {preds.shape}"
    idx = int(np.argmax(preds[0]))
    conf = float(np.max(preds[0]))
    print(f"[Smoke] Inference OK  -> {LABELS[idx]} ({conf:.0%})")


def main() -> None:
    print("=" * 55)
    print("  KrishiSetu — Disease Model Builder")
    print("=" * 55)

    print("[Info] Building CNN model ...")
    model = build_model()
    model.summary()

    print(f"\n[Info] Saving model -> {MODEL_OUT}")
    model.save(str(MODEL_OUT))
    print("[Info] Model saved successfully.")

    save_meta(model)
    smoke_test(model)

    print("\n[Done] disease_model.h5 is ready.")
    print("       To upgrade: replace disease_model.h5 with a")
    print("       PlantVillage-trained model keeping the same output shape.")


if __name__ == "__main__":
    main()
