"""E2E T5 (mất gói và thêm trễ trước GST 30 s): phải thấy DROP/DELAY rồi vẫn hội tụ."""

from __future__ import annotations

import unittest

from tests.helpers import ScenarioTestCase
from tests.invariants import all_invariants


class TestT5PreGst(ScenarioTestCase):
    scenario_name = "t5_drop_delay_pre_gst"

    def test_invariants_hold(self) -> None:
        self.assertEqual(all_invariants(self.summary, rows=self.rows), [])

    def test_drops_and_delays_before_gst(self) -> None:
        gst_ms = 30000
        drops = [row for row in self.context.events("DROP") if row["time_ms"] < gst_ms]
        delays = [row for row in self.context.events("DELAY") if row["time_ms"] < gst_ms]
        self.assertTrue(drops, "Trước GST phải có gói bị DROP")
        self.assertTrue(delays, "Trước GST phải có gói bị thêm trễ")

    def test_converged_after_gst(self) -> None:
        self.assertTrue(self.summary["converged"])


if __name__ == "__main__":
    unittest.main()
