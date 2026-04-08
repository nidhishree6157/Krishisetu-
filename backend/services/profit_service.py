"""
profit_service.py
─────────────────
Farm profit calculation service.

Integrates with:
  • Yield module  — total_yield in kg, yield_per_hectare
  • Market module — current_price in ₹/quintal (100 kg)

Public API
──────────
  calculate_profit(yield_kg, price_per_quintal, cost_inr, area_ha) -> dict

  Returns:
    {
      "yield_kg":            float,
      "yield_quintals":      float,
      "price_per_quintal":   float,
      "area_ha":             float,
      "revenue":             int,      # ₹
      "cost":                int,      # ₹
      "profit":              int,      # ₹  (may be negative)
      "profit_per_hectare":  int,
      "margin_pct":          float,    # profit as % of revenue
      "breakeven_price":     int,      # ₹/quintal to cover costs
      "rating":              str,
      "advice":              str,
    }
"""

from __future__ import annotations


def _safe(val, default: float = 0.0) -> float:
    try:
        v = float(val)
        return v if v >= 0 else default
    except Exception:
        return default


def calculate_profit(
    yield_kg: float,
    price_per_quintal: float,
    cost_inr: float,
    area_ha: float = 1.0,
) -> dict:
    """
    Calculate farm revenue, cost, and profit.

    Args:
        yield_kg           : Total harvested yield in kg (from yield module).
        price_per_quintal  : Market price in ₹ per quintal = 100 kg (from market module).
        cost_inr           : Total farming cost in ₹ (seeds + fertilizer + labour + misc).
        area_ha            : Farm area in hectares (used for per-ha profit).

    Returns:
        Full profit breakdown dict. Never raises.
    """
    try:
        yield_kg           = _safe(yield_kg, 1000.0)
        price_per_quintal  = _safe(price_per_quintal, 2000.0)
        cost_inr           = _safe(cost_inr, 0.0)
        area_ha            = _safe(area_ha, 1.0) or 1.0

        yield_quintals = yield_kg / 100.0
        revenue        = int(yield_quintals * price_per_quintal)
        cost           = int(cost_inr)
        profit         = revenue - cost

        profit_per_ha  = int(profit / area_ha)
        margin_pct     = round((profit / revenue) * 100, 1) if revenue > 0 else 0.0
        breakeven      = int(cost / yield_quintals) if yield_quintals > 0 else 0

        # ── Rating ─────────────────────────────────────────────────────────
        if   profit <= 0:               rating = "Loss"
        elif margin_pct >= 50:          rating = "Excellent"
        elif margin_pct >= 30:          rating = "Good"
        elif margin_pct >= 15:          rating = "Average"
        else:                           rating = "Low Margin"

        # ── Advice ─────────────────────────────────────────────────────────
        _ADVICE = {
            "Excellent":   "Excellent profitability. Reinvest in quality seeds and micro-irrigation to sustain margins.",
            "Good":        "Good profit margin. Explore value-addition (processing, direct marketing) to improve further.",
            "Average":     "Moderate margins. Reduce input costs through bulk buying, FPO membership, or organic transition.",
            "Low Margin":  "Low margin — focus on cost reduction. Consider government input subsidies and crop insurance.",
            "Loss":        "Loss scenario. Consult an agronomist and explore crop insurance / government relief schemes.",
        }
        advice_text = _ADVICE[rating]

        if breakeven > 0 and price_per_quintal < breakeven:
            advice_text += f" Note: current price ₹{int(price_per_quintal)}/q is below break-even of ₹{breakeven}/q."
        elif profit < 0 and revenue > 0:
            shortfall = abs(profit)
            advice_text += f" Cost exceeds revenue by ₹{shortfall:,} — seek expense reduction urgently."

        return {
            "yield_kg":           round(yield_kg, 1),
            "yield_quintals":     round(yield_quintals, 2),
            "price_per_quintal":  round(price_per_quintal, 0),
            "area_ha":            round(area_ha, 2),
            "revenue":            revenue,
            "cost":               cost,
            "profit":             profit,
            "profit_per_hectare": profit_per_ha,
            "margin_pct":         margin_pct,
            "breakeven_price":    breakeven,
            "rating":             rating,
            "advice":             advice_text,
        }

    except Exception as exc:
        print(f"[ProfitService] Error: {exc}")
        return {
            "yield_kg":           0,
            "yield_quintals":     0,
            "price_per_quintal":  0,
            "area_ha":            1.0,
            "revenue":            0,
            "cost":               int(_safe(cost_inr, 0)),
            "profit":             -int(_safe(cost_inr, 0)),
            "profit_per_hectare": 0,
            "margin_pct":         0.0,
            "breakeven_price":    0,
            "rating":             "Unknown",
            "advice":             "Could not calculate profit. Please check your inputs.",
        }
