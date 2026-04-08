"""
soil_parser.py
──────────────
Extracts soil nutrient values (N, P, K, pH) from an uploaded file.

Current implementation: returns sensible demo values so the rest of
the pipeline (auto-fill, model input) works end-to-end right away.

Upgrade path (when ready):
  PDF  → use pdfplumber / PyMuPDF to extract text, then regex for values
  Image → use pytesseract (Tesseract OCR) to read scanned reports
  Both → run the text through a regex/NLP extractor to pull numeric fields
"""

from __future__ import annotations

import os
import re


# ── Typical mid-range Indian agricultural soil values (demo defaults) ──
_DEMO_VALUES = {
    "nitrogen":   82.0,   # kg/ha
    "phosphorus": 38.0,   # kg/ha
    "potassium":  42.0,   # kg/ha
    "ph":          6.4,   # 0–14
}


def _try_pdf_extract(filepath: str) -> dict | None:
    """
    Attempt text extraction from a PDF using pdfplumber.
    Returns a partial dict of found values, or None if the library
    is not installed / file cannot be parsed.
    """
    try:
        import pdfplumber   # optional dependency
        text = ""
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or "") + "\n"
        return _parse_text(text) if text.strip() else None
    except Exception:
        return None


def _try_image_extract(filepath: str) -> dict | None:
    """
    Attempt OCR on an image file using pytesseract.
    Returns a partial dict of found values, or None if the library
    is not installed / file cannot be read.
    """
    try:
        from PIL import Image       # optional dependency
        import pytesseract          # optional dependency
        text = pytesseract.image_to_string(Image.open(filepath))
        return _parse_text(text) if text.strip() else None
    except Exception:
        return None


# Regex patterns to pull labelled numeric values from report text.
_PATTERNS = {
    "nitrogen":   re.compile(r"nitrogen[^\d]*(\d+(?:\.\d+)?)", re.I),
    "phosphorus": re.compile(r"phosphorus[^\d]*(\d+(?:\.\d+)?)", re.I),
    "potassium":  re.compile(r"potassium[^\d]*(\d+(?:\.\d+)?)", re.I),
    "ph":         re.compile(r"\bph[^\d]*(\d+(?:\.\d+)?)", re.I),
}


def _parse_text(text: str) -> dict:
    """Extract numeric values from free-form text using regex."""
    result = {}
    for key, pattern in _PATTERNS.items():
        m = pattern.search(text)
        if m:
            try:
                result[key] = float(m.group(1))
            except ValueError:
                pass
    return result


def extract_soil_data(filepath: str) -> dict:
    """
    Public API.  Accepts the absolute path of an uploaded soil report
    (PDF or image).  Returns a dict with keys:
        nitrogen, phosphorus, potassium, ph

    All values are guaranteed to be present (demo defaults fill any gap).

    Args:
        filepath: Absolute or relative path to the uploaded file.

    Returns:
        dict with numeric soil values.
    """
    result: dict = {}

    if filepath and os.path.isfile(filepath):
        ext = os.path.splitext(filepath)[1].lower()

        if ext == ".pdf":
            result = _try_pdf_extract(filepath) or {}
        elif ext in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}:
            result = _try_image_extract(filepath) or {}

    # Fill any missing fields with demo defaults so callers always get
    # a complete, usable dict.
    for key, default in _DEMO_VALUES.items():
        if key not in result or result[key] is None:
            result[key] = default

    # Sanity-clamp extracted values to agronomic ranges.
    result["nitrogen"]   = max(0.0, min(float(result["nitrogen"]),   300.0))
    result["phosphorus"] = max(0.0, min(float(result["phosphorus"]), 150.0))
    result["potassium"]  = max(0.0, min(float(result["potassium"]),  300.0))
    result["ph"]         = max(3.0, min(float(result["ph"]),          10.0))

    print(f"[SoilParser] Extracted from '{filepath}': {result}")
    return result
