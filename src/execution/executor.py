"""
Thực thi giao dịch (Transaction) và khối (Block) trên trạng thái (State) của Chat Chain.

Quy tắc kiểm tra và thực thi một tin nhắn (Mục 3.1 README, theo đúng thứ tự):
1. account có trong sổ tài khoản (UNKNOWN_ACCOUNT) - khi cung cấp account_pubkeys.
2. Chữ ký hợp lệ bằng khóa công khai của account (BAD_SIGNATURE, WRONG_DOMAIN) - khi cung cấp account_pubkeys.
3. key bắt đầu bằng '<account>/' (NOT_OWNER) và đúng dạng '<account>/chat/<nonce>' (BAD_KEY).
4. value không rỗng, tối đa 200 ký tự (NFC) và toàn bộ tx mã hóa tối đa 1024 byte (TX_TOO_LONG).
5. nonce đúng bằng nonce_đã_áp_dụng + 1 của tài khoản:
   - Nhỏ hơn hoặc bằng nonce_đã_áp_dụng -> REPLAYED_TX
   - Lớn hơn nonce_đã_áp_dụng + 1 -> BAD_NONCE
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from src.core.block import MAX_BLOCK_BYTES, Block
from src.core.transaction import (
    DEFAULT_CHAIN_ID,
    MAX_TEXT_CHARS,
    MAX_TX_BYTES,
    Transaction,
)
from src.execution.state import State

# Các mã lý do từ chối khi thực thi giao dịch và khối
UNKNOWN_ACCOUNT: str = "UNKNOWN_ACCOUNT"
BAD_SIGNATURE: str = "BAD_SIGNATURE"
WRONG_DOMAIN: str = "WRONG_DOMAIN"
NOT_OWNER: str = "NOT_OWNER"
BAD_KEY: str = "BAD_KEY"
TX_TOO_LONG: str = "TX_TOO_LONG"
REPLAYED_TX: str = "REPLAYED_TX"
BAD_NONCE: str = "BAD_NONCE"
BLOCK_TOO_LARGE: str = "BLOCK_TOO_LARGE"
BAD_TX_ROOT: str = "BAD_TX_ROOT"
BAD_STATE_HASH: str = "BAD_STATE_HASH"


def apply_tx(
    state: State,
    tx: Transaction,
    account_pubkeys: Mapping[str, bytes | str] | None = None,
    chain_id: str = DEFAULT_CHAIN_ID,
    max_text_chars: int = MAX_TEXT_CHARS,
    max_tx_bytes: int = MAX_TX_BYTES,
    check_limits: bool = True,
    dry_run: bool = False,
) -> tuple[bool, str | None]:
    """
    Kiểm tra và áp dụng một giao dịch (Transaction) vào State:
    - Kiểm tra tuần tự: sổ tài khoản & chữ ký (nếu truyền account_pubkeys) ->
      quyền sở hữu key (NOT_OWNER) -> định dạng key '<account>/chat/<nonce>' (BAD_KEY) ->
      giới hạn độ dài ký tự & byte (TX_TOO_LONG) -> thứ tự nonce (REPLAYED_TX / BAD_NONCE).
    - Nếu hợp lệ và dry_run=False: ghi key=value vào state và tăng bộ đếm nonce của account.
    - Trả về (True, None) nếu thành công, hoặc (False, reason) nếu bị từ chối.
    """
    # Bước 1 & 2: Kiểm tra tài khoản tồn tại và xác minh chữ ký (nếu truyền sổ tài khoản)
    if account_pubkeys is not None:
        if tx.account not in account_pubkeys:
            return False, UNKNOWN_ACCOUNT
        ok_sig, sig_reason = tx.verify_signature(account_pubkeys[tx.account], chain_id=chain_id)
        if not ok_sig:
            return False, sig_reason

    # Bước 3: Kiểm tra quyền sở hữu không gian tên và định dạng key
    ok_key, key_reason = tx.check_key_format()
    if not ok_key:
        return False, key_reason

    # Bước 4: Kiểm tra giới hạn số ký tự NFC (<= 200) và kích thước mã hóa (<= 1024 byte)
    if check_limits:
        ok_lim, lim_reason = tx.check_limits(
            max_text_chars=max_text_chars,
            max_tx_bytes=max_tx_bytes,
        )
        if not ok_lim:
            return False, lim_reason

    # Bước 5: Kiểm tra chống phát lại (replay) và thứ tự tuần tự của nonce
    applied_nonce = state.get_nonce(tx.account)
    expected_nonce = applied_nonce + 1
    if tx.nonce <= applied_nonce:
        return False, REPLAYED_TX
    if tx.nonce > expected_nonce:
        return False, BAD_NONCE

    # Ghi nhận vào state nếu không phải chế độ chỉ kiểm tra
    if not dry_run:
        state.set(tx.key, tx.value, account=tx.account, nonce=tx.nonce)

    return True, None


def apply_block(
    state: State,
    block_or_txs: Block | Sequence[Transaction],
    account_pubkeys: Mapping[str, bytes | str] | None = None,
    chain_id: str = DEFAULT_CHAIN_ID,
    max_text_chars: int = MAX_TEXT_CHARS,
    max_tx_bytes: int = MAX_TX_BYTES,
    max_block_bytes: int = MAX_BLOCK_BYTES,
    dry_run: bool = False,
    verify_commitments: bool = True,
    mutate_in_place: bool = False,
) -> tuple[State | None, str | None]:
    """
    Thực thi toàn bộ danh sách giao dịch của một Block trên một bản sao của State:
    - Kiểm tra tổng kích thước mã hóa của các giao dịch trong block <= max_block_bytes (4096 byte).
    - Nếu truyền đối tượng Block và verify_commitments=True (khi không phải thực thi thử tạo block mới):
      kiểm tra tx_root trong Header khớp với danh sách giao dịch thực tế (BAD_TX_ROOT).
    - Thực thi lần lượt từng giao dịch bằng apply_tx trên state nháp. Nếu bất kỳ tx nào lỗi,
      hủy bỏ toàn bộ thay đổi và trả về (None, reason).
    - Nếu truyền Block và verify_commitments=True: kiểm tra state_hash sau thực thi khớp với
      header.state_hash (BAD_STATE_HASH).
    - Trả về (new_state, None) khi hợp lệ. Nếu mutate_in_place=True và dry_run=False thì
      cập nhật luôn vào đối tượng state gốc.
    """
    is_block_obj = isinstance(block_or_txs, Block) or hasattr(block_or_txs, "header")
    if is_block_obj:
        blk: Block = block_or_txs  # type: ignore[assignment]
        tx_list: list[Transaction] = list(blk.transactions)
    else:
        blk = None  # type: ignore[assignment]
        tx_list = list(block_or_txs)  # type: ignore[arg-type]

    # 1. Kiểm tra tổng kích thước mã hóa của phần thân khối <= 4096 byte
    total_body_bytes = sum(tx.byte_size() for tx in tx_list)
    if total_body_bytes > max_block_bytes:
        return None, BLOCK_TOO_LARGE

    # 2. Nếu có Header và yêu cầu đối chiếu cam kết thì kiểm tra tx_root trước
    if is_block_obj and verify_commitments and not dry_run:
        if blk.header.tx_root and str(blk.compute_tx_root()) != blk.header.tx_root:
            return None, BAD_TX_ROOT

    # 3. Nhân bản state để thực thi nguyên tử (nếu giữa chừng lỗi thì state cũ giữ nguyên)
    working_state = state.clone()

    for tx in tx_list:
        ok, reason = apply_tx(
            working_state,
            tx,
            account_pubkeys=account_pubkeys,
            chain_id=chain_id,
            max_text_chars=max_text_chars,
            max_tx_bytes=max_tx_bytes,
            check_limits=True,
            dry_run=False,
        )
        if not ok:
            return None, reason

    # 4. Đối chiếu state_hash sau khi đã áp dụng toàn bộ giao dịch trong Body
    if is_block_obj and verify_commitments and not dry_run:
        if blk.header.state_hash and str(working_state.state_hash()) != blk.header.state_hash:
            return None, BAD_STATE_HASH

    # 5. Nếu người gọi muốn cập nhật trực tiếp vào state truyền vào (và không phải thực thi thử)
    if mutate_in_place and not dry_run:
        state.replace_from(working_state)

    return working_state, None


def trial_execute_transactions(
    base_state: State,
    candidate_txs: Sequence[Transaction],
    account_pubkeys: Mapping[str, bytes | str] | None = None,
    chain_id: str = DEFAULT_CHAIN_ID,
    max_text_chars: int = MAX_TEXT_CHARS,
    max_tx_bytes: int = MAX_TX_BYTES,
    max_block_bytes: int = MAX_BLOCK_BYTES,
) -> tuple[State, list[Transaction], list[tuple[Transaction, str]]]:
    """
    Hàm tiện ích phục vụ chế độ "thực thi thử" cho Proposer khi dựng khối mới:
    - Nhận trạng thái hiện tại (base_state) và danh sách giao dịch ứng viên từ TxPool.
    - Thực thi thử trên bản sao của base_state, dừng ngay tại giao dịch đầu tiên vượt quá
      ngưỡng kích thước khối (max_block_bytes = 4096 byte) theo đúng quy tắc Mục 4.1.
    - Trả về bộ 3: (state_sau_thực_thi_thử, danh_sách_tx_được_chọn, danh_sách_tx_bị_bỏ_qua_kèm_lý_do).
    """
    working_state = base_state.clone()
    included_txs: list[Transaction] = []
    skipped_txs: list[tuple[Transaction, str]] = []
    accumulated_bytes: int = 0

    for tx in candidate_txs:
        ok, reason = apply_tx(
            working_state,
            tx,
            account_pubkeys=account_pubkeys,
            chain_id=chain_id,
            max_text_chars=max_text_chars,
            max_tx_bytes=max_tx_bytes,
            check_limits=True,
            dry_run=True,
        )
        if not ok:
            skipped_txs.append((tx, reason or BAD_NONCE))
            continue

        tx_size = tx.byte_size()
        # Dừng ngay tại giao dịch hợp lệ đầu tiên không còn vừa trong ngưỡng 4096 byte
        if accumulated_bytes + tx_size > max_block_bytes:
            break

        working_state.set(tx.key, tx.value, account=tx.account, nonce=tx.nonce)
        included_txs.append(tx)
        accumulated_bytes += tx_size

    return working_state, included_txs, skipped_txs
