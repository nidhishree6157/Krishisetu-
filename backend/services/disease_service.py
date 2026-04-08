"""
disease_service.py
──────────────────
Post-processing layer for the disease detection model.

Given the raw model output (disease label + confidence), this service:
  1. Looks up treatment and prevention advice from the knowledge base.
  2. Applies a crop-specific filter when crop_type is provided.
  3. Returns a fully-formed dict that the route can return as JSON.

Public API
──────────
  enrich_prediction(disease: str, confidence: float,
                    crop_type: str | None = None) -> dict
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────────────────────
# DISEASE KNOWLEDGE BASE
# Keys are the exact labels emitted by the model (case-sensitive).
# ──────────────────────────────────────────────────────────────────────────────
_DISEASE_KB: dict[str, dict] = {
    "Leaf Blight": {
        "severity":    "High",
        "description": (
            "Leaf blight is a fungal/bacterial disease causing water-soaked "
            "lesions that expand rapidly, browning and killing leaf tissue. "
            "Left untreated it can reduce yield by 20-50 %."
        ),
        "treatment": (
            "Apply a broad-spectrum fungicide (Mancozeb 75 WP at 2.5 g/L or "
            "Propiconazole 25 EC at 1 mL/L). Remove and burn infected leaves "
            "immediately. Repeat sprays every 10-14 days until symptoms clear."
        ),
        "prevention": (
            "Use disease-resistant varieties. Avoid overhead irrigation — "
            "water at the base to keep foliage dry. Ensure adequate plant "
            "spacing for air circulation. Rotate crops annually."
        ),
        "organic_option": (
            "Spray Trichoderma viride (10 g/L) or neem oil (5 mL/L) as a "
            "biofungicide. Copper oxychloride (3 g/L) is also effective."
        ),
        "urgency": "Act within 48 hours to prevent spread",
    },

    "Powdery Mildew": {
        "severity":    "Medium",
        "description": (
            "Powdery mildew appears as white, powdery fungal growth on leaf "
            "surfaces, stems, and young shoots. It reduces photosynthesis and "
            "distorts new growth. Favoured by dry conditions with high humidity."
        ),
        "treatment": (
            "Apply sulfur-based fungicide (wettable sulfur 80 WP at 2-3 g/L) "
            "or Hexaconazole 5 SC at 2 mL/L. Spray in the early morning. "
            "Karathane (dinocap) at 1 mL/L also gives good control."
        ),
        "prevention": (
            "Avoid dense planting. Remove plant debris after harvest. "
            "Apply potassium bicarbonate sprays preventatively. "
            "Choose mildew-resistant varieties where available."
        ),
        "organic_option": (
            "Spray a 1:9 mixture of milk and water weekly, or baking soda "
            "(5 g/L + a few drops of vegetable oil). Neem oil at 5 mL/L."
        ),
        "urgency": "Treat within 1 week to prevent further spread",
    },

    "Rust": {
        "severity":    "High",
        "description": (
            "Rust diseases cause orange/brown pustules on leaves and stems. "
            "They spread rapidly via windborne spores, especially in cool, "
            "moist conditions. Severe infections defoliate entire crops."
        ),
        "treatment": (
            "Apply copper-based fungicide (Copper Oxychloride 50 WP at 3 g/L "
            "or Bordeaux mixture 1 %). Propiconazole 25 EC (1 mL/L) or "
            "Tebuconazole 25.9 EC (1 mL/L) are highly effective systemic options. "
            "Two to three sprays at 7-day intervals are typically required."
        ),
        "prevention": (
            "Plant rust-resistant varieties. Remove and destroy infected "
            "plant material. Avoid late planting. Ensure balanced fertilisation "
            "— excess nitrogen increases susceptibility."
        ),
        "organic_option": (
            "Spray diluted neem oil (10 mL/L) or garlic extract (50 g/L). "
            "Trichoderma harzianum at 5 g/L as a preventive soil drench."
        ),
        "urgency": "Act immediately — rust spreads very fast",
    },

    "Healthy": {
        "severity":    "None",
        "description": (
            "No disease detected. The plant appears healthy. Continue regular "
            "monitoring and follow good agronomic practices."
        ),
        "treatment":      "No treatment required.",
        "prevention": (
            "Maintain soil health with organic matter. Water appropriately, "
            "avoid waterlogging. Monitor weekly for early signs of disease. "
            "Practice crop rotation and use certified disease-free seeds."
        ),
        "organic_option": "No action required.",
        "urgency":        "No immediate action required",
    },
}

# ── Crop-specific notes appended to treatment when crop_type is supplied ─────
_CROP_NOTES: dict[str, dict[str, str]] = {
    "wheat": {
        "Rust":          "For wheat rust (stripe/leaf/stem), use Propiconazole at flag-leaf stage.",
        "Leaf Blight":   "Karnal Bunt and Alternaria blight are common in wheat — isolate infected lots.",
    },
    "rice": {
        "Leaf Blight":   "Bacterial Leaf Blight in rice: use Copper Oxychloride 0.3 % or Streptomycin.",
        "Rust":          "Brown leaf spot is common in rice paddies — ensure proper drainage.",
    },
    "tomato": {
        "Leaf Blight":   "Early/Late Blight in tomato: remove lower foliage, apply Mancozeb weekly.",
        "Powdery Mildew":"Use Azoxystrobin (1 mL/L) specifically for tomato powdery mildew.",
    },
    "potato": {
        "Leaf Blight":   "Late Blight in potato: act within 24 h. Use Metalaxyl+Mancozeb (2 g/L).",
    },
    "corn": {
        "Rust":          "Southern corn rust: apply Azoxystrobin or Pyraclostrobin at first signs.",
        "Leaf Blight":   "Northern corn leaf blight: resistant hybrids are the best long-term strategy.",
    },
    "cotton": {
        "Leaf Blight":   "Bacterial blight in cotton: use copper bactericide, avoid leaf wetting.",
    },
    "sugarcane": {
        "Rust":          "Orange rust in sugarcane: remove affected ratoons, use resistant varieties.",
    },
}

# ── One-liner explanation per disease ────────────────────────────────────────
# Shown prominently in the UI as a quick summary before detailed treatment info.
_EXPLANATIONS: dict[str, str] = {
    "Leaf Blight":    "Bacterial/fungal disease causing rapid browning of leaf tissue, common in humid fields.",
    "Powdery Mildew": "Fungal disease visible as white powder on leaves; thrives in warm, dry-but-humid weather.",
    "Rust":           "Fungal disease spreading via windborne spores, creates orange-brown pustules on leaves.",
    "Healthy":        "No disease detected — plant appears healthy. Keep up current management practices.",
}

# ── Recommended fertilizer / corrective action per disease ───────────────────
# Simple first-response advice; does NOT replace a proper agronomist visit.
_FERTILIZER_MAP: dict[str, str] = {
    "Leaf Blight":    "Use nitrogen-balanced fertilizer. Avoid excess nitrogen, which worsens blight spread.",
    "Powdery Mildew": "Apply potassium bicarbonate spray. Reduce nitrogen, increase potassium in fertilizer.",
    "Rust":           "Apply copper fungicide or neem oil. Ensure balanced micro-nutrients (avoid excess N).",
    "Healthy":        "Continue regular balanced fertilization — no corrective action needed.",
}

# ── Confidence interpretation ─────────────────────────────────────────────────
def _confidence_label(conf: float) -> str:
    """Convert 0-1 confidence to a human-readable label."""
    if conf >= 0.85:
        return "Very High"
    if conf >= 0.70:
        return "High"
    if conf >= 0.50:
        return "Moderate"
    return "Low — consider manual verification"


# ── Public API ────────────────────────────────────────────────────────────────

def enrich_prediction(
    disease:    str,
    confidence: float,
    crop_type:  str | None = None,
) -> dict:
    """
    Augment a raw model prediction with treatment and prevention information.

    Args:
        disease:    Disease label from the ML model (e.g. "Leaf Blight").
        confidence: Model softmax confidence in [0, 1].
        crop_type:  Optional crop name (e.g. "wheat") for crop-specific notes.

    Returns:
        A dict ready to be serialised as a JSON API response:
          success          bool
          disease          str   — original label
          confidence       float — 0-1, as returned by the model
          confidence_pct   str   — human-readable percentage
          confidence_label str   — "High / Moderate / Low"
          severity         str   — "None / Medium / High"
          is_healthy       bool
          description      str
          treatment        str
          prevention       str
          organic_option   str
          urgency          str
          crop_note        str   — crop-specific addendum (may be "")
    """
    info = _DISEASE_KB.get(disease)
    if info is None:
        # Unknown class — return safe defaults
        info = {
            "severity":      "Unknown",
            "description":   f"Detected: {disease}. Consult an agronomist for details.",
            "treatment":     "Consult your nearest KVK or agriculture officer.",
            "prevention":    "Maintain good field hygiene and monitor regularly.",
            "organic_option":"Neem oil spray (5 mL/L) as a general precaution.",
            "urgency":       "Seek expert advice",
        }

    crop_note = ""
    if crop_type:
        crop_notes_for_disease = _CROP_NOTES.get(crop_type.lower(), {})
        crop_note = crop_notes_for_disease.get(disease, "")

    return {
        "success":           True,
        # Primary label — returned under both keys so old and new frontend code works.
        "disease":           disease,
        "label":             disease,          # alias: frontend should use data.label
        "confidence":        round(confidence, 4),         # 0–1 for frontend math
        "confidence_pct":    f"{confidence * 100:.1f}%",
        "confidence_label":  _confidence_label(confidence),
        "severity":          info["severity"],
        "is_healthy":        disease == "Healthy",
        # Detailed knowledge-base fields
        "explanation":       _EXPLANATIONS.get(disease, "No detailed explanation available."),
        "description":       info["description"],
        "treatment":         info["treatment"],
        "fertilizer":        _FERTILIZER_MAP.get(disease, "Consult your nearest agronomist or KVK."),
        "prevention":        info["prevention"],
        "organic_option":    info["organic_option"],
        "urgency":           info["urgency"],
        "crop_note":         crop_note,
    }
