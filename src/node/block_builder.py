"""
Dựng block và proposal cho proposer (Mục 4.1 README).

Quy trình dựng block hợp lệ:
1. Duyệt tx pool theo thứ tự đến, giữ đúng thứ tự nonce từng tài khoản,
   dừng ngay tại tx đầu tiên không còn vừa ngưỡng 4096 byte (TxPool.select_for_block).
2. Thực thi thử trên bản sao state cha để lấy state_hash (trial_execute_transactions).
3. Tính tx_root, đặt timestamp > timestamp khối cha, ký header (domain HEADER).
Pool trống thì tạo block rỗng.

Phần "block sai có chủ đích" (build_invalid_block) phục vụ node lỗi `invalid_block`
của kịch bản T4: bad_state_hash, oversized, replayed_tx.

Module không import net/sim; mọi thứ cần thiết được truyền vào qua tham số.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from src.core.block import MAX_BLOCK_BYTES, Block
from src.core.header import DEFAULT_CHAIN_ID, Header
from src.core.proposal import Proposal
from src.core.transaction import MAX_TEXT_CHARS, MAX_TX_BYTES, Transaction
from src.crypto.hashing import sha256_hex, tx_root as compute_tx_root
from src.execution.executor import trial_execute_transactions
from src.execution.state import State

# Các kiểu block sai (khớp faults/invalid_block.py)
MODE_BAD_STATE_HASH: str = "bad_state_hash"
MODE_OVERSIZED: str = "oversized"
MODE_REPLAYED_TX: str = "replayed_tx"
INVALID_MODES: tuple[str, ...] = (MODE_BAD_STATE_HASH, MODE_OVERSIZED, MODE_REPLAYED_TX)


@dataclass
class BuildResult:
    """Kết quả dựng block: block đã ký, state sau thực thi thử, tx được chọn và tx bị bỏ."""

    block: Block
    state: State
    included: list[Transaction] = field(default_factory=list)
    skipped: list[tuple[Transaction, str]] = field(default_factory=list)


def _header_of(parent: Any) -> Header:
    """Nhận Block hoặc Header, trả về Header."""
    return parent.header if hasattr(parent, "header") else parent


def next_timestamp(now_ms: int, parent: Any) -> int:
    """timestamp phải lớn hơn timestamp khối cha: max(thời gian ảo hiện tại, cha + 1)."""
    return max(int(now_ms), _header_of(parent).timestamp + 1)


def _assemble_block(
    *,
    chain_id: str,
    height: int,
    parent: Any,
    transactions: Sequence[Transaction],
    state_hash: str,
    proposer_id: str,
    private_key: bytes | str,
    timestamp: int,
) -> Block:
    """Dựng header (tx_root tính từ danh sách tx), ký, rồi ghép với body."""
    header = Header(
        chain_id=chain_id,
        height=height,
        parent_hash=str(parent.block_hash()),
        tx_root=str(compute_tx_root(list(transactions))),
        state_hash=state_hash,
        proposer_id=proposer_id,
        timestamp=timestamp,
    )
    header.sign(private_key)
    return Block(header=header, transactions=list(transactions))


def build_block(
    *,
    height: int,
    parent: Block | Header,
    parent_state: State,
    pool: Any,
    proposer_id: str,
    private_key: bytes | str,
    now_ms: int,
    account_pubkeys: Mapping[str, bytes | str] | None = None,
    chain_id: str = DEFAULT_CHAIN_ID,
    max_text_chars: int = MAX_TEXT_CHARS,
    max_tx_bytes: int = MAX_TX_BYTES,
    max_block_bytes: int = MAX_BLOCK_BYTES,
) -> BuildResult:
    """
    Dựng một block hợp lệ ở `height` trên khối cha `parent` và state cha `parent_state`.
    `pool` cần có select_for_block(state, max_block_bytes) (TxPool).
    Không sửa pool lẫn parent_state; tx chỉ bị xóa khỏi pool khi block được finalize.
    """
    candidates = pool.select_for_block(parent_state, max_block_bytes=max_block_bytes)
    after_state, included, skipped = trial_execute_transactions(
        parent_state,
        candidates,
        account_pubkeys=account_pubkeys,
        chain_id=chain_id,
        max_text_chars=max_text_chars,
        max_tx_bytes=max_tx_bytes,
        max_block_bytes=max_block_bytes,
    )
    block = _assemble_block(
        chain_id=chain_id,
        height=height,
        parent=parent,
        transactions=included,
        state_hash=str(after_state.state_hash()),
        proposer_id=proposer_id,
        private_key=private_key,
        timestamp=next_timestamp(now_ms, parent),
    )
    return BuildResult(block=block, state=after_state, included=included, skipped=skipped)


def build_invalid_block(
    *,
    mode: str,
    height: int,
    parent: Block | Header,
    parent_state: State,
    pool: Any,
    proposer_id: str,
    private_key: bytes | str,
    now_ms: int,
    account_pubkeys: Mapping[str, bytes | str] | None = None,
    chain_id: str = DEFAULT_CHAIN_ID,
    max_text_chars: int = MAX_TEXT_CHARS,
    max_tx_bytes: int = MAX_TX_BYTES,
    max_block_bytes: int = MAX_BLOCK_BYTES,
    applied_txs: Sequence[Transaction] = (),
) -> Block | None:
    """
    Dựng block SAI có chủ đích nhưng vẫn ký header đúng (node lỗi vẫn ký bằng khóa của mình):
    - bad_state_hash: body hợp lệ, state_hash trong header bị thay bằng giá trị bịa
      -> node đúng từ chối BAD_STATE_HASH.
    - oversized: nhồi thêm tx cho tổng kích thước > max_block_bytes (tx_root khớp)
      -> node đúng từ chối BLOCK_TOO_LARGE.
    - replayed_tx: đặt một tx ĐÃ áp dụng (nonce <= nonce đã áp dụng) lên đầu body
      -> node đúng từ chối REPLAYED_TX.
    `applied_txs` là các tx đã finalize (lấy từ ledger) để dùng làm nguyên liệu.
    Trả None nếu không đủ nguyên liệu để tạo lỗi theo mode (khi đó caller nên dựng block đúng).
    """
    if mode not in INVALID_MODES:
        raise ValueError(f"mode block sai không hỗ trợ: {mode}")

    base = build_block(
        height=height,
        parent=parent,
        parent_state=parent_state,
        pool=pool,
        proposer_id=proposer_id,
        private_key=private_key,
        now_ms=now_ms,
        account_pubkeys=account_pubkeys,
        chain_id=chain_id,
        max_text_chars=max_text_chars,
        max_tx_bytes=max_tx_bytes,
        max_block_bytes=max_block_bytes,
    )
    timestamp = base.block.timestamp
    valid_state_hash = str(base.state.state_hash())

    def assemble(txs: Sequence[Transaction], state_hash: str) -> Block:
        return _assemble_block(
            chain_id=chain_id,
            height=height,
            parent=parent,
            transactions=txs,
            state_hash=state_hash,
            proposer_id=proposer_id,
            private_key=private_key,
            timestamp=timestamp,
        )

    if mode == MODE_BAD_STATE_HASH:
        fake_hash = str(sha256_hex("BAD_STATE_HASH", height, proposer_id))
        return assemble(base.included, fake_hash)

    if mode == MODE_REPLAYED_TX:
        replayable = [
            tx for tx in applied_txs if tx.nonce <= parent_state.get_nonce(tx.account)
        ]
        if not replayable:
            return None
        txs: list[Transaction] = [replayable[-1]]
        total = txs[0].byte_size()
        for tx in base.included:
            if total + tx.byte_size() <= max_block_bytes:
                txs.append(tx)
                total += tx.byte_size()
        return assemble(txs, valid_state_hash)

    # MODE_OVERSIZED
    source = list(base.included) + list(applied_txs)
    if not source:
        return None
    txs = list(base.included)
    total = sum(tx.byte_size() for tx in txs)
    index = 0
    while total <= max_block_bytes:
        tx = source[index % len(source)]
        txs.append(tx)
        total += tx.byte_size()
        index += 1
    return assemble(txs, valid_state_hash)


def make_proposal(
    block_or_header: Block | Header,
    *,
    round_num: int,
    pol_round: int,
    proposer_id: str,
    private_key: bytes | str,
    chain_id: str = DEFAULT_CHAIN_ID,
) -> Proposal:
    """
    Tạo và ký PROPOSAL (domain PROPOSAL) của proposer ở round hiện tại.
    - Block mới: pol_round = -1.
    - Đề xuất lại block đã khóa/đã thấy đủ prevote: truyền header gốc (giữ chữ ký người tạo)
      và pol_round = round đã thấy quorum prevote (phải nhỏ hơn round_num).
    """
    if pol_round < -1 or (pol_round >= 0 and pol_round >= round_num):
        raise ValueError("pol_round phải là -1 hoặc nhỏ hơn round hiện tại")
    header = deepcopy(block_or_header.header if hasattr(block_or_header, "header") else block_or_header)
    proposal = Proposal(
        height=header.height,
        round=round_num,
        block_hash=str(header.block_hash()),
        pol_round=pol_round,
        header=header,
        proposer_id=proposer_id,
    )
    proposal.sign(private_key, chain_id, proposer_id)
    return proposal