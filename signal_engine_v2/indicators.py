"""Shared, deterministic indicator snapshot builder.

Calculates each indicator once per market snapshot. Index volume is left unknown
unless a reliable volume-weighted proxy has been attached by the data layer.
"""
from __future__ import annotations

from math import sqrt
from types import SimpleNamespace
from typing import Dict, Sequence

from indicators.core import (adx, atr, body_frac, close_pos, ema, macd, rsi,
                             vwap, vol_ratio)


def _legacy(candles):
    # Adapt the v2 immutable candle model to the existing tested pure-Python core.
    return [SimpleNamespace(ts=c.timestamp, o=c.open, h=c.high, l=c.low,
                            c=c.close, v=c.volume, oi=0.0) for c in candles]


def calculate(candles: Sequence, session_candles: Sequence | None = None) -> Dict[str, float | None]:
    bars = list(candles)
    if not bars:
        return {}
    legacy = _legacy(bars)
    closes = [float(c.close) for c in bars]
    highs = [float(c.high) for c in bars]
    lows = [float(c.low) for c in bars]
    volumes = [float(c.volume) for c in bars]
    out: Dict[str, float | None] = {}

    for period in (9, 21, 50, 200):
        series = ema(closes, period)
        out[f"ema_{period}"] = series[-1] if len(series) >= period else None

    rs = rsi(closes, 14)
    out["rsi_14"] = rs[-1] if len(bars) >= 15 else None
    m_line, m_signal, m_hist = macd(closes, 12, 26, 9)
    out["macd"] = m_line[-1] if len(bars) >= 35 else None
    out["macd_signal"] = m_signal[-1] if len(bars) >= 35 else None
    out["macd_hist"] = m_hist[-1] if len(bars) >= 35 else None

    av = adx(legacy, 14)[-1] if len(bars) >= 29 else (None, None, None)
    out["adx_14"], out["plus_di"], out["minus_di"] = av
    out["atr_14"] = atr(legacy, 14)[-1] if len(bars) >= 14 else None

    session = list(session_candles) if session_candles is not None else bars
    session_legacy = _legacy(session)
    vw = vwap(session_legacy)
    out["session_vwap"] = vw[-1] if vw else None
    out["vwap_slope_3"] = (vw[-1] - vw[-4]) if len(vw) >= 4 else None
    out["rvol_20"] = vol_ratio(legacy, 20)

    last = legacy[-1]
    out["candle_body_fraction"] = body_frac(last)
    out["candle_close_position"] = close_pos(last)
    if len(bars) >= 21:
        out["donchian_high_20"] = max(highs[-21:-1])
        out["donchian_low_20"] = min(lows[-21:-1])
    else:
        out["donchian_high_20"] = out["donchian_low_20"] = None

    if len(closes) >= 20:
        mean = sum(closes[-20:]) / 20
        variance = sum((x - mean) ** 2 for x in closes[-20:]) / 20
        sd = sqrt(variance)
        upper, lower = mean + 2 * sd, mean - 2 * sd
        out["bb_mid_20"] = mean
        out["bb_upper_20_2"] = upper
        out["bb_lower_20_2"] = lower
        out["bb_width_pct"] = ((upper - lower) / mean * 100) if mean else None
    else:
        out["bb_mid_20"] = out["bb_upper_20_2"] = out["bb_lower_20_2"] = out["bb_width_pct"] = None

    # OBV is cumulative direction-weighted volume; None when volume is unavailable.
    if len(bars) >= 2 and any(v > 0 for v in volumes):
        obv = 0.0
        for i in range(1, len(bars)):
            if closes[i] > closes[i - 1]:
                obv += volumes[i]
            elif closes[i] < closes[i - 1]:
                obv -= volumes[i]
        out["obv"] = obv
    else:
        out["obv"] = None

    # MFI requires real volume; return None rather than manufacturing a neutral value.
    if len(bars) >= 15 and all(v > 0 for v in volumes[-15:]):
        flows = []
        for i in range(1, len(bars)):
            tp = (highs[i] + lows[i] + closes[i]) / 3
            prev_tp = (highs[i - 1] + lows[i - 1] + closes[i - 1]) / 3
            flows.append((tp * volumes[i], 1 if tp > prev_tp else -1 if tp < prev_tp else 0))
        recent = flows[-14:]
        positive = sum(v for v, d in recent if d > 0)
        negative = sum(v for v, d in recent if d < 0)
        out["mfi_14"] = 100.0 if negative == 0 and positive > 0 else (50.0 if negative == positive == 0 else
                           100.0 - 100.0 / (1.0 + positive / negative))
    else:
        out["mfi_14"] = None

    return out
