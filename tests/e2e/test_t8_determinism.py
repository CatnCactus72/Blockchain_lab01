"""E2E T8 (determinism): cùng seed chạy hai lần phải giống từng byte; seed khác phải khác."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers import run_case

DETERMINISM_CASES = ("t1_normal", "t7_byzantine_equivocate")


def _bytes(path: Path) -> bytes:
    return Path(path).read_bytes()


def _state_hashes(summary: dict) -> list[str]:
    return [node["state_hash"] for _, node in sorted(summary["nodes"].items())]


class TestT8Determinism(unittest.TestCase):
    def check_case(self, scenario: str) -> None:
        with tempfile.TemporaryDirectory(prefix="lab01_t8_") as tmp:
            first = run_case(scenario, out_dir=str(Path(tmp) / "a"), seed=42)
            second = run_case(scenario, out_dir=str(Path(tmp) / "b"), seed=42)
            bytes_a, bytes_b = _bytes(first.log_path), _bytes(second.log_path)
            self.assertEqual(
                bytes_a, bytes_b, f"{scenario}: cùng seed 42 phải cho log giống từng byte"
            )
            self.assertEqual(
                _state_hashes(first.summary), _state_hashes(second.summary),
                f"{scenario}: cùng seed phải cùng state hash cuối",
            )
            third = run_case(scenario, out_dir=str(Path(tmp) / "c"), seed=43)
            bytes_c = _bytes(third.log_path)
            self.assertNotEqual(
                bytes_a, bytes_c, f"{scenario}: seed khác phải cho log khác"
            )

    def test_t1_normal_deterministic(self) -> None:
        self.check_case("t1_normal")

    def test_t7_byzantine_deterministic(self) -> None:
        self.check_case("t7_byzantine_equivocate")

    def test_config_declares_t8_cases(self) -> None:
        # config/scenarios/t8_determinism.json khai báo đúng hai case trên.
        import json

        from tests.helpers import SCENARIO_DIR

        config = json.loads(
            (SCENARIO_DIR / "t8_determinism.json").read_text(encoding="utf-8")
        )
        self.assertIn("determinism_cases", config)
        cases = ",".join(str(case) for case in config["determinism_cases"])
        self.assertIn("t1_normal", cases)
        self.assertIn("t7_byzantine_equivocate", cases)


if __name__ == "__main__":
    unittest.main()
