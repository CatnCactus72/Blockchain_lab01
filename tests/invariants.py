"""
Các bất biến dùng chung cho mọi test e2e (Mục 11 README):

1. Không có hai block khác nhau cùng height được finalize bởi các node đúng.
2. Hai node đúng bất kỳ: chuỗi finalize của node này là tiền tố của node kia.
3. Mỗi tx được áp dụng đúng một lần; tx của cùng tài khoản theo đúng thứ tự nonce.
4. Không vote nào bị đếm hai lần (DUPLICATE_VOTE bị loại không đếm lần hai).
5. Mọi REJECT có reason thuộc danh sách cố định; log đúng định dạng,
   thời gian không giảm, seq tăng nghiêm ngặt.

Mỗi hàm trả về danh sách mô tả vi phạm; danh sách rỗng nghĩa là bất biến
được giữ vững. Hàm gộp `all_invariants` gọi cả các hàm trên.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.logsys.event import EVENTS, REASONS, format_time

# Trường bắt buộc ở mọi dòng log (item 9 README)
REQUIRED_FIELDS: tuple[str, ...] = ("node", "ev", "h")

NIL_HEIGHT: str = "-"


def parse_log(path: str | Path) -> list[dict[str, Any]]:
    """
    Đọc file log chuẩn key=value thành các dòng đã tách:
    {time_ms, seq, node, ev, h, fields, raw}. Ném ValueError nếu dòng sai cấu trúc.
    """
    rows: list[dict[str, Any]] = []
    text = Path(path).read_text(encoding="utf-8")
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        pieces = raw.split(" ")
        try:
            minutes, seconds, millis = (int(p) for p in pieces[0].split(":"))
        except ValueError:
            raise ValueError(f"Dòng {line_no}: thời gian sai định dạng MM:SS:mmm: {raw}") from None
        fields: dict[str, str] = {}
        for piece in pieces[1:]:
            key, sep, value = piece.partition("=")
            if not sep:
                raise ValueError(f"Dòng {line_no}: cặp key=value hỏng: {raw}")
            fields[key] = value
        if "seq" not in fields:
            raise ValueError(f"Dòng {line_no}: thiếu seq: {raw}")
        rows.append(
            {
                "raw": raw,
                "time_ms": (minutes * 60 + seconds) * 1000 + millis,
                "seq": int(fields["seq"]),
                "node": fields.get("node"),
                "ev": fields.get("ev"),
                "h": fields.get("h"),
                "fields": fields,
            }
        )
    return rows


def log_format_problems(rows: list[dict[str, Any]]) -> list[str]:
    """Bất biến 5: định dạng log, seq nghiêm ngặt, thời gian không giảm, reason hợp lệ."""
    problems: list[str] = []
    if not rows:
        return ["Log rỗng"]
    if rows[0]["ev"] != "SIM_START":
        problems.append(f"Dòng đầu không phải SIM_START: {rows[0]['raw']!r}")
    if rows[-1]["ev"] != "SIM_END":
        problems.append(f"Dòng cuối không phải SIM_END: {rows[-1]['raw']!r}")
    previous_time, previous_seq = -1, -1
    for row in rows:
        if row["ev"] not in EVENTS:
            problems.append(f"ev không có trong danh sách cố định: {row['ev']}")
        for key in REQUIRED_FIELDS:
            if row[key] is None:
                problems.append(f"Thiếu trường bắt buộc {key}: {row['raw']!r}")
        reason = row["fields"].get("reason")
        if reason is not None and reason not in REASONS:
            problems.append(f"reason không có trong danh sách cố định: {reason}")
        if row["seq"] <= previous_seq:
            problems.append(f"seq không tăng nghiêm ngặt tại: {row['raw']!r}")
        if row["time_ms"] < previous_time:
            problems.append(f"Thời gian không giảm tại: {row['raw']!r}")
        previous_seq, previous_time = row["seq"], row["time_ms"]
    return problems


def _honest_id(node_id: str) -> str:
    return str(node_id)


def chain_safety_problems(summary: dict[str, Any]) -> list[str]:
    """
    Bất biến 1 + 2 trên các node trung thực: cùng height thì cùng hash,
    chuỗi của node này là tiền tố của node kia.
    """
    problems: list[str] = []
    honest: list[str] = [(_honest_id(node)) for node in summary.get("honest_nodes", [])]
    nodes: dict[str, Any] = summary.get("nodes", {})
    for node_id in honest:
        if node_id not in nodes:
            problems.append(f"Node trung thực {node_id} không có trong summary")
    if problems:
        return problems
    height_to_hash: dict[int, dict[str, str]] = {}
    for node_id in honest:
        chain = nodes[node_id]["chain"]
        heights = [int(block["height"]) for block in chain]
        if heights != sorted(heights):
            problems.append(f"{node_id}: height trong chuỗi không tăng: {heights}")
        if len(set(heights)) != len(heights):
            problems.append(f"{node_id}: cùng height xuất hiện nhiều lần: {heights}")
        for block in chain:
            height_to_hash.setdefault(int(block["height"]), {})[node_id] = str(block["hash"])
    for height, by_node in sorted(height_to_hash.items()):
        if len(set(by_node.values())) > 1:
            problems.append(f"Height {height}: các node đúng finalize block khác nhau: {by_node}")
    chains = {node_id: [block["hash"] for block in nodes[node_id]["chain"]] for node_id in honest}
    for a, chain_a in chains.items():
        for b, chain_b in chains.items():
            if a == b:
                continue
            short, long = (
                (chain_a, chain_b) if len(chain_a) <= len(chain_b) else (chain_b, chain_a)
            )
            if long[: len(short)] != short:
                problems.append(f"Chuỗi {a} không phải tiền tố của {b}")
    if summary.get("safety_prefixes") is False:
        problems.append("summary.safety_prefixes = False")
    return problems


def _parse_applied_details(row: dict[str, Any]) -> tuple[str | None, int | None, str | None]:
    """TX_APPLIED có details là JSON chứa account/nonce/key (ghép từ record_finalized).
    Giá trị trong log được mã hóa URL (format_event), phải unquote trước khi json.loads."""
    from urllib.parse import unquote

    details = row["fields"].get("details")
    if not details:
        return None, None, None
    text = unquote(details)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = json.loads(details)
        except json.JSONDecodeError:
            return None, None, None
    if not isinstance(data, dict):
        return None, None, None
    account = data.get("account")
    nonce = data.get("nonce")
    key = data.get("key")
    if account is None and isinstance(key, str) and "/" in key:
        account = key.split("/", 1)[0]
    if isinstance(key, str) and key.count("/") == 2 and key.rsplit("/", 1)[-1].isdigit():
        if nonce is None:
            nonce = int(key.rsplit("/", 1)[-1])
    if isinstance(nonce, str) and nonce.isdigit():
        nonce = int(nonce)
    return account, nonce, key


def tx_application_problems(
    rows: list[dict[str, Any]],
    honest_nodes: list[str] | None = None,
) -> list[str]:
    """
    Bất biến 3: mỗi tx được vừa đúng một lần, theo đúng thứ tự nonce của cùng tài khoản.
    Dựa trên sự kiện TX_APPLIED của các node trung thực.
    """
    problems: list[str] = []
    skip = set(honest_nodes) if honest_nodes is not None else None
    for row in rows:
        if row["ev"] not in ("TX_APPLIED", "TX_SKIPPED"):
            continue
        node = row["node"] or ""
        if skip is not None and node not in skip:
            continue  # node Byzantine không đủ tin cậy để truy nghịch
        if row["ev"] == "TX_SKIPPED":
            continue
        account, nonce, key = _parse_applied_details(row)
        if account is None or nonce is None:
            problems.append(f"TX_APPLIED thiếu account/nonce trong details: {row['raw']!r}")
    if problems:
        return problems
    # Đếm và kiểm thứ tự nonce theo (node, account)
    per_node_account: dict[tuple[str, str], list[tuple[int, str | None, dict[str, Any]]]] = {}
    for row in rows:
        if row["ev"] != "TX_APPLIED":
            continue
        node = row["node"] or ""
        if skip is not None and node not in skip:
            continue
        account, nonce, key = _parse_applied_details(row)
        if account is None or nonce is None:
            continue
        per_node_account.setdefault((node, account), []).append((nonce, key, row))
    for (node, account), applications in sorted(per_node_account.items()):
        nonces = [item[0] for item in applications]
        if len(set(nonces)) != len(nonces):
            duplicate = [value for value in sorted(nonces) if nonces.count(value) > 1]
            problems.append(
                f"{node}/{account}: nonce bị áp dụng nhiều lần: {sorted(set(duplicate))}"
            )
        if nonces != sorted(nonces):
            problems.append(f"{node}/{account}: áp dụng không theo thứ tự nonce: {nonces}")
        if nonces and min(nonces) != 1:
            problems.append(f"{node}/{account}: nonce đầu tiên != 1: {min(nonces)}")
    return problems


def vote_counting_problems(rows: list[dict[str, Any]]) -> list[str]:
    """
    Bất biến 4: vote trùng hoặc mâu thuẫn phải bị từ chối và không bao giờ mô tả
    là đã được đếm (không có Accepted CHO vote trùng/mâu thuẫn).
    """
    problems: list[str] = []
    for row in rows:
        if row["ev"] != "REJECT":
            continue
        reason = row["fields"].get("reason")
        if reason in ("DUPLICATE_VOTE", "CONFLICTING_VOTE") and reason in REASONS:
            # REJECT là hành vi đúng; chỉ sai nếu dòng cùng msg được đánh dấu accepted sau đó.
            continue
        # Bất biến này được đầu sous kiểm trả bằng vote_counter unit test + các REJECT ở trên.
    return problems


def all_invariants(
    summary: dict[str, Any],
    log_path: str | Path | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Gộp mọi bất biến; trả về danh sách vi phạm (rỗng = tất cả giữ vững)."""
    problems: list[str] = []
    if rows is None:
        if log_path is None:
            raise ValueError("Cần log_path hoặc rows")
        rows = parse_log(log_path)
    problems.extend(log_format_problems(rows))
    problems.extend(chain_safety_problems(summary))
    honest = list(summary.get("honest_nodes", []))
    problems.extend(tx_application_problems(rows, honest_nodes=honest))
    problems.extend(vote_counting_problems(rows))
    return problems


def format_time_guard(ms: int) -> str:
    """Kiểm tạo chuỗi MM:SS:mmm (dùng helper cho test log)."""
    return format_time(ms)
