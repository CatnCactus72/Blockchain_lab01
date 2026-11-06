"""Bộ ghép kiểm thử: dựng kịch bản từ file config, chạy simulator trong test,
đọc và lọc log. Mọi test e2e gọi run_scenario() và parse_log() từ module này."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from src.main import run_scenario as _run_scenario

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
SCENARIO_DIR: Path = REPO_ROOT / "config" / "scenarios"

# Bật traceback đầy đủ khi một test hỏng để lý do thấy rõ trong run_all.
unittest.TestCase.longMessage = True


def scenario_path(name: str) -> Path:
    """'t1_normal' -> 'config/scenarios/t1_normal.json' trong repo."""
    return SCENARIO_DIR / f"{name}.json"


class RunContext:
    """Kết quả của một lần chạy scenario trong test: summary + log đã phân tách."""

    def __init__(self, summary: dict[str, Any], log_path: Path) -> None:
        self.summary = summary
        self.log_path = Path(log_path)
        self.rows: list[dict[str, Any]] = []
        from .invariants import parse_log

        self.rows = parse_log(log_path)

    # ----- lọc sự kiện -----

    def events(self, ev: str | None = None, reason: str | None = None,
               node: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
        result = []
        for row in self.rows:
            if ev is not None and row["ev"] != ev:
                continue
            if reason is not None and row["fields"].get("reason") != reason:
                continue
            if node is not None and row["node"] != node:
                continue
            if kind is not None and row["fields"].get("kind") != kind:
                continue
            result.append(row)
        return result

    def reject_reasons(self) -> set[str]:
        return {row["fields"]["reason"] for row in self.rows
                if row["ev"] == "REJECT" and "reason" in row["fields"]}

    def honest_chains(self) -> dict[str, list[dict[str, Any]]]:
        return {node: self.summary["nodes"][node]["chain"]
                for node in self.summary.get("honest_nodes", [])}


def run_case(name: str, out_dir: str | None = None, seed: int | None = None,
             faulty_ids: list[str] | None = None) -> RunContext:
    """
    Chạy một kịch bản trong repo với môi trường thật (blockchain) và phần tách log.
    out_dir mặc định dùng thư mục tạm; trả RunContext chứa summary + log.
    """
    if out_dir is None:
        out_dir = tempfile.mkdtemp(prefix="lab01_test_")
    summary, log_path = _run_scenario(
        str(scenario_path(name)), str(out_dir), seed, faulty_ids, smoke_env=False, root=str(REPO_ROOT)
    )
    return RunContext(summary, log_path)


def apply_per_account_nonce(context: RunContext, node: str) -> dict[str, list[int]]:
    """Map account -> các nonce đã TX_APPLIED (thứ tự log) của một node trung thực."""
    from .invariants import _parse_applied_details

    per_account: dict[str, list[int]] = {}
    for row in context.rows:
        if row["ev"] != "TX_APPLIED" or row["node"] != node:
            continue
        account, nonce, _ = _parse_applied_details(row)
        if account is not None and nonce is not None:
            per_account.setdefault(str(account), []).append(int(nonce))
    return per_account


def run_two_with_seed(name: str, seed: int | None = None) -> tuple[RunContext, RunContext]:
    """Chạy một kịch bản hai lần cùng seed (dùng cho kiểm tra determinism)."""
    with tempfile.TemporaryDirectory(prefix="lab01_det_") as tmp:
        first = run_case(name, out_dir=str(Path(tmp) / "a"), seed=seed)
        second = run_case(name, out_dir=str(Path(tmp) / "b"), seed=seed)
        return first, second


class ScenarioTestCase(unittest.TestCase):
    """
    Lớp nền cho test e2e: chạy một kịch bản đúng một lần trong setUpClass rồi
    các phương thức test cùng rọi chung kết quả (scenarios xác định nên chạy lại
    trong cùng class không sinh log khác nhau).
    """

    scenario_name: str = ""

    summary: dict[str, Any] = {}
    log_path: Path
    rows: list[dict[str, Any]] = []

    @classmethod
    def setUpClass(cls) -> None:
        if not cls.scenario_name:
            raise RuntimeError("ScenarioTestCase.subclass cần đặt scenario_name")
        context = run_case(cls.scenario_name)
        cls.summary = context.summary
        cls.log_path = context.log_path
        cls.rows = context.rows
        cls.context = context

    def run_case_fresh(self) -> RunContext:
        """Chạy lại kịch bản trực tiếp giúp tests cần nhiều lần chạy riêng."""
        return run_case(self.scenario_name)
