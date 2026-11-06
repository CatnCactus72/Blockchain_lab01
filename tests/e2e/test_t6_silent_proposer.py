"""E2E T6 (N1 im lặng): height 1 round 0 thất bại, nhảy round rồi finalize."""

from __future__ import annotations

import unittest

from tests.helpers import ScenarioTestCase
from tests.invariants import all_invariants


class TestT6SilentProposer(ScenarioTestCase):
    scenario_name = "t6_silent_proposer"

    def test_invariants_hold(self) -> None:
        self.assertEqual(all_invariants(self.summary, rows=self.rows), [])

    def test_height1_round0_times_out_then_new_round(self) -> None:
        # NEW_ROUND (h=1, r=1) phải tồn tại: round 0 của N1 im lặng không thể finalize.
        next_rounds = [row for row in self.context.events("NEW_ROUND")
                       if row["h"] == "1" and row["fields"].get("r") == "1"]
        self.assertTrue(next_rounds, "Height 1 phải có NEW_ROUND r=1 sau khi proposer im lặng")
        first_next = next_rounds[0]
        # Một TIMEOUT ở height 1 xảy ra trước khi sang round 1.
        timeouts = self.context.events("TIMEOUT", node=None)  # mọi node
        early_timeouts = [row for row in timeouts
                          if row["h"] == "1" and row["time_ms"] < first_next["time_ms"]]
        self.assertTrue(early_timeouts,
                        f"Phải có TIMEOUT height 1 trước NEW_ROUND r=1 tại {first_next['time_ms']}")

    def test_height1_finalized_in_later_round(self) -> None:
        next_rounds = [row for row in self.context.events("NEW_ROUND")
                       if row["h"] == "1" and row["fields"].get("r") == "1"]
        self.assertTrue(next_rounds)
        first_next = next_rounds[0]
        finalizes = self.context.events("FINALIZE", node=None)
        height1 = [row for row in finalizes if row["h"] == "1"]
        self.assertTrue(height1)
        rounds = {row["fields"].get("r") for row in height1}
        self.assertNotIn("0", rounds, "Height 1 không thể finalize ở round 0 của proposer im lặng")
        self.assertLess(first_next["seq"], height1[0]["seq"])

    def test_converged(self) -> None:
        self.assertTrue(self.summary["converged"])


if __name__ == "__main__":
    unittest.main()
