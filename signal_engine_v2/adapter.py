"""Bridge the existing Upstox/legacy data models into the isolated v2 engine."""
from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Optional, Sequence

from indicators.core import htf_bias
from models import Candle as LegacyCandle
from .indicators import enrich_snapshot
from .models import Candle, MarketSnapshot


def _convert(bar: LegacyCandle, is_closed: bool = True) -> Candle:
    return Candle(bar.ts, float(bar.o), float(bar.h), float(bar.l),
                  float(bar.c), max(0.0, float(bar.v or 0.0)), is_closed)


def build_snapshot(underlying: str, instrument_kind: str, timeframe: str,
                   candles: Sequence[LegacyCandle],
                   live_candle: Optional[LegacyCandle] = None,
                   futures_volume_by_timestamp: Optional[Mapping] = None,
                   metadata: Optional[dict] = None) -> MarketSnapshot:
    """Create a v2 snapshot from existing feed candles.

    Historical candles must be finalized. A supplied live candle remains
    provisional and is never used in indicator warm-up. For index underlyings,
    futures volume can weight the index typical price without introducing
    futures premium/basis into the price series.
    """
    if not candles and live_candle is None:
        raise ValueError("at least one candle is required")
    closed = [_convert(x, True) for x in candles]
    partial = _convert(live_candle, False) if live_candle is not None else None
    current = partial or closed[-1]
    analysis_bars = list(closed)
    details = dict(metadata or {})

    volume_map = futures_volume_by_timestamp or {}
    if instrument_kind.upper() == "INDEX" and volume_map:
        covered = sum(1 for b in analysis_bars if float(volume_map.get(b.timestamp, 0) or 0) > 0)
        if analysis_bars and covered >= 0.8 * len(analysis_bars):
            analysis_bars = [replace(b, volume=max(0.0, float(volume_map.get(b.timestamp, 0) or 0)))
                             for b in analysis_bars]
            details["volume_source"] = "current_month_future_volume"
        else:
            details["volume_source"] = "unavailable"
    elif instrument_kind.upper() == "STOCK":
        details["volume_source"] = "underlying_equity_volume"
    else:
        details["volume_source"] = "unavailable"

    snap = MarketSnapshot(
        underlying=underlying.upper(),
        instrument_kind=instrument_kind.upper(),
        timeframe=timeframe,
        candle=current,
        candles=tuple(analysis_bars),
        metadata=details,
    )
    snap = enrich_snapshot(snap)
    legacy_closed = [LegacyCandle(b.timestamp, b.open, b.high, b.low, b.close, b.volume, 0)
                     for b in analysis_bars]
    bias = htf_bias(legacy_closed, minutes=15, completed_only=True)
    return replace(snap, metadata={**dict(snap.metadata), "htf_bias": bias})
