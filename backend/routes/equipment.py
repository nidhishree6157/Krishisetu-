from __future__ import annotations

from flask import Blueprint, jsonify, request

from services.equipment_service import get_equipment_catalog, list_suitable_crop_labels

equipment_bp = Blueprint("equipment", __name__)


def _filter_by_crop(items: list[dict], crop: str) -> list[dict]:
    c = crop.strip().lower()
    if not c or c == "all":
        return items

    out: list[dict] = []
    for item in items:
        crops = [str(x).strip().lower() for x in (item.get("suitable_crops") or [])]
        if "all crops" in crops:
            out.append(item)
            continue
        if c in crops:
            out.append(item)
            continue
        # e.g. user picks "Maize" and row has "Maize (fodder)"
        if any(c in sc or sc.startswith(c) for sc in crops):
            out.append(item)
    return out


@equipment_bp.route("/list", methods=["GET"])
def get_equipment():
    """
    Returns curated equipment with name, use_case, price_range, suitable_crops, etc.
    Optional query: ?crop=Rice  (filters server-side; client may also filter).
    """
    try:
        data = get_equipment_catalog()
        crop_q = request.args.get("crop", "").strip()
        if crop_q:
            data = _filter_by_crop(data, crop_q)

        return jsonify(
            {
                "success": True,
                "data": data,
                "crop_filters": list_suitable_crop_labels(),
            }
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Failed to fetch equipment",
                    "error": str(e),
                    "data": [],
                    "crop_filters": [],
                }
            ),
            500,
        )
