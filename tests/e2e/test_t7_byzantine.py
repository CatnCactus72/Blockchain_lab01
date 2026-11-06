"""E2E T7 (N2, N5, N8 equivocate): vote/proposal từ xung đột bị phát hiện, an toàn giữ vững."""

from __future__ import annotations

import unittest

from tests.helpers import ScenarioTestCase, apply_per_account_nonce
from tests.invariants import all_invariants


class TestT7Byzantine(ScenarioTestCase):
    scenario_name = "t7_byzantine_equivocate"

    def test_invariants_hold(self) -> None:
        self.assertEqual(all_invariants(self.summary, rows=self.rows), [])

    def test_equivocators_excluded_from_honest(self) -> None:
        for node in ("N2", "N5", "N8"):
            self.assertNotIn(node, self.summary["honest_nodes"])

    def test_conflicts_and_duplicates_detected(self) -> None:
        reasons = self.context.reject_reasons()
        self.assertIn("CONFLICTING_VOTE", reasons,
                      "Node đúng phải phát hiện vote mâu thuẫn của node equivocate")
        # Bản equivocation trùng nội dung từng cặp cũng có thể bị khử trùng ở tầng gossip
        # (DUP) nên DUPLICATE_VOTE không bắt buộc xuất hiện trong log, chỉ là khả năng.
        self.assertTrue(reasons <= {"CONFLICTING_VOTE", "DUPLICATE_VOTE", "FUTURE_HEIGHT", "BAD_SIGNATURE"})

    def test_conflict_rejects_from_byzantine_only(self) -> None:
        for row in self.context.events("REJECT", reason="CONFLICTING_VOTE"):
            self.assertIn(row["fields"].get("origin"), {"N2", "N5", "N8"})

    def test_converged(self) -> None:
        self.assertTrue(self.summary["converged"])


if __name__ == "__main__":
    unittest.main()
