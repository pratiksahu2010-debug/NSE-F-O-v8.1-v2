"""Big-move acceleration metrics; a score, not a standalone entry trigger."""
from __future__ import annotations


def detect_impulse(indicators: dict, candle) -> dict:
    atr = indicators.get("atr_14")
    rvol = indicators.get("rvol_20")
    adx = indicators.get("adx_14")
    adx_slope = indicators.get("adx_slope_3")
    ema9, ema21 = indicators.get("ema_9"), indicators.get("ema_21")
    hist, prev_hist = indicators.get("macd_hist"), indicators.get("macd_hist_prev")
    score = 0.0
    tags = []
    if atr and atr > 0:
        expansion = (candle.high - candle.low) / atr
        if expansion >= 1.2:
            score += 1.0
            tags.append("range_expansion")
    if rvol is not None and rvol >= 1.5:
        score += 1.0
        tags.append("relative_volume_expansion")
    if adx is not None and adx >= 22 and adx_slope is not None and adx_slope > 0:
        score += 1.0
        tags.append("adx_acceleration")
    if ema9 is not None and ema21 is not None and atr and atr > 0:
        spread = abs(ema9 - ema21) / atr
        if spread >= 0.25:
            score += 1.0
            tags.append("ema_separation")
    if hist is not None and prev_hist is not None and abs(hist) > abs(prev_hist):
        score += 1.0
        tags.append("macd_histogram_expansion")
    return {"impulse_score": score, "impulse_tags": tuple(tags),
            "move_potential": "EXPLOSIVE" if score >= 4 else "STRONG" if score >= 3 else "NORMAL"}
