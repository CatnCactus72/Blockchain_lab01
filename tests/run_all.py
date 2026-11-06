"""Chạy toàn bộ kiểm thử theo Mục 11 README:

    python -m tests.run_all

Thứ tự: unit test, e2e T1..T8, rồi hai kịch bản phụ X1, X2 (báo riêng).
Mỗi test in PASS / FAIL / ERROR / SKIP (kèm lý do); mã thoát khác 0 nếu có test hỏng.

Mỗi test chạy qua unittest.TestSuite để setUpClass (chạy scenario một lần) hoạt động đúng.
"""

from __future__ import annotations

import unittest

UNIT_MODULES = (
    "tests.unit.test_crypto",
    "tests.unit.test_state",
    "tests.unit.test_vote_counter",
    "tests.unit.test_block_validation",
    "tests.unit.test_limits",
    # Hai bộ kiểm ghép có sẵn của nhóm (không thuộc danh sách README nhưng đang dùng).
    "tests.unit.test_part1_environment",
    "tests.unit.test_part1_part2_integration",
)

E2E_MODULES = (
    "tests.e2e.test_t1_normal",
    "tests.e2e.test_t2_dup_reorder",
    "tests.e2e.test_t3_bad_signature",
    "tests.e2e.test_t4_replay_tx",
    "tests.e2e.test_t5_pre_gst",
    "tests.e2e.test_t6_silent_proposer",
    "tests.e2e.test_t7_byzantine",
    "tests.e2e.test_t8_determinism",
)

EXTRA_MODULES = (
    "tests.e2e.test_x1_burst",
    "tests.e2e.test_x2_beyond_f",
)


def _label(test) -> str:
    return test.id().replace("tests.e2e.", "").replace("tests.unit.", "")


def _short_reason(err) -> str:
    lines = [line.strip() for line in err.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith(("AssertionError", "Error", "ValueError", "RuntimeError",
                            "KeyError", "AttributeError", "TypeError", "NotImplementedError")):
            return line
    return lines[-1] if lines else "(không có thông điệp)"


class ProgressResult(unittest.TestResult):
    """In PASS/FAIL với lý do ngắn ngay khi test kết thúc."""

    def _ok(self, test, tag="PASS", note=""):
        print(f"{tag} {_label(test)}{note}", flush=True)

    def addSuccess(self, test) -> None:
        super().addSuccess(test)
        self._ok(test)

    def addFailure(self, test, err) -> None:
        super().addFailure(test, err)
        base = self.failures[-1][1]
        print(f"FAIL {_label(test)} — {_short_reason(str(base))}", flush=True)

    def addError(self, test, err) -> None:
        super().addError(test, err)
        base = self.errors[-1][1]
        print(f"ERROR {_label(test)} — {_short_reason(str(base))}", flush=True)

    def addSkip(self, test, reason) -> None:
        super().addSkip(test, reason)
        self._ok(test, tag="SKIP", note=f" — {reason}")

    def was_successful(self) -> bool:
        return not self.errors and not self.failures


def run_modules(name: str, module_names: tuple[str, ...]) -> bool:
    print("=" * 72, flush=True)
    print(name, flush=True)
    print("=" * 72, flush=True)
    all_ok = True
    loader = unittest.defaultTestLoader
    for module_name in module_names:
        module = __import__(module_name, fromlist=["__doc__"])
        suite = loader.loadTestsFromModule(module)
        result = ProgressResult()
        runner_desc = f"[{module_name.split('.')[-1]}]"
        print(f"--- {runner_desc} ---", flush=True)
        suite.run(result)
        if not result.was_successful():
            all_ok = False
    return all_ok


def main(argv=None) -> int:
    unit_ok = run_modules("UNIT TEST", UNIT_MODULES)
    e2e_ok = run_modules("E2E T1 - T8", E2E_MODULES)
    extra_ok = run_modules("E2E PHỤ X1, X2 (báo riêng)", EXTRA_MODULES)
    ok = unit_ok and e2e_ok and extra_ok
    print("=" * 72, flush=True)
    print("KẾT QUẢ TỔNG:", "MỌI TEST PASS" if ok else "CÓ TEST HỎNG", flush=True)
    print("=" * 72, flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
