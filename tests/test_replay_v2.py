from datetime import datetime, timedelta
from unittest.mock import patch

from tools.replay_v2 import apply_portfolio_limits, simulate_outcome


def test_stop_wins_when_stop_and_target_are_touched_in_same_candle():
    now = datetime(2026, 11, 5, 10, 0)
    future = [type("Bar", (), {"l": 94, "h": 111, "c": 100,
                               "ts": now + timedelta(minutes=5)})()]
    r, reason, used, _ = simulate_outcome("CALL", 100, 95, 105, 110, future)
    assert r == -1
    assert reason == "SL"
    assert used == 1


def row(symbol, when, exit_when, score=80, side="CALL", r=1, exit_reason="T2"):
    return {
        "symbol": symbol, "day": "2026-11-05",
        "signal_ts": when.isoformat(), "exit_ts": exit_when.isoformat(),
        "score": score, "side": side, "r": r, "exit": exit_reason,
    }


def test_portfolio_daily_signal_cap_is_applied_across_symbols():
    start = datetime(2026, 11, 5, 9, 30)
    rows = [row(f"SYM{i}", start + timedelta(minutes=5*i),
                start + timedelta(minutes=5*i), score=90-i) for i in range(16)]
    with patch("tools.replay_v2.cfg.DAILY_SIGNAL_CAP", 15):
        accepted, rejected = apply_portfolio_limits(rows)
    assert len(accepted) == 15
    assert rejected["daily_signal_cap_reached"] == 1


def test_portfolio_correlation_group_limit_is_applied():
    start = datetime(2026, 11, 5, 9, 30)
    symbols = ["BANKNIFTY", "HDFCBANK", "ICICIBANK", "SBIN"]
    rows = [row(symbol, start, start + timedelta(minutes=10), score=90-i)
            for i, symbol in enumerate(symbols)]
    with patch("tools.replay_v2.cfg.MAX_PER_GROUP", 3):
        accepted, rejected = apply_portfolio_limits(rows)
    assert len(accepted) == 3
    assert rejected["correlation_group_capacity_reached"] == 1


def test_daily_loss_circuit_breaker_counts_completed_losing_trades():
    start = datetime(2026, 11, 5, 9, 30)
    rows = []
    for i in range(5):
        signal_time = start + timedelta(minutes=10*i)
        rows.append(row(f"SYM{i}", signal_time, signal_time + timedelta(minutes=5),
                        r=-1, exit_reason="SL"))
    with patch("tools.replay_v2.cfg.MAX_DAILY_LOSSES", 4):
        accepted, rejected = apply_portfolio_limits(rows)
    assert len(accepted) == 4
    assert rejected["daily_loss_circuit_breaker"] == 1
