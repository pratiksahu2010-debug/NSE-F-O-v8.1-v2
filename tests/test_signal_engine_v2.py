from datetime import datetime, timedelta, timezone
from dataclasses import replace

from signal_engine_v2 import EngineConfig, SignalPipeline
from signal_engine_v2.models import (Candidate, Candle, CandleState, MarketSnapshot,
                                     Side, DecisionState)


class FixedStrategy:
    def __init__(self, name, candidates, priority=100):
        self.name, self.candidates, self.priority = name, candidates, priority

    def evaluate(self, snapshot):
        return self.candidates


def snapshot(closed=True):
    ts = datetime(2026, 11, 5, 9, 30, tzinfo=timezone.utc)
    bar = Candle(ts, 100, 105, 99, 104, 1000, closed)
    history_count = 219 if closed else 220
    history = tuple(
        Candle(ts - timedelta(minutes=5 * (history_count - i)),
               100, 101, 99, 100, 1000, True)
        for i in range(history_count)
    )
    bars = history + ((bar,) if closed else ())
    return MarketSnapshot("NIFTY", "INDEX", "5m", bar, bars,
                          indicators={"ema_9": 103.0, "ema_21": 102.0, "ema_50": 101.0,
                                      "session_vwap": 100.0, "vwap_slope_3": 0.2,
                                      "adx_14": 30.0, "plus_di": 30.0, "minus_di": 10.0,
                                      "rsi_14": 60.0, "macd_hist": 0.5, "rvol_20": 2.0,
                                      "atr_14": 2.0},
                          metadata={"htf_bias": 1})

def candidate(strategy="MOMENTUM", side=Side.CALL, score=80, state=CandleState.CLOSED):
    return Candidate("NIFTY", "INDEX", side, strategy, "setup-1", snapshot().candle.timestamp,
                     state, score, 100, 95 if side is Side.CALL else 105,
                     110 if side is Side.CALL else 90, strategy_priority=10)


def test_closed_candidate_is_confirmed():
    pipe = SignalPipeline([FixedStrategy("momentum", [candidate()])])
    decisions = pipe.evaluate(snapshot())
    assert any(x.state is DecisionState.CONFIRMED for x in decisions)


def test_intrabar_candidate_is_explicitly_early():
    pipe = SignalPipeline([FixedStrategy("momentum", [candidate(state=CandleState.INTRABAR)])])
    decisions = pipe.evaluate(snapshot(closed=False))
    assert any(x.state is DecisionState.EARLY for x in decisions)


def test_low_score_is_rejected():
    pipe = SignalPipeline([FixedStrategy("momentum", [candidate(score=64)])],
                          EngineConfig(unified_scoring_enabled=False))
    decisions = pipe.evaluate(snapshot())
    assert any("score_below_minimum" in x.rejected_reasons for x in decisions)


def test_opposite_direction_conflict_without_margin_rejects_both():
    a = candidate("MOMENTUM", Side.CALL, 80)
    b = candidate("BREAKOUT", Side.PUT, 75)
    pipe = SignalPipeline([FixedStrategy("a", [a]), FixedStrategy("b", [b])],
                          EngineConfig(conflict_score_margin=8, unified_scoring_enabled=False))
    decisions = pipe.evaluate(snapshot())
    assert not any(x.state is not DecisionState.REJECTED for x in decisions)
    assert any("directional_conflict_no_clear_winner" in x.rejected_reasons for x in decisions)


def test_repeated_scan_is_deduplicated():
    pipe = SignalPipeline([FixedStrategy("momentum", [candidate()])])
    assert len([x for x in pipe.evaluate(snapshot()) if x.state is DecisionState.CONFIRMED]) == 1
    assert len([x for x in pipe.evaluate(snapshot()) if x.state is DecisionState.CONFIRMED]) == 0

def test_adx_below_22_is_hard_rejected_even_with_high_score():
    snap = snapshot()
    snap = replace(snap, indicators={**snap.indicators, "adx_14": 21.99})
    pipe = SignalPipeline([FixedStrategy("momentum", [candidate(score=95)])],
                          EngineConfig(unified_scoring_enabled=False))
    decisions = pipe.evaluate(snap)
    assert any("adx_below_minimum_22" in x.rejected_reasons for x in decisions)
    assert not any(x.state is not DecisionState.REJECTED for x in decisions)


def test_adx_exactly_22_passes_hard_floor():
    snap = snapshot()
    snap = replace(snap, indicators={**snap.indicators, "adx_14": 22.0})
    pipe = SignalPipeline([FixedStrategy("momentum", [candidate(score=95)])],
                          EngineConfig(unified_scoring_enabled=False))
    decisions = pipe.evaluate(snap)
    assert any(x.state is DecisionState.CONFIRMED for x in decisions)


def test_overextended_entry_is_rejected():
    snap = snapshot()
    snap = replace(snap, indicators={**snap.indicators, "ema_21": 90.0, "atr_14": 2.0})
    pipe = SignalPipeline([FixedStrategy("momentum", [candidate(score=95)])],
                          EngineConfig(unified_scoring_enabled=False, max_entry_extension_atr=1.25))
    decisions = pipe.evaluate(snap)
    assert any("entry_overextended_from_ema21" in x.rejected_reasons for x in decisions)

def test_relative_strength_uses_underlying_minus_index_return():
    from signal_engine_v2.relative_strength import relative_strength
    assert relative_strength(1.8, 0.5) == 1.3
    assert relative_strength(None, 0.5) is None


def test_regime_classification_uses_directional_trend():
    from signal_engine_v2.market_regime import classify_regime
    values = {"adx_14": 27.0, "ema_9": 105.0, "ema_21": 103.0,
              "ema_50": 100.0, "atr_pct": 0.2, "bb_width_pct": 2.0}
    assert classify_regime(values) == "TRENDING_UP"


def test_impulse_detector_labels_multi_factor_expansion():
    from types import SimpleNamespace
    from signal_engine_v2.impulse_detector import detect_impulse
    candle = SimpleNamespace(high=106.0, low=100.0)
    values = {"atr_14": 3.0, "rvol_20": 2.0, "adx_14": 28.0,
              "adx_slope_3": 3.0, "ema_9": 105.0, "ema_21": 103.0,
              "macd_hist": 1.2, "macd_hist_prev": 0.5}
    result = detect_impulse(values, candle)
    assert result["impulse_score"] >= 4.0
    assert result["move_potential"] == "EXPLOSIVE"
