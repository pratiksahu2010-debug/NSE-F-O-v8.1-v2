import unittest
from unittest.mock import patch
from datetime import datetime, timedelta

from config import cfg
from models import Candle
from strategies.mex_lifecycle import MexLifecycle, CANDIDATE, CONFIRMED, EXPIRED
from utils.market_hours import IST


class MemoryDB:
    def __init__(self):
        self.values = {}
    def kv_get(self, key):
        return self.values.get(key)
    def kv_set(self, key, value):
        self.values[key] = value


class MexLifecycleContinuityTests(unittest.TestCase):
    def setUp(self):
        self.db = MemoryDB()
        self.engine = MexLifecycle(self.db)
        self.start = datetime(2026, 11, 2, 10, 0, tzinfo=IST)

    def candle(self, minute, close=101.5):
        return Candle(self.start + timedelta(minutes=minute), 100, max(102, close), 99, close, 1000)

    def test_immediate_next_bar_confirms(self):
        with patch.object(cfg, "MEX_LIFECYCLE_ENABLED", True):
            first = self.candle(0)
            self.assertEqual(self.engine.observe("TEST", 1, first, 85, "test"), CANDIDATE)
            self.assertEqual(self.engine.observe("TEST", None, self.candle(5, 103)), CONFIRMED)
            self.assertEqual(self.engine.state("TEST")["setup_bar"], first.ts.isoformat())
            self.assertEqual(self.engine.state("TEST")["confirmed_bar"], self.candle(5, 103).ts.isoformat())

    def test_disabled_lifecycle_does_not_wait_for_next_candle(self):
        with patch.object(cfg, "MEX_LIFECYCLE_ENABLED", False):
            bar = self.candle(0)
            self.assertEqual(self.engine.observe("TEST", 1, bar, 85, "test"), CONFIRMED)
            self.assertEqual(self.engine.state("TEST")["state"], "IDLE")

    def test_gap_expires_candidate(self):
        with unittest.mock.patch.object(cfg, "MEX_LIFECYCLE_ENABLED", True):
            self.assertEqual(self.engine.observe("TEST", 1, self.candle(0), 85, "test"), CANDIDATE)
            self.assertEqual(self.engine.observe("TEST", None, self.candle(10, 103)), EXPIRED)


if __name__ == "__main__":
    unittest.main()
