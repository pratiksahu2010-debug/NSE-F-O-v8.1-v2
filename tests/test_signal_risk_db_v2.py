from datetime import datetime, timezone
from types import SimpleNamespace

from signal_engine_v2.risk_gate import risk_context_from_db


class FakeDB:
    def signals_on(self, day):
        return [
            SimpleNamespace(underlying="NIFTY", side="CALL", ts=day+"T09:30:00+00:00",
                            status="CLOSED", result="LOSS", exit_reason="SL"),
            SimpleNamespace(underlying="BANKNIFTY", side="PUT", ts=day+"T10:00:00+00:00",
                            status="ACTIVE", result="", exit_reason=""),
            SimpleNamespace(underlying="RELIANCE", side="CALL", ts=day+"T10:05:00+00:00",
                            status="T1_HIT", result="", exit_reason=""),
        ]


def test_risk_context_restores_daily_limits_and_group_exposure():
    now = datetime(2026, 11, 5, 11, 0, tzinfo=timezone.utc)
    context = risk_context_from_db(FakeDB(), now)
    assert context.daily_signals == 3
    assert context.daily_losses == 1
    assert context.active_signals == 2
    assert context.active_by_group["BANK"] == 1
    assert ("NIFTY", "CALL") in context.stopped_out_sides
    assert context.last_signal_at["RELIANCE"].hour == 10
