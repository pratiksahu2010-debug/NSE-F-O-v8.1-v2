from datetime import datetime, timedelta
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

from engine import scanner as scanner_module
from models import Candle, Underlying, Vote
from utils.market_hours import IST


def _stage1_scanner(symbol, simple_candidate):
    scanner = scanner_module.Scanner.__new__(scanner_module.Scanner)
    scanner.unds = [symbol]
    scanner.pool = Mock()
    scanner.ban = set()
    scanner.hist = {}
    scanner.live_context = {}
    scanner.mkt_bias = 0
    scanner.mkt_ret = None
    scanner._why = {}
    scanner._rej = {}
    scanner._symbol_rejections = {}
    scanner.v7_diagnostics = {}
    scanner.candidate_watchlist = {}
    scanner._candidate_lock = threading.RLock()
    scanner._ready_lock = threading.Lock()
    scanner._ready_state = {}
    scanner._backfill_lock = threading.Lock()
    scanner._backfill_this_scan = 0
    scanner._archive = Mock()
    scanner._watch = Mock()
    scanner._schedule_candidate_watchlist_persistence = Mock()
    scanner._simple_candidate = Mock(return_value=simple_candidate)
    scanner.mex = Mock()
    scanner.mex.universe = {symbol.name}
    scanner.mex.scan.return_value = {
        "sgn": None, "score": 0, "state": "IDLE", "live": {}, "metrics": {}
    }
    scanner.momentum_orb = Mock()
    scanner.momentum_orb.universe = {symbol.name}
    scanner.momentum_orb.scan.return_value = {
        "confirmed_now": False, "metrics": {}
    }
    scanner.live_engine = Mock()
    return scanner


def test_simple_mode_runs_mex_and_orb_without_changing_simple_normal_route():
    now = datetime(2026, 11, 5, 10, 0, tzinfo=IST)
    candle = Candle(now - timedelta(minutes=5), 100, 102, 99, 101, 1000, 0)
    symbol = Underlying("ABC", "STOCK", "NSE_EQ|ABC")
    simple_candidate = {
        "ps": 1.0,
        "votes": [Vote("SIMPLE_TREND", 1.0, "existing SIMPLE rule")],
        "entry_candidate": {"strategy": "SIMPLE_TREND"},
    }
    scanner = _stage1_scanner(symbol, simple_candidate)

    with patch.object(scanner_module.cfg, "STRATEGY_MODE", "SIMPLE"), \
         patch.object(scanner_module.events, "symbol_event", return_value=False), \
         patch.object(scanner_module, "_stage1_fetch_results",
                      return_value=iter([(symbol, ([candle], None), None)])):
        candidates, hits = scanner.stage1(now)

    scanner._simple_candidate.assert_called_once()
    scanner.mex.scan.assert_called_once_with(symbol.name, [candle], [candle])
    scanner.momentum_orb.scan.assert_called_once_with(symbol.name, [candle], [candle])
    assert hits == 1
    assert len(candidates) == 1
    assert candidates[0]["selected_engine"] == "SIMPLE_TREND"
    assert candidates[0]["votes"][0].name == "SIMPLE_TREND"
    assert candidates[0]["entry_candidate"]["strategy"] == "SIMPLE_TREND"


def test_simple_mode_live_dispatch_keeps_mex_and_orb_but_not_legacy_normal():
    scanner = scanner_module.Scanner.__new__(scanner_module.Scanner)
    symbol = Underlying("ABC", "STOCK", "NSE_EQ|ABC")
    scanner.mex = SimpleNamespace(universe={"ABC"})
    scanner.momentum_orb = SimpleNamespace(universe={"ABC"})
    scanner.live_engine = Mock()
    scanner.live_engine.detect.return_value = None
    scanner._live_symbol_locks = {"ABC": threading.RLock()}
    scanner._live_state_lock = threading.Lock()
    scanner._live_inflight = set()
    scanner._closed = False
    partial = Candle(datetime(2026, 11, 5, 10, 0, tzinfo=IST), 100, 102, 99, 101, 1000, 0)
    cached = {"session": [], "allc": [], "fut": []}
    now = datetime(2026, 11, 5, 10, 0, tzinfo=IST)

    with patch.object(scanner_module.cfg, "STRATEGY_MODE", "SIMPLE"):
        scanner._detect_live_candidate(symbol, partial, now, cached)

    scanner.live_engine.detect.assert_called_once()
    kwargs = scanner.live_engine.detect.call_args.kwargs
    assert kwargs["allow_sequential"] is False
    assert kwargs["allow_mex"] is True
    assert kwargs["allow_orb"] is True


