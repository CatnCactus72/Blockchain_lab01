"""
Các hàm kiểm tra tính hợp lệ của giao dịch (tx), phần đầu khối (header),
đề xuất (proposal), phần thân khối (body), toàn bộ khối (block), phiếu bầu (vote)
và chứng nhận cam kết (commit certificate).

Mỗi hàm trả về cặp (ok: bool, reason: str | None), trong đó reason thuộc danh sách
mã lý do từ chối cố định ở Mục 9 README.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from src.core.block import MAX_BLOCK_BYTES, Block
from src.core.header import DEFAULT_CHAIN_ID, Header
from src.core.proposal import Proposal
from src.core.transaction import (
    MAX_TEXT_CHARS,
    MAX_TX_BYTES,
    Transaction,
)
from src.core.vote import (
    DEFAULT_QUORUM,
    VALID_PHASES,
    CommitCertificate,
    Vote,
)
from src.crypto.hashing import tx_root as compute_tx_root
from src.execution.executor import apply_tx
from src.execution.state import State
from src.node.proposer import (
    DEFAULT_NUM_VALIDATORS,
    expected_proposer_id,
    is_expected_proposer,
)

# ============================================================================
# Danh sách cố định 21 mã lý do từ chối (Mục 9 README)
# ============================================================================
BAD_SIGNATURE: str = "BAD_SIGNATURE"
WRONG_DOMAIN: str = "WRONG_DOMAIN"
WRONG_CHAIN: str = "WRONG_CHAIN"
UNKNOWN_ACCOUNT: str = "UNKNOWN_ACCOUNT"
NOT_OWNER: str = "NOT_OWNER"
BAD_KEY: str = "BAD_KEY"
TX_TOO_LONG: str = "TX_TOO_LONG"
BAD_NONCE: str = "BAD_NONCE"
REPLAYED_TX: str = "REPLAYED_TX"
BAD_PARENT: str = "BAD_PARENT"
BAD_TX_ROOT: str = "BAD_TX_ROOT"
BAD_STATE_HASH: str = "BAD_STATE_HASH"
BAD_TIMESTAMP: str = "BAD_TIMESTAMP"
BLOCK_TOO_LARGE: str = "BLOCK_TOO_LARGE"
NOT_PROPOSER: str = "NOT_PROPOSER"
DUPLICATE_MSG: str = "DUPLICATE_MSG"
DUPLICATE_VOTE: str = "DUPLICATE_VOTE"
CONFLICTING_VOTE: str = "CONFLICTING_VOTE"
FUTURE_HEIGHT: str = "FUTURE_HEIGHT"
PEER_BLOCKED: str = "PEER_BLOCKED"
RATE_LIMIT: str = "RATE_LIMIT"

VALID_REASONS: tuple[str, ...] = (
    BAD_SIGNATURE,
    WRONG_DOMAIN,
    WRONG_CHAIN,
    UNKNOWN_ACCOUNT,
    NOT_OWNER,
    BAD_KEY,
    TX_TOO_LONG,
    BAD_NONCE,
    REPLAYED_TX,
    BAD_PARENT,
    BAD_TX_ROOT,
    BAD_STATE_HASH,
    BAD_TIMESTAMP,
    BLOCK_TOO_LARGE,
    NOT_PROPOSER,
    DUPLICATE_MSG,
    DUPLICATE_VOTE,
    CONFLICTING_VOTE,
    FUTURE_HEIGHT,
    PEER_BLOCKED,
    RATE_LIMIT,
)


def validate_tx(
    tx: Transaction,
    state: State | None = None,
    account_pubkeys: Mapping[str, bytes | str] | None = None,
    chain_id: str = DEFAULT_CHAIN_ID,
    max_text_chars: int = MAX_TEXT_CHARS,
    max_tx_bytes: int = MAX_TX_BYTES,
    check_nonce: bool = True,
    expected_nonce: int | None = None,
) -> tuple[bool, str | None]:
    """
    Kiểm tra tính hợp lệ của một giao dịch (tin nhắn chat) theo đúng thứ tự 5 bước ở Mục 3.1 README:
    1. account có trong sổ tài khoản (UNKNOWN_ACCOUNT).
    2. Chữ ký hợp lệ bằng khóa công khai của account (BAD_SIGNATURE, WRONG_DOMAIN).
    3. key bắt đầu bằng '<account>/' (NOT_OWNER) và đúng dạng '<account>/chat/<nonce>' (BAD_KEY).
    4. value không rỗng, tối đa 200 ký tự NFC và toàn bộ tx mã hóa tối đa 1024 byte (TX_TOO_LONG).
    5. nonce đúng bằng nonce_đã_áp_dụng + 1 (nhỏ hơn hoặc bằng là REPLAYED_TX, lớn hơn là BAD_NONCE).
    """
    # Bước 1 & 2: Kiểm tra sổ tài khoản và chữ ký
    if account_pubkeys is not None:
        if tx.account not in account_pubkeys:
            return False, UNKNOWN_ACCOUNT
        ok_sig, sig_reason = tx.verify_signature(account_pubkeys[tx.account], chain_id=chain_id)
        if not ok_sig:
            return False, sig_reason

    # Bước 3: Kiểm tra quyền sở hữu key và định dạng key
    ok_key, key_reason = tx.check_key_format()
    if not ok_key:
        return False, key_reason

    # Bước 4: Kiểm tra giới hạn số ký tự và kích thước byte
    ok_lim, lim_reason = tx.check_limits(
        max_text_chars=max_text_chars,
        max_tx_bytes=max_tx_bytes,
    )
    if not ok_lim:
        return False, lim_reason

    # Bước 5: Kiểm tra số thứ tự nonce chống phát lại (replay)
    if check_nonce:
        if expected_nonce is not None:
            target_nonce = expected_nonce
        elif state is not None:
            target_nonce = state.get_nonce(tx.account) + 1
        else:
            target_nonce = None

        if target_nonce is not None:
            if tx.nonce < target_nonce:
                return False, REPLAYED_TX
            if tx.nonce > target_nonce:
                return False, BAD_NONCE
        elif tx.nonce < 1:
            return False, REPLAYED_TX

    return True, None


def validate_header(
    header: Header,
    parent_header_or_block: Header | Block | None = None,
    validator_pubkeys: Mapping[str, bytes | str] | None = None,
    chain_id: str = DEFAULT_CHAIN_ID,
    expected_round: int | None = None,
    n: int = DEFAULT_NUM_VALIDATORS,
    validators: Sequence[str] | None = None,
) -> tuple[bool, str | None]:
    """
    Kiểm tra tính hợp lệ của Header khối theo Mục 3.3 & Mục 4 bước 2:
    1. chain_id khớp với chain_id cấu hình (WRONG_CHAIN).
    2. height == parent.height + 1 và parent_hash == parent.block_hash() (BAD_PARENT).
    3. proposer_id thuộc danh sách validator, chữ ký header hợp lệ trên domain HEADER
       (BAD_SIGNATURE, WRONG_DOMAIN), và đúng proposer của (height, expected_round)
       nếu truyền expected_round (NOT_PROPOSER).
    4. timestamp > parent.timestamp (BAD_TIMESTAMP).
    """
    # 1. Kiểm tra chain_id
    if header.chain_id != chain_id:
        return False, WRONG_CHAIN

    # 2. Kiểm tra liên kết khối cha (height và parent_hash)
    parent_header: Header | None = None
    if parent_header_or_block is not None:
        parent_header = (
            parent_header_or_block.header
            if hasattr(parent_header_or_block, "header")
            else parent_header_or_block  # type: ignore[assignment]
        )

    if parent_header is not None:
        if header.height != parent_header.height + 1:
            return False, BAD_PARENT
        if header.parent_hash != str(parent_header.block_hash()):
            return False, BAD_PARENT

    # 3. Kiểm tra proposer hợp lệ và chữ ký của người tạo khối trong Header
    if validator_pubkeys is not None and header.proposer_id not in validator_pubkeys:
        return False, NOT_PROPOSER

    if expected_round is not None:
        if not is_expected_proposer(
            header.proposer_id,
            header.height,
            expected_round,
            n=n,
            validators=validators,
        ):
            return False, NOT_PROPOSER

    if validator_pubkeys is not None:
        ok_sig, sig_reason = header.verify_signature(
            validator_pubkeys[header.proposer_id],
            expected_chain_id=chain_id,
        )
        if not ok_sig:
            return False, sig_reason

    # 4. Kiểm tra timestamp phải tăng nghiêm ngặt so với khối cha
    if parent_header is not None:
        if header.timestamp <= parent_header.timestamp:
            return False, BAD_TIMESTAMP
    elif header.timestamp < 0:
        return False, BAD_TIMESTAMP

    return True, None


def validate_proposal(
    proposal: Proposal,
    parent_header_or_block: Header | Block | None = None,
    validator_pubkeys: Mapping[str, bytes | str] | None = None,
    chain_id: str = DEFAULT_CHAIN_ID,
    sender_id: str | int | None = None,
    current_height: int | None = None,
    future_height_window: int = 5,
    n: int = DEFAULT_NUM_VALIDATORS,
    validators: Sequence[str] | None = None,
) -> tuple[bool, str | None]:
    """
    Kiểm tra tính hợp lệ của một thông điệp đề xuất (PROPOSAL) theo Mục 3.4 & Mục 4:
    1. Kiểm tra khoảng chiều cao tương lai [current_height, current_height + future_height_window]
       (ngoài khoảng trả về FUTURE_HEIGHT).
    2. Kiểm tra chain_id của header (WRONG_CHAIN).
    3. Kiểm tra proposer của round hiện tại (height, round) và chữ ký proposal_sig trên
       domain PROPOSAL (NOT_PROPOSER, BAD_SIGNATURE, WRONG_DOMAIN).
    4. Kiểm tra tính hợp lệ của proposal.header thông qua validate_header:
       - Nếu pol_round == -1 (block mới): header.proposer_id phải là proposer của round hiện tại.
       - Nếu pol_round >= 0 (đề xuất lại block đã khóa): header.proposer_id là một validator hợp lệ
         đã tạo block ở round trước.
    """
    if current_height is not None:
        if proposal.height > current_height + future_height_window:
            return False, FUTURE_HEIGHT

    if proposal.header.chain_id != chain_id:
        return False, WRONG_CHAIN

    if proposal.height != proposal.header.height:
        return False, BAD_PARENT

    ok_prop, prop_reason = proposal.verify_proposer_and_sig(
        validator_pubkeys=validator_pubkeys,
        chain_id=chain_id,
        sender_id=sender_id,
        n=n,
        validators=validators,
    )
    if not ok_prop:
        return False, prop_reason

    # Kiểm tra Header bên trong Proposal
    expected_header_round = proposal.round if proposal.pol_round == -1 else None
    return validate_header(
        header=proposal.header,
        parent_header_or_block=parent_header_or_block,
        validator_pubkeys=validator_pubkeys,
        chain_id=chain_id,
        expected_round=expected_header_round,
        n=n,
        validators=validators,
    )


def validate_body(
    header: Header,
    transactions: Sequence[Transaction],
    parent_state: State,
    account_pubkeys: Mapping[str, bytes | str] | None = None,
    chain_id: str = DEFAULT_CHAIN_ID,
    max_text_chars: int = MAX_TEXT_CHARS,
    max_tx_bytes: int = MAX_TX_BYTES,
    max_block_bytes: int = MAX_BLOCK_BYTES,
) -> tuple[bool, str | None]:
    """
    Kiểm tra phần thân khối (Body) đối chiếu với Header và trạng thái khối cha (Mục 4 bước 3):
    1. Kiểm tra tổng kích thước mã hóa của danh sách giao dịch <= 4096 byte (BLOCK_TOO_LARGE).
    2. Tính lại tx_root từ danh sách giao dịch và so sánh với header.tx_root (BAD_TX_ROOT).
    3. Thực thi tuần tự từng giao dịch trên bản sao của parent_state theo quy tắc Mục 3.1
       (trả về UNKNOWN_ACCOUNT, BAD_SIGNATURE, WRONG_DOMAIN, NOT_OWNER, BAD_KEY,
        TX_TOO_LONG, REPLAYED_TX, BAD_NONCE nếu có giao dịch bất kỳ không hợp lệ).
    4. Tính lại state_hash sau khi thực thi hết body và so sánh với header.state_hash (BAD_STATE_HASH).
    """
    tx_list = list(transactions)

    # 1. Kiểm tra kích thước tối đa của Body
    total_bytes = sum(tx.byte_size() for tx in tx_list)
    if total_bytes > max_block_bytes:
        return False, BLOCK_TOO_LARGE

    # 2. Tính lại và đối chiếu tx_root
    computed_root = str(compute_tx_root(tx_list))
    if header.tx_root != computed_root:
        return False, BAD_TX_ROOT

    # 3. Thực thi từng giao dịch trên bản sao của parent_state
    working_state = parent_state.clone()
    for tx in tx_list:
        ok_tx, tx_reason = apply_tx(
            working_state,
            tx,
            account_pubkeys=account_pubkeys,
            chain_id=chain_id,
            max_text_chars=max_text_chars,
            max_tx_bytes=max_tx_bytes,
            check_limits=True,
            dry_run=False,
        )
        if not ok_tx:
            return False, tx_reason

    # 4. Tính lại và đối chiếu state_hash
    computed_state_hash = str(working_state.state_hash())
    if header.state_hash != computed_state_hash:
        return False, BAD_STATE_HASH

    return True, None


def validate_block(
    block: Block,
    parent_block_or_header: Header | Block | None = None,
    parent_state: State | None = None,
    validator_pubkeys: Mapping[str, bytes | str] | None = None,
    account_pubkeys: Mapping[str, bytes | str] | None = None,
    chain_id: str = DEFAULT_CHAIN_ID,
    expected_round: int | None = None,
    max_text_chars: int = MAX_TEXT_CHARS,
    max_tx_bytes: int = MAX_TX_BYTES,
    max_block_bytes: int = MAX_BLOCK_BYTES,
    n: int = DEFAULT_NUM_VALIDATORS,
    validators: Sequence[str] | None = None,
) -> tuple[bool, str | None]:
    """
    Kiểm tra toàn diện một Block hoàn chỉnh (bao gồm cả Header và Body):
    1. Kiểm tra Header qua validate_header().
    2. Kiểm tra Body và thực thi lại trên bản sao của parent_state qua validate_body().
    """
    ok_header, header_reason = validate_header(
        header=block.header,
        parent_header_or_block=parent_block_or_header,
        validator_pubkeys=validator_pubkeys,
        chain_id=chain_id,
        expected_round=expected_round,
        n=n,
        validators=validators,
    )
    if not ok_header:
        return False, header_reason

    base_state = parent_state if parent_state is not None else State()
    return validate_body(
        header=block.header,
        transactions=block.transactions,
        parent_state=base_state,
        account_pubkeys=account_pubkeys,
        chain_id=chain_id,
        max_text_chars=max_text_chars,
        max_tx_bytes=max_tx_bytes,
        max_block_bytes=max_block_bytes,
    )


def validate_vote(
    vote: Vote,
    validator_pubkeys: Mapping[str, bytes | str] | None = None,
    chain_id: str = DEFAULT_CHAIN_ID,
    current_height: int | None = None,
    future_height_window: int = 5,
) -> tuple[bool, str | None]:
    """
    Kiểm tra tính hợp lệ của một phiếu bầu (Vote):
    1. Nếu truyền current_height: kiểm tra vote.height <= current_height + future_height_window
       (vượt quá trả về FUTURE_HEIGHT).
    2. Kiểm tra phase thuộc (PREVOTE, PRECOMMIT) và validator_id có trong sổ khóa validator.
    3. Xác minh chữ ký trên domain VOTE (phân biệt WRONG_DOMAIN và BAD_SIGNATURE).
    """
    if current_height is not None:
        if vote.height > current_height + future_height_window:
            return False, FUTURE_HEIGHT

    if vote.phase not in VALID_PHASES:
        return False, BAD_SIGNATURE

    if validator_pubkeys is not None:
        if vote.validator_id not in validator_pubkeys:
            return False, BAD_SIGNATURE
        return vote.verify_signature(validator_pubkeys[vote.validator_id], chain_id=chain_id)

    return True, None


def validate_commit_certificate(
    certificate: CommitCertificate,
    validator_pubkeys: Mapping[str, bytes | str] | None = None,
    chain_id: str = DEFAULT_CHAIN_ID,
    quorum: int = DEFAULT_QUORUM,
    expected_height: int | None = None,
    expected_block_hash: str | None = None,
) -> tuple[bool, str | None]:
    """Kiểm tra tính hợp lệ của chứng nhận CommitCertificate (đủ 7 precommit hợp lệ)."""
    if certificate is None:
        return False, BAD_SIGNATURE
    return certificate.verify(
        validator_pubkeys=validator_pubkeys,
        chain_id=chain_id,
        quorum=quorum,
        expected_height=expected_height,
        expected_block_hash=expected_block_hash,
    )
