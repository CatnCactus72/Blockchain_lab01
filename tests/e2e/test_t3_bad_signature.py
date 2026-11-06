"""E2E T3 (bad_signature): N3 luân phiên ba kiểu sai chữ ký; mạng vẫn hội tụ."""

from __future__ import annotations

import json
import unittest

from tests.helpers import ScenarioTestCase
from tests.invariants import all_invariants


class TestT3BadSignature(ScenarioTestCase):
    scenario_name = "t3_bad_signature"

    def test_invariants_hold(self) -> None:
        self.assertEqual(all_invariants(self.summary, rows=self.rows), [])

    def test_three_reject_kinds_observed(self) -> None:
        answered = {row["fields"].get("reason") for row in self.context.events("REJECT")}
        # Ba kiểu kiểm tra của T3 chỉ sinh hai mã lý do hợp lệ: khóa giả và ký sai domain.
        self.assertIn("BAD_SIGNATURE", answered)
        self.assertIn("WRONG_DOMAIN", answered)
        self.assertLessEqual(answered, {"BAD_SIGNATURE", "WRONG_DOMAIN"})

    def test_applied_nonce_per_account_ordered(self) -> None:
        from tests.helpers import apply_per_account_nonce
        for node in self.summary["honest_nodes"]:
            for account, nonces in apply_per_account_nonce(self.context, node).items():
                self.assertEqual(nonces, sorted(nonces), msg=f"{node}/{account}")

    def test_converged(self) -> None:
        self.assertTrue(self.summary["converged"])


if __name__ == "__main__":
    unittest.main()