def test_signal_alert_requires_all_chat_acknowledgements():
    from models import Signal

    scanner = scanner_module.Scanner.__new__(scanner_module.Scanner)
    scanner.tg = SimpleNamespace(chat_ids=["chat-one", "chat-two"])
    scanner.db = Mock()
    scanner.db.telegram_delivery_status.return_value = {
        "total": 2, "delivered": 2, "pending": 0, "all_delivered": True
    }
    scanner._note_symbol = Mock()
    scanner._deliver_pending_outbox = Mock()
    scanner._mark_alerted = Mock()
    scanner._watch = Mock()
    now = datetime(2026, 11, 5, 10, 5, tzinfo=IST)
    signal = Signal(id="ABC-20261105T100000-C", ts="2026-11-05T10:00:00+05:30",
                    underlying="ABC", side="CALL", confidence=8.0)

    delivered = scanner._queue_signal_alert(signal, "dedupe-key", "alert body", now)

    assert delivered is True
    assert scanner.db.enqueue_telegram.call_count == 2
    scanner._deliver_pending_outbox.assert_called_once()
    scanner._mark_alerted.assert_called_once_with("dedupe-key")
    scanner._watch.assert_called_once()


def test_signal_alert_reports_outbox_enqueue_failure():
    from models import Signal

    scanner = scanner_module.Scanner.__new__(scanner_module.Scanner)
    scanner.tg = SimpleNamespace(chat_ids=["chat-one"])
    scanner.db = Mock()
    scanner.db.enqueue_telegram.side_effect = RuntimeError("database unavailable")
    scanner._note_symbol = Mock()
    scanner._deliver_pending_outbox = Mock()
    now = datetime(2026, 11, 5, 10, 5, tzinfo=IST)
    signal = Signal(id="ABC-20261105T100000-C", ts="2026-11-05T10:00:00+05:30",
                    underlying="ABC", side="CALL", confidence=8.0)

    delivered = scanner._queue_signal_alert(signal, "dedupe-key", "alert body", now)

    assert delivered is False
    scanner._note_symbol.assert_called_once()
    scanner._deliver_pending_outbox.assert_not_called()


def test_normal_15m_context_requires_matching_bullish_or_bearish_direction():
    matches = scanner_module._normal_15m_context_matches

    assert matches("CALL", 1) is True
    assert matches("CALL", -1) is False
    assert matches("CALL", 0) is False

    assert matches("PUT", -1) is True
    assert matches("PUT", 1) is False
    assert matches("PUT", 0) is False

    assert matches("UNKNOWN", 1) is False



def test_normal_structural_invalidation_distance_is_available_for_both_directions():
    from strategies.price import invalidation_distance

    now = datetime(2026, 11, 5, 12, 0, tzinfo=IST)
    candles = []
    for i in range(40):
        close = 100.0 + i * 0.5
        candles.append(Candle(now - timedelta(minutes=5 * (39 - i)),
                              close - 0.2, close + 1.0, close - 1.0,
                              close, 1000, 0))

    call_distance = invalidation_distance("CALL", candles, candles, 120.0, "TREND")
    put_distance = invalidation_distance("PUT", candles, candles, 119.0, "TREND")

    assert call_distance > 0
    assert put_distance > 0
