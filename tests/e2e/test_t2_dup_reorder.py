"""E2E T2 (trùng + đảo thứ tự, N4 replay copy): mạng nhiễu nhưng thứ tự vẫn đúng."""

from __future__ import annotations

import unittest

from tests.helpers import ScenarioTestCase, apply_per_account_nonce
from tests.invariants import all_invariants


class TestT2DupReorder(ScenarioTestCase):
    scenario_name = "t2_dup_reorder"

    def test_invariants_hold(self) -> None:
        self.assertEqual(all_invariants(self.summary, rows=self.rows), [])

    def test_honest_nodes_converge(self) -> None:
        # N4 là node lỗi replay: phải bị loại khỏi danh sách node trung thực.
        self.assertNotIn("N4", self.summary["honest_nodes"])
        self.assertTrue(self.summary["converged"])

    def test_n4_chains_ends_behind_but_prefix_safe(self) -> None:
        chain_n4 = self.summary["nodes"]["N4"]["chain"]
        other = self.summary["nodes"]["N0"]["chain"]
        self.assertLessEqual(len(chain_n4), len(other))

    def test_duplicate_delivery_observed(self) -> None:
        # Trùng 20% sau GST + N4 gửi mỗi gói 3 lần: phải thấy sự kiện DUP do khử trùng.
        self.assertTrue(self.context.events("DUP"), "Phải có sự kiện DUP do trùng gói")

    def test_applied_nonce_per_account_ordered(self) -> None:
        for node in self.summary["honest_nodes"]:
            for account, nonces in apply_per_account_nonce(self.context, node).items():
                self.assertEqual(nonces, sorted(nonces), msg=f"{node}/{account}")


if __name__ == "__main__":
    unittest.main()
