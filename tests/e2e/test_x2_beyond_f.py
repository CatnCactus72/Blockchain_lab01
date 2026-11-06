"""E2E X2 (4 node im lặng, vượt f): mất tiến trình nhưng không bao giờ finalize sai."""

from __future__ import annotations

import unittest

from tests.helpers import ScenarioTestCase
from tests.invariants import all_invariants


class TestX2BeyondF(ScenarioTestCase):
    scenario_name = "x2_beyond_f"

    def test_invariants_hold(self) -> None:
        # Đây là bất biến quan trọng nhất khi vượt f: không thể finalize sai.
        self.assertEqual(all_invariants(self.summary, rows=self.rows), [])

    def test_no_finalize_at_all(self) -> None:
        # Không đạt quorum, đúng theo README: phải chạy hết max_virtual_time mà không finalize.
        self.assertFalse(self.context.events("FINALIZE"))

    def test_silent_nodes_excluded_from_honest(self) -> None:
        for node in ("N6", "N7", "N8", "N9"):
            self.assertNotIn(node, self.summary["honest_nodes"])

    def test_safety_prefixes_true(self) -> None:
        self.assertTrue(self.summary["safety_prefixes"])

    def test_runs_to_max_virtual_time(self) -> None:
        self.assertGreaterEqual(self.summary["duration_ms"], 100000)


if __name__ == "__main__":
    unittest.main()
