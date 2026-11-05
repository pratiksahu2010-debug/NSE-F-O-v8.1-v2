from datetime import datetime, timezone

from signal_engine_v2 import EngineConfig, SignalPipeline
from signal_engine_v2.models import (Candidate, Candle, CandleState, MarketSnapshot,
                                     Side, DecisionState)


class FixedStrategy:
    def __init__(self, name, candidates, priority=100):
        self.name, self.candidates, self.priority = name, candidates, priority

    def evaluate(self, snapshot):
        return self.candidates


def snapshot(closed=True):
    bar = Candle(datetime(2026, 11, 5, 9, 30, tzinfo=timezone.utc), 100, 105, 99, 104, 1000, closed)
    return MarketSnapshot("NIFTY", "INDEX", "5m", bar)


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
    pipe = SignalPipeline([FixedStrategy("momentum", [candidate(score=64)])])
    decisions = pipe.evaluate(snapshot())
    assert any("score_below_minimum" in x.rejected_reasons for x in decisions)


def test_opposite_direction_conflict_without_margin_rejects_both():
    a = candidate("MOMENTUM", Side.CALL, 80)
    b = candidate("BREAKOUT", Side.PUT, 75)
    pipe = SignalPipeline([FixedStrategy("a", [a]), FixedStrategy("b", [b])],
                          EngineConfig(conflict_score_margin=8))
    decisions = pipe.evaluate(snapshot())
    assert not any(x.state is not DecisionState.REJECTED for x in decisions)
    assert any("directional_conflict_no_clear_winner" in x.rejected_reasons for x in decisions)


def test_repeated_scan_is_deduplicated():
    pipe = SignalPipeline([FixedStrategy("momentum", [candidate()])])
    assert len([x for x in pipe.evaluate(snapshot()) if x.state is DecisionState.CONFIRMED]) == 1
    assert len([x for x in pipe.evaluate(snapshot()) if x.state is DecisionState.CONFIRMED]) == 0
