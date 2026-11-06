"""E2E X1 (chế độ bùng nổ): 100 tin trong 1 s dồn qua nhiều block, không quá khổ."""

from __future__ import annotations

import unittest

from tests.helpers import ScenarioTestCase, apply_per_account_nonce
from tests.invariants import all_invariants


class TestX1Burst(ScenarioTestCase):
    scenario_name = "x1_burst_blocksize"

    def test_invariants_hold(self) -> None:
        self.assertEqual(all_invariants(self.summary, rows=self.rows), [])

    def test_converged(self) -> None:
        self.assertTrue(self.summary["converged"])

    def test_no_block_too_large(self) -> None:
        self.assertNotIn("BLOCK_TOO_LARGE", self.context.reject_reasons())

    def test_many_messages_applied(self) -> None:
        # Bùng nổ phải dồn qua nhiều block; dùng tổng số TX_APPLIED thấy được.
        applied = [row for row in self.rows if row["ev"] == "TX_APPLIED"]
        self.assertGreaterEqual(len(applied), 100)

    def test_per_account_nonces_strictly_ordered(self) -> None:
        for node in self.summary["honest_nodes"]:
            for account, nonces in apply_per_account_nonce(self.context, node).items():
                self.assertEqual(nonces, sorted(nonces), msg=f"{node}/{account}")


if __name__ == "__main__":
    unittest.main()
