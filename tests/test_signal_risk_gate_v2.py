from datetime import datetime, timezone

from signal_engine_v2.models import Candidate, CandleState, Side
from signal_engine_v2.risk_gate import RiskContext, RiskLimits, validate_daily_risk


def candidate(symbol="NIFTY", side=Side.CALL):
    return Candidate(symbol, "INDEX", side, "BIG_MOMENTUM", "setup",
                     datetime(2026, 11, 5, 9, 30, tzinfo=timezone.utc),
                     CandleState.CLOSED, 80, 100, 95, 110)


def context(**kwargs):
    return RiskContext(now=datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc), **kwargs)


def test_daily_loss_circuit_breaker():
    ok, reason = validate_daily_risk(candidate(), context(daily_losses=4))
    assert not ok and reason == "daily_loss_circuit_breaker"


def test_daily_signal_cap():
    ok, reason = validate_daily_risk(candidate(), context(daily_signals=15))
    assert not ok and reason == "daily_signal_cap_reached"


def test_active_signal_cap():
    ok, reason = validate_daily_risk(candidate(), context(active_signals=6))
    assert not ok and reason == "maximum_active_signals_reached"


def test_bank_group_capacity():
    ok, reason = validate_daily_risk(candidate("BANKNIFTY"),
                                     context(active_by_group={"BANK": 3}))
    assert not ok and reason == "correlation_group_capacity_reached"


def test_same_side_reentry_after_loss_is_blocked():
    ctx = context(stopped_out_sides=frozenset({("NIFTY", "CALL")}))
    ok, reason = validate_daily_risk(candidate(), ctx)
    assert not ok and reason == "same_side_blocked_after_stop_loss"


def test_opposite_side_is_not_blocked_by_same_side_loss():
    ctx = context(stopped_out_sides=frozenset({("NIFTY", "CALL")}))
    ok, reason = validate_daily_risk(candidate(side=Side.PUT), ctx)
    assert ok and reason == ""
