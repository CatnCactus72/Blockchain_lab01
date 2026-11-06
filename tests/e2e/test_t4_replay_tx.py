"""E2E T4 (replay tx): alice gửi lại nonce cũ; N5 nhét tx đã áp dụng vào block."""

from __future__ import annotations

import json
import unittest

from tests.helpers import ScenarioTestCase, apply_per_account_nonce
from tests.invariants import _parse_applied_details, all_invariants


class TestT4ReplayTx(ScenarioTestCase):
    scenario_name = "t4_replay_tx"

    def test_invariants_hold(self) -> None:
        self.assertEqual(all_invariants(self.summary, rows=self.rows), [])

    def test_replayed_nonce_rejected(self) -> None:
        self.assertIn("REPLAYED_TX", self.context.reject_reasons())

    def test_alice_applied_nonce_each_once_in_order(self) -> None:
        nonces = apply_per_account_nonce(self.context, "N0")["alice"]
        self.assertEqual(nonces, sorted(nonces))
        self.assertEqual(len(nonces), len(set(nonces)))

    def test_converged(self) -> None:
        self.assertTrue(self.summary["converged"])


if __name__ == "__main__":
    unittest.main()
