"""
Công cụ quan sát trạng thái (show_state.py) của một tài khoản hoặc toàn bộ State
đã finalize của một Node.

Cách dùng từ dòng lệnh (Mục 1 & 10 README):
  python -m tests.tools.show_state --log logs/<file>.log --node 3 --account alice
  python -m tests.tools.show_state --log logs/<file>.log --node 3
"""

from __future__ import annotations

import argparse
import sys

from src.execution.state import State
from src.node.query import ChatQuery
from tests.tools.show_chat import normalize_node_id, reconstruct_node_from_log


def format_state_output(
    state_or_query: State | ChatQuery,
    node_id: str = "N0",
    account: str | None = None,
) -> str:
    """
    Định dạng dữ liệu trạng thái (State) của một tài khoản hoặc toàn bộ node để hiển thị.
    """
    norm_node = normalize_node_id(node_id)
    if isinstance(state_or_query, ChatQuery):
        state_obj = state_or_query.get_state()
        entries = state_or_query.get_state_entries(account=account)
    else:
        state_obj = state_or_query
        entries = (
            state_obj.get_account_entries(account)
            if account is not None
            else state_obj.to_dict()
        )

    header_scope = f"account={account}" if account is not None else "ALL"
    lines: list[str] = [
        f"=== STATE CỦA NODE {norm_node} ({header_scope}) | state_hash={str(state_obj.state_hash())[:12]}... ==="
    ]

    if account is not None:
        lines.append(f"applied_nonce({account}) = {state_obj.get_nonce(account)}")

    if not entries:
        lines.append("(State rỗng)")
        return "\n".join(lines)

    for key, val in entries.items():
        lines.append(f"  {key} = {val}")

    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    """Xây dựng bộ phân tích tham số dòng lệnh cho công cụ show_state."""
    parser = argparse.ArgumentParser(
        description="Hiển thị các mục State của một tài khoản hoặc toàn bộ State của một node."
    )
    parser.add_argument("--log", required=True, help="Đường dẫn tới file log (.log)")
    parser.add_argument("--node", default="0", help="ID của node cần xem (ví dụ: 3 hoặc N3)")
    parser.add_argument("--account", default=None, help="Tên tài khoản cần lọc (ví dụ: alice)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Hàm chạy chính của công cụ dòng lệnh tests.tools.show_state."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        _, _, query = reconstruct_node_from_log(args.log, node_id=args.node)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    output = format_state_output(
        state_or_query=query,
        node_id=normalize_node_id(args.node),
        account=args.account,
    )
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
