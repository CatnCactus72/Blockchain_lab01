"""
Công cụ giả lập ứng dụng đọc kênh chat (show_chat.py) từ dữ liệu đã finalize của một Node.

Cách dùng từ dòng lệnh (Mục 1 & 10 README):
  python -m tests.tools.show_chat --log logs/<file>.log --node 3 --last 2
  python -m tests.tools.show_chat --log logs/<file>.log --node 3 --height 7

Công cụ sử dụng giao diện đọc ChatQuery (get_latest(k), get_block(height)) trong src/node/query.py
và chỉ hiển thị các khối đã được FINALIZE theo đúng thứ tự sổ cái (height, sau đó vị trí tx trong khối).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from src.core.block import Block
from src.core.header import DEFAULT_CHAIN_ID, Header
from src.core.transaction import Transaction
from src.core.vote import CommitCertificate, PRECOMMIT, Vote
from src.crypto.hashing import state_hash as compute_state_hash, tx_root as compute_tx_root
from src.execution.state import State
from src.node.ledger import Ledger
from src.node.query import ChatQuery


def normalize_node_id(node_arg: str | int) -> str:
    """Chuẩn hóa tham số node (ví dụ '3' hoặc 'N3') về dạng 'N3'."""
    s = str(node_arg).strip()
    if s.isdigit():
        return f"N{s}"
    if s.upper().startswith("N") and s[1:].isdigit():
        return f"N{s[1:]}"
    return s


def parse_log_line(line: str) -> dict[str, str] | None:
    """
    Phân tích một dòng log chuẩn dạng:
    '00:07:410 seq=00902 node=N3 ev=FINALIZE h=5 r=1 hash=9d41.. state=c0a7..'
    Hỗ trợ cả giá trị trong ngoặc kép lẫn giá trị chứa khoảng trắng (như nội dung
    tin nhắn tiếng Việt trong details=... hoặc value=...) cho tới trường key= kế tiếp.
    Trả về dict các trường hoặc None nếu dòng trống/không hợp lệ.
    """
    stripped = line.strip()
    if not stripped:
        return None

    parts = stripped.split(" ", 1)
    if not parts:
        return None

    result: dict[str, str] = {"time": parts[0]}
    if len(parts) == 1:
        return result

    rest = parts[1]
    key_pattern = re.compile(r"(?:^|\s+)([A-Za-z_][A-Za-z0-9_]*)=")
    matches = list(key_pattern.finditer(rest))
    for i, match in enumerate(matches):
        k = match.group(1)
        val_start = match.end()
        val_end = matches[i + 1].start() if i + 1 < len(matches) else len(rest)
        v = rest[val_start:val_end].strip()
        if len(v) >= 2 and ((v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'"))):
            v = v[1:-1]
        result[k] = v
    return result


def _extract_tx_from_event(fields: dict[str, str]) -> Transaction | None:
    """Trích xuất đối tượng Transaction từ sự kiện log TX_APPLIED."""
    account = fields.get("account", "")
    nonce_str = fields.get("nonce", "")
    key = fields.get("key", "")
    value = fields.get("value", fields.get("text", fields.get("msg_text", "")))
    details = fields.get("details", "")

    if details:
        # Thử giải mã nếu details là chuỗi JSON hoặc dạng key=value
        if details.startswith("{") and details.endswith("}"):
            try:
                obj = json.loads(details)
                account = account or str(obj.get("account", ""))
                if not nonce_str and "nonce" in obj:
                    nonce_str = str(obj["nonce"])
                key = key or str(obj.get("key", ""))
                value = value or str(obj.get("value", obj.get("text", "")))
            except ValueError:
                pass
        elif "=" in details and not value:
            k_part, v_part = details.split("=", 1)
            if "/chat/" in k_part and not key:
                key = k_part.strip()
                value = v_part.strip().strip('"')
            else:
                value = details
        elif not value:
            value = details

    if key and "/chat/" in key and (not account or not nonce_str):
        seg = key.split("/")
        if len(seg) == 3 and seg[1] == "chat":
            account = account or seg[0]
            nonce_str = nonce_str or seg[2]

    if account and nonce_str:
        try:
            nonce = int(nonce_str)
        except ValueError:
            nonce = 1
        if not key:
            key = f"{account}/chat/{nonce}"
        return Transaction(account=account, nonce=nonce, key=key, value=value)

    return None


def reconstruct_node_from_log(
    log_path: str | Path,
    node_id: str | int = "N0",
) -> tuple[Ledger, State, ChatQuery]:
    """
    Đọc file log mô phỏng và dựng lại Ledger (chỉ gồm các khối đã FINALIZE)
    cùng State tương ứng của một node cụ thể, trả về (Ledger, State, ChatQuery).
    """
    target_node = normalize_node_id(node_id)
    path = Path(log_path)
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file log: {path}")

    # Lưu thông tin FINALIZE của target_node theo height: h -> dict thông tin
    finalized_by_height: dict[int, dict[str, Any]] = {}
    # Lưu các giao dịch TX_APPLIED của target_node theo height: h -> list[Transaction]
    node_txs_by_height: dict[int, list[Transaction]] = {}
    # Dự phòng: lưu TX_APPLIED trên toàn mạng theo height nếu node chỉ ghi FINALIZE
    global_txs_by_height: dict[int, list[Transaction]] = {}
    seen_global_tx_ids: dict[int, set[str]] = {}

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            parsed = parse_log_line(line)
            if not parsed:
                continue

            ev = parsed.get("ev", "")
            node = parsed.get("node", "")
            h_str = parsed.get("h", "-")
            try:
                height = int(h_str)
            except ValueError:
                height = -1

            if ev == "FINALIZE" and node == target_node and height >= 1:
                finalized_by_height[height] = parsed

            elif ev == "TX_APPLIED" and height >= 1:
                tx = _extract_tx_from_event(parsed)
                if tx is not None:
                    if node == target_node:
                        node_txs_by_height.setdefault(height, []).append(tx)
                    tid = str(tx.tx_id())
                    if tid not in seen_global_tx_ids.setdefault(height, set()):
                        seen_global_tx_ids[height].add(tid)
                        global_txs_by_height.setdefault(height, []).append(tx)

    # Khởi tạo Ledger (không truyền validator_pubkeys để tái tạo từ log) và State
    ledger = Ledger(chain_id=DEFAULT_CHAIN_ID, validator_pubkeys=None, quorum=1)
    state = State()

    for h in sorted(finalized_by_height.keys()):
        txs = node_txs_by_height.get(h, global_txs_by_height.get(h, []))
        for tx in txs:
            state.set(tx.key, tx.value, account=tx.account, nonce=tx.nonce)

        fin_info = finalized_by_height[h]
        parent_blk = ledger.latest()
        header = Header(
            chain_id=DEFAULT_CHAIN_ID,
            height=h,
            parent_hash=str(parent_blk.block_hash()),
            tx_root=str(compute_tx_root(txs)),
            state_hash=str(compute_state_hash(state.data)),
            proposer_id=fin_info.get("origin", target_node),
            timestamp=h * 1000,
        )
        block = Block(header=header, transactions=list(txs))
        blk_hash = str(block.block_hash())
        dummy_vote = Vote(
            height=h,
            round=int(fin_info.get("r", 0)) if fin_info.get("r", "0").isdigit() else 0,
            phase=PRECOMMIT,
            block_hash=blk_hash,
            validator_id=target_node,
        )
        cert = CommitCertificate(
            height=h,
            block_hash=blk_hash,
            votes=[dummy_vote],
            round=dummy_vote.round,
        )
        ledger.append(block, cert, validator_pubkeys=None, quorum=1)

    query = ChatQuery(ledger=ledger, state=state)
    return ledger, state, query


def format_chat_output(
    query: ChatQuery,
    node_id: str = "N0",
    last: int | None = None,
    height: int | None = None,
) -> str:
    """
    Định dạng nội dung kênh chat từ giao diện đọc ChatQuery:
    - Nếu truyền height: gọi query.get_block(height).
    - Nếu truyền last: gọi query.get_latest(last).
    - Nếu không truyền cả hai: lấy toàn bộ các khối đã finalize (từ height 1).
    """
    norm_node = normalize_node_id(node_id)
    if height is not None:
        blk = query.get_block(height)
        blocks = [blk] if blk is not None else []
    elif last is not None:
        blocks = query.get_latest(last)
    else:
        blocks = query.ledger.all_blocks(include_genesis=False)

    lines: list[str] = [
        f"=== KÊNH CHAT ĐÃ FINALIZE CỦA NODE {norm_node} (latest_height={query.ledger.latest_height}) ==="
    ]

    if not blocks:
        lines.append("(Không có block đã finalize nào thỏa mãn yêu cầu)")
        return "\n".join(lines)

    for blk in blocks:
        if blk is None:
            continue
        lines.append(
            f"[Block h={blk.height} hash={str(blk.block_hash())[:8]} txs={len(blk.transactions)}]"
        )
        if not blk.transactions:
            lines.append("  (Block rỗng - không có tin nhắn)")
        else:
            for idx, tx in enumerate(blk.transactions):
                lines.append(f"  #{idx + 1} [{tx.account}#nonce={tx.nonce}] {tx.key}: {tx.value}")

    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    """Xây dựng bộ phân tích tham số dòng lệnh cho công cụ show_chat."""
    parser = argparse.ArgumentParser(
        description="Hiển thị kênh chat đã finalize của một node từ file log."
    )
    parser.add_argument("--log", required=True, help="Đường dẫn tới file log (.log)")
    parser.add_argument("--node", default="0", help="ID của node cần xem (ví dụ: 3 hoặc N3)")
    parser.add_argument("--last", type=int, default=None, help="Lấy k block đã finalize mới nhất")
    parser.add_argument("--height", type=int, default=None, help="Lấy block đã finalize ở height chỉ định")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Hàm chạy chính của công cụ dòng lệnh tests.tools.show_chat."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        _, _, query = reconstruct_node_from_log(args.log, node_id=args.node)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    output = format_chat_output(
        query=query,
        node_id=normalize_node_id(args.node),
        last=args.last,
        height=args.height,
    )
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
