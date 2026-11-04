"""
Hàng chờ giao dịch (Transaction Pool / Mempool) của một Node trong Chat Chain.

Quy tắc hoạt động của TxPool (Mục 3.1, 4.1 & 12 README):
- Lưu các giao dịch theo đúng thứ tự đến (FIFO).
- Khi nhận giao dịch mới: kiểm tra hợp lệ theo quy tắc Mục 3.1 (tài khoản, chữ ký,
  quyền sở hữu key, định dạng key, giới hạn độ dài, chống replay nonce).
- Khử trùng theo tx_id và kiểm tra xung đột/trùng nonce trong cùng tài khoản.
- Cung cấp hàm lấy danh sách giao dịch để dựng khối (select_for_block): duyệt theo
  thứ tự đến, giữ đúng thứ tự nonce tuần tự trong từng tài khoản (tx chưa tới lượt nonce
  thì để lại trong pool), cộng dồn kích thước mã hóa và dừng ngay tại tx đầu tiên
  không còn vừa trong ngưỡng 4096 byte.
- Khi một khối được finalize: xóa toàn bộ các giao dịch đã vào khối (và các giao dịch
  có nonce <= nonce đã áp dụng trong state mới) khỏi pool.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping

from src.core.block import MAX_BLOCK_BYTES
from src.core.transaction import (
    DEFAULT_CHAIN_ID,
    MAX_TEXT_CHARS,
    MAX_TX_BYTES,
    Transaction,
)
from src.execution.state import State
from src.node.validation import (
    BAD_NONCE,
    DUPLICATE_MSG,
    REPLAYED_TX,
    validate_tx,
)


class TxPool:
    """
    Hàng chờ giao dịch (TxPool) lưu trữ các tin nhắn chat đang chờ được đưa vào khối.
    Đảm bảo tính xác định tuyệt đối (duyệt theo thứ tự danh sách đến, không dùng set không thứ tự).
    """

    def __init__(
        self,
        account_pubkeys: Mapping[str, bytes | str] | None = None,
        chain_id: str = DEFAULT_CHAIN_ID,
        max_text_chars: int = MAX_TEXT_CHARS,
        max_tx_bytes: int = MAX_TX_BYTES,
    ) -> None:
        self.account_pubkeys: dict[str, bytes | str] | None = (
            dict(account_pubkeys) if account_pubkeys is not None else None
        )
        self.chain_id: str = chain_id
        self.max_text_chars: int = max_text_chars
        self.max_tx_bytes: int = max_tx_bytes

        # Danh sách giao dịch giữ nguyên thứ tự đến
        self._queue: list[Transaction] = []
        # Map tra cứu nhanh theo tx_id (str -> Transaction)
        self._by_id: dict[str, Transaction] = {}
        # Map theo dõi các nonce đang nằm trong pool của mỗi tài khoản: account -> {nonce: tx_id}
        self._account_nonces: dict[str, dict[int, str]] = {}

    def add(
        self,
        tx: Transaction,
        state: State | None = None,
        account_pubkeys: Mapping[str, bytes | str] | None = None,
        strict_nonce: bool = False,
    ) -> tuple[bool, str | None]:
        """
        Kiểm tra và thêm một giao dịch mới vào TxPool:
        1. Kiểm tra mục 1..4 của Mục 3.1 (UNKNOWN_ACCOUNT, BAD_SIGNATURE, WRONG_DOMAIN,
           NOT_OWNER, BAD_KEY, TX_TOO_LONG).
        2. Kiểm tra nonce so với state hiện tại:
           - Nếu tx.nonce <= state.get_nonce(tx.account) -> từ chối với REPLAYED_TX.
        3. Kiểm tra trùng hoặc replay ngay trong pool:
           - Nếu cùng account và cùng nonce đã có trong pool -> từ chối với REPLAYED_TX.
           - Nếu tx_id đã tồn tại trong pool -> từ chối với DUPLICATE_MSG.
        4. Nếu strict_nonce=True: yêu cầu tx.nonce phải đúng bằng nonce tiếp theo
           của tài khoản (kể cả các tx nối tiếp đã có trong pool), nếu lớn hơn trả về BAD_NONCE.
        5. Thêm tx vào cuối hàng chờ và trả về (True, None).
        """
        pubkeys = account_pubkeys if account_pubkeys is not None else self.account_pubkeys

        # Kiểm tra các quy tắc 1..4 (chưa kiểm tra nonce ở bước này để xử lý riêng bước 5 bên dưới)
        ok, reason = validate_tx(
            tx=tx,
            state=state,
            account_pubkeys=pubkeys,
            chain_id=self.chain_id,
            max_text_chars=self.max_text_chars,
            max_tx_bytes=self.max_tx_bytes,
            check_nonce=False,
        )
        if not ok:
            return False, reason

        # Bước 5a: Kiểm tra chống replay so với trạng thái đã áp dụng
        applied_nonce = state.get_nonce(tx.account) if state is not None else 0
        if tx.nonce <= applied_nonce:
            return False, REPLAYED_TX

        # Bước 5b: Kiểm tra xem cùng (account, nonce) hoặc cùng tx_id đã có trong pool chưa
        acc_nonces = self._account_nonces.get(tx.account, {})
        if tx.nonce in acc_nonces:
            return False, REPLAYED_TX

        tid = str(tx.tx_id())
        if tid in self._by_id:
            return False, DUPLICATE_MSG

        # Bước 5c: Nếu bật chế độ kiểm tra nonce tuần tự nghiêm ngặt ngay khi vào pool
        if strict_nonce:
            # Nonce kỳ vọng tiếp theo tính cả các tx tuần tự đang chờ trong pool
            expected = applied_nonce + 1
            while expected in acc_nonces:
                expected += 1
            if tx.nonce > expected:
                return False, BAD_NONCE

        # Thêm giao dịch vào hàng chờ theo đúng thứ tự đến
        self._queue.append(tx)
        self._by_id[tid] = tx
        if tx.account not in self._account_nonces:
            self._account_nonces[tx.account] = {}
        self._account_nonces[tx.account][tx.nonce] = tid

        return True, None

    # Các bí danh cho phương thức add()
    add_tx = add
    submit = add
    put = add

    def has_tx(self, tx_or_id: Transaction | str) -> bool:
        """Kiểm tra một giao dịch (hoặc tx_id) có đang nằm trong pool hay không."""
        tid = str(tx_or_id.tx_id()) if isinstance(tx_or_id, Transaction) else str(tx_or_id)
        return tid in self._by_id

    def get_tx(self, tx_id: str) -> Transaction | None:
        """Lấy đối tượng Transaction theo tx_id (hoặc None nếu không có)."""
        return self._by_id.get(str(tx_id))

    def select_for_block(
        self,
        state: State,
        max_block_bytes: int = MAX_BLOCK_BYTES,
    ) -> list[Transaction]:
        """
        Chọn danh sách giao dịch từ pool để dựng khối theo đúng quy tắc Mục 4.1 README:
        - Duyệt tx pool theo thứ tự đến.
        - Giữ đúng thứ tự nonce tuần tự trong từng tài khoản (bắt đầu từ state.get_nonce(acc) + 1);
          giao dịch nào chưa tới lượt nonce thì để lại trong pool.
        - Cộng dồn kích thước mã hóa (tx.byte_size()); dừng ngay tại giao dịch hợp lệ đầu tiên
          không còn vừa trong ngưỡng max_block_bytes (4096 byte).
        """
        selected: list[Transaction] = []
        total_bytes: int = 0
        next_expected_nonce: dict[str, int] = {}

        for tx in self._queue:
            acc = tx.account
            if acc not in next_expected_nonce:
                next_expected_nonce[acc] = state.get_nonce(acc) + 1

            expected_n = next_expected_nonce[acc]
            if tx.nonce < expected_n:
                # Giao dịch đã cũ hơn nonce hiện tại, bỏ qua
                continue
            if tx.nonce > expected_n:
                # Giao dịch chưa tới lượt nonce của tài khoản này, để lại cho lượt sau
                continue

            # Giao dịch đúng lượt nonce: kiểm tra dung lượng khối còn lại
            tx_bytes = tx.byte_size()
            if total_bytes + tx_bytes > max_block_bytes:
                # Dừng ngay tại giao dịch đầu tiên không còn vừa trong ngưỡng 4096 byte
                break

            selected.append(tx)
            total_bytes += tx_bytes
            next_expected_nonce[acc] = expected_n + 1

        return selected

    # Bí danh cho select_for_block
    peek_for_block = select_for_block
    get_executable_txs = select_for_block

    def remove_finalized(
        self,
        transactions_or_ids: Iterable[Transaction | str] = (),
        state: State | None = None,
    ) -> int:
        """
        Xóa các giao dịch đã được đưa vào khối finalize khỏi pool.
        Nếu truyền thêm state mới, tự động dọn sạch mọi giao dịch có nonce <= nonce đã áp dụng.
        Trả về số lượng giao dịch đã xóa khỏi pool.
        """
        remove_ids: set[str] = set()
        for item in transactions_or_ids:
            if isinstance(item, Transaction):
                remove_ids.add(str(item.tx_id()))
            else:
                remove_ids.add(str(item))

        new_queue: list[Transaction] = []
        removed_count: int = 0

        for tx in self._queue:
            tid = str(tx.tx_id())
            already_applied = state is not None and tx.nonce <= state.get_nonce(tx.account)
            if tid in remove_ids or already_applied:
                removed_count += 1
                self._by_id.pop(tid, None)
                acc_map = self._account_nonces.get(tx.account)
                if acc_map is not None:
                    acc_map.pop(tx.nonce, None)
                    if not acc_map:
                        self._account_nonces.pop(tx.account, None)
            else:
                new_queue.append(tx)

        self._queue = new_queue
        return removed_count

    # Các bí danh cho remove_finalized
    remove_txs = remove_finalized
    remove_block_txs = remove_finalized
    prune = remove_finalized

    def pending(self) -> list[Transaction]:
        """Trả về bản sao danh sách các giao dịch đang chờ theo đúng thứ tự đến."""
        return list(self._queue)

    # Bí danh cho pending()
    get_all = pending
    list_txs = pending

    def clear(self) -> None:
        """Xóa toàn bộ giao dịch trong pool."""
        self._queue.clear()
        self._by_id.clear()
        self._account_nonces.clear()

    def __len__(self) -> int:
        return len(self._queue)

    def __contains__(self, tx_or_id: Transaction | str) -> bool:
        return self.has_tx(tx_or_id)

    def __iter__(self) -> Iterator[Transaction]:
        return iter(list(self._queue))
