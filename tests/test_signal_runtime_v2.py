from datetime import datetime, timezone

from signal_engine_v2.config import EngineConfig
from signal_engine_v2.models import (Candidate, Candle, CandleState, MarketSnapshot,
                                     Side, DecisionState)
from signal_engine_v2.pipeline import SignalPipeline
from signal_engine_v2.risk_gate import RiskContext, RiskLimits
from signal_engine_v2.runtime import evaluate_snapshot


class OneCandidate:
    name = "TEST"
    priority = 1

    def evaluate(self, snapshot):
        return [Candidate("NIFTY", "INDEX", Side.CALL, "TEST", "runtime-1",
                          snapshot.candle.timestamp, CandleState.CLOSED,
                          80, 100, 95, 110)]


def test_runtime_applies_daily_risk_and_releases_rejected_candidate_for_retry():
    bar = Candle(datetime(2026, 11, 5, 9, 30, tzinfo=timezone.utc),
                 100, 105, 99, 104, 1000, True)
    snap = MarketSnapshot("NIFTY", "INDEX", "5m", bar)
    engine = SignalPipeline([OneCandidate()], EngineConfig(unified_scoring_enabled=False))
    ctx = RiskContext(now=bar.timestamp, daily_losses=4)
    limits = RiskLimits(max_daily_losses=4)
    first = evaluate_snapshot(engine, snap, ctx, limits)
    assert first[0].state is DecisionState.REJECTED
    assert first[0].rejected_reasons == ("daily_loss_circuit_breaker",)

    ctx_ok = RiskContext(now=bar.timestamp)
    second = evaluate_snapshot(engine, snap, ctx_ok, limits)
    assert any(x.state is DecisionState.CONFIRMED for x in second)
