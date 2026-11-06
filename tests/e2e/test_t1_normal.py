"""E2E T1 (kịch bản thường): mọi node đúng hội tụ, log sạch."""

from __future__ import annotations

import unittest

from tests.helpers import ScenarioTestCase
from tests.invariants import all_invariants


class TestT1Normal(ScenarioTestCase):
    scenario_name = "t1_normal"

    def test_invariants_hold(self) -> None:
        self.assertEqual(all_invariants(self.summary, rows=self.rows), [])

    def test_all_honest_nodes_converge(self) -> None:
        self.assertTrue(self.summary["converged"], "Các node trung thực phải có ensemble giống nhau")
        self.assertTrue(self.summary["safety_prefixes"])

    def test_every_node_finalizes_target_heights(self) -> None:
        for node_id, node_data in self.summary["nodes"].items():
            with self.subTest(node=node_id):
                heights = [block["height"] for block in node_data["chain"]]
                self.assertEqual(heights, list(range(1, 11)))
        hashes = [node["state_hash"] for node in self.summary["nodes"].values()]
        self.assertEqual(len(set(hashes)), 1)

    def test_no_rejects_in_normal_run(self) -> None:
        # Không có node lỗi nên không có REJECT nào được ghi.
        self.assertEqual(self.context.reject_reasons(), set())


if __name__ == "__main__":
    unittest.main()
