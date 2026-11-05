from datetime import datetime
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

from engine import scanner as scanner_module
from models import Candle, Underlying, Vote
from utils.market_hours import IST


def _stage1_scanner(symbol, candle, simple_candidate):
    scanner = scanner_module.Scanner.__new__(scanner_module.Scanner)
    scanner.unds = [symbol]
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
    candle = Candle(now.replace(minute=55), 100, 102, 99, 101, 1000, 0)
    symbol = Underlying("ABC", "STOCK", "NSE_EQ|ABC")
    simple_candidate = {
        "ps": 1.0,
        "votes": [Vote("SIMPLE_TREND", 1.0, "existing SIMPLE rule")],
        "entry_candidate": {"strategy": "SIMPLE_TREND"},
    }
    scanner = _stage1_scanner(symbol, candle, simple_candidate)

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


def test_simple_mode_does_not_route_normal_through_legacy_intrabar_detector():
    scanner = scanner_module.Scanner.__new__(scanner_module.Scanner)
    scanner.underlying_by_key = {"NSE_EQ|ABC": Underlying("ABC", "STOCK", "NSE_EQ|ABC")}
    scanner.underlying_by_fut_key = {}
    scanner._fut_volume_snapshot = {}
    scanner._live_state_lock = threading.Lock()
    scanner._live_pending = set()
    scanner._live_eval_at = {}
    scanner._closed = False
    scanner.live_engine = Mock()
    scanner.live_engine.update.return_value = object()
    scanner.live_context = {
        "ABC": {
            "session": [], "allc": [], "fut": [],
            "updated_at": datetime(2026, 11, 5, 9, 59, tzinfo=IST).isoformat(),
        }
    }
    scanner.live_engine.detect.return_value = None
    scanner._detect_live_candidate = Mock()
    tick = SimpleNamespace(ltp=101.0, volume=1000)
    received_at = datetime(2026, 11, 5, 10, 0, tzinfo=IST).timestamp()

    with patch.object(scanner_module.cfg, "STRATEGY_MODE", "SIMPLE"), \
         patch.object(scanner_module.cfg, "LIVE_INTRABAR_ENABLED", True):
        scanner.ingest_live_tick("NSE_EQ|ABC", tick, received_at)

    scanner.live_engine.detect.assert_not_called()
    # The tick is accepted for asynchronous MEX/ORB evaluation; the worker
    # itself decides which independent strategy universes are eligible.
    assert scanner._live_pending == {"ABC"}
