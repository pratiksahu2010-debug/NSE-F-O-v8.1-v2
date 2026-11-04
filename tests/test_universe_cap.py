import os
import unittest

os.environ.setdefault("DB_PATH", ":memory:")

from bot import select_bounded_universe
from models import Underlying


def und(name, kind="STOCK"):
    return Underlying(name=name, kind=kind, spot_key=f"key:{name}")


class TestBoundedUniverse(unittest.TestCase):
    def test_caps_total_symbols_including_indices(self):
        indices = [und("NIFTY", "INDEX"), und("BANKNIFTY", "INDEX")]
        stocks = [und(f"S{i}") for i in range(60)]
        selected = select_bounded_universe(indices, stocks, [f"S{i}" for i in range(50)], [], 40)
        self.assertEqual(len(selected), 40)
        self.assertEqual([x.name for x in selected[:2]], ["NIFTY", "BANKNIFTY"])
        self.assertEqual(selected[-1].name, "S37")

    def test_does_not_fill_slots_from_unranked_master_order(self):
        indices = [und("NIFTY", "INDEX")]
        stocks = [und("A"), und("B"), und("C")]
        selected = select_bounded_universe(indices, stocks, ["B"], [], 40)
        self.assertEqual([x.name for x in selected], ["NIFTY", "B"])

    def test_priority_symbols_are_additive_and_deduplicated(self):
        indices = [und("NIFTY", "INDEX")]
        stocks = [und("A"), und("B")]
        selected = select_bounded_universe(indices, stocks, ["A"], ["A", "B"], 3)
        self.assertEqual([x.name for x in selected], ["NIFTY", "A", "B"])

    def test_zero_or_negative_cap_is_safe(self):
        self.assertEqual(select_bounded_universe([und("NIFTY", "INDEX")], [], [], [], 0), [])
        self.assertEqual(select_bounded_universe([und("NIFTY", "INDEX")], [], [], [], -3), [])


if __name__ == "__main__":
    unittest.main()
