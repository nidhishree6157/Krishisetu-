"""
train_crop_model.py
───────────────────
Trains a 4-feature RandomForest classifier for climate-based crop
recommendation, covering both staple and plantation crops.

Features used
─────────────
  temperature  (°C)
  humidity     (%)
  rainfall     (mm/month)
  ph           (soil pH)

This model is complementary to the 7-feature model in routes/ai.py.
It acts as a plantation-crop validation layer inside the recommendation
pipeline — especially useful when soil NPK data is unavailable or when
the primary model returns low confidence.

Usage
─────
  Run from the backend/ directory:
      python models/train_crop_model.py

  The trained model is saved to:
      backend/models/crop_model.pkl
"""

from __future__ import annotations

import sys
from pathlib import Path

# ── Ensure the script works when run from any directory ──────────────────────
_HERE   = Path(__file__).resolve().parent          # backend/models/
_BACKEND = _HERE.parent                            # backend/
sys.path.insert(0, str(_BACKEND))

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.metrics import classification_report, accuracy_score
from sklearn.preprocessing import LabelEncoder
import joblib

# ── Paths ─────────────────────────────────────────────────────────────────────
DATASET_PATH = _HERE / "crop_dataset.csv"
MODEL_PATH   = _HERE / "crop_model.pkl"
META_PATH    = _HERE / "crop_model_meta.json"

FEATURES  = ["temperature", "humidity", "rainfall", "ph"]
LABEL_COL = "crop"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_dataset() -> pd.DataFrame:
    df = pd.read_csv(DATASET_PATH)
    print(f"[Train] Loaded dataset: {len(df)} rows, {df[LABEL_COL].nunique()} crops")
    print(f"        Crops: {sorted(df[LABEL_COL].unique())}")
    return df


def _validate(df: pd.DataFrame) -> None:
    missing = [c for c in FEATURES + [LABEL_COL] if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset missing columns: {missing}")
    nulls = df[FEATURES + [LABEL_COL]].isnull().sum()
    if nulls.any():
        raise ValueError(f"Dataset has null values:\n{nulls[nulls > 0]}")


def _train(X: np.ndarray, y: np.ndarray) -> RandomForestClassifier:
    """
    Train a RandomForest with hyper-parameters tuned for this 4-feature
    climate dataset.  Returns the fitted model.
    """
    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=None,
        min_samples_split=2,
        min_samples_leaf=1,
        max_features="sqrt",
        random_state=42,
        class_weight="balanced",   # handles class imbalance gracefully
    )
    model.fit(X, y)
    return model


def _evaluate(model: RandomForestClassifier, X: np.ndarray, y: np.ndarray) -> None:
    """Print accuracy metrics and cross-validation score."""
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    model_eval = _train(X_train, y_train)
    y_pred = model_eval.predict(X_test)

    acc = accuracy_score(y_test, y_pred)
    print(f"\n[Eval] Hold-out accuracy: {acc:.1%}")
    print(classification_report(y_test, y_pred))

    cv = cross_val_score(
        RandomForestClassifier(n_estimators=300, random_state=42, class_weight="balanced"),
        X, y, cv=5, scoring="accuracy"
    )
    print(f"[Eval] 5-fold CV accuracy: {cv.mean():.1%} (+/- {cv.std():.1%})")


def _save_meta(model: RandomForestClassifier) -> None:
    """Save model metadata (feature list + classes) for safe loading."""
    import json
    meta = {
        "features": FEATURES,
        "classes":  list(model.classes_),
        "n_estimators": model.n_estimators,
    }
    META_PATH.write_text(json.dumps(meta, indent=2))
    print(f"[Train] Metadata saved -> {META_PATH}")


def _smoke_test(model: RandomForestClassifier) -> None:
    """Quick sanity check: each crop should predict itself on its centroid."""
    centroids = {
        "Arecanut": [25.5, 85.0, 215.0, 6.4],
        "Coconut":  [29.0, 77.0, 168.0, 6.3],
        "Coffee":   [21.0, 73.0, 154.0, 6.1],
        "Pepper":   [26.0, 81.0, 170.0, 6.1],
        "Rice":     [28.0, 77.0, 225.0, 6.4],   # mid-range paddy profile
        "Wheat":    [19.0, 52.0,  77.0, 6.9],
        "Maize":    [26.0, 66.0, 125.0, 6.5],
        "Cotton":   [32.0, 47.0,  58.0, 7.6],
        "Sugarcane":[30.0, 76.0, 183.0, 6.3],
        "Soybean":  [27.0, 64.0, 135.0, 6.4],
        "Groundnut":[29.0, 62.0, 110.0, 6.5],
        "Banana":   [30.0, 78.0, 168.0, 6.5],
    }
    print("\n[Smoke] Centroid predictions:")
    all_ok = True
    for crop, features in centroids.items():
        pred = model.predict([features])[0]
        proba = float(max(model.predict_proba([features])[0]))
        status = "OK" if pred == crop else f"GOT {pred!r}"
        if pred != crop:
            all_ok = False
        print(f"  {crop:<12} -> {pred:<12} ({proba:.0%})  [{status}]")
    if all_ok:
        print("[Smoke] All crops predicted correctly.")
    else:
        print("[Smoke] WARNING: Some crops did not predict correctly.")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  KrishiSetu — Climate-Based Crop Model Training")
    print("=" * 60)

    df = _load_dataset()
    _validate(df)

    X = df[FEATURES].values.astype(float)
    y = df[LABEL_COL].values

    # Evaluate first (uses an 80/20 split internally)
    _evaluate(
        RandomForestClassifier(n_estimators=300, random_state=42, class_weight="balanced"),
        X, y,
    )

    # Train final model on full dataset
    print("\n[Train] Training final model on full dataset ...")
    model = _train(X, y)

    # Persist
    joblib.dump(model, MODEL_PATH)
    print(f"[Train] Model saved -> {str(MODEL_PATH)}")

    _save_meta(model)
    _smoke_test(model)

    print("\n[Train] Done. crop_model.pkl is ready to use.")


if __name__ == "__main__":
    main()
