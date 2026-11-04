"""
Giao diện đọc (Query Interface) phục vụ ứng dụng chat và các công cụ quan sát
(show_chat.py, show_state.py).

Quy tắc hoạt động (Mục 2, 10 & 12 README):
- Chỉ trả về các khối và tin nhắn đã finalize trong sổ cái (Ledger).
- Tin nhắn đang nằm trong TxPool hoặc trong khối chưa finalize tuyệt đối không hiển thị
  trên kênh chat chính thức.
- Cung cấp hai phương thức cốt lõi:
  * get_latest(k): trả về k khối đã finalize mới nhất (theo thứ tự chiều cao tăng dần).
  * get_block(height): trả về khối đã finalize ở chiều cao height (hoặc None nếu chưa finalize).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.core.block import Block
from src.execution.state import State
from src.node.ledger import Ledger


class ChatQuery:
    """
    Giao diện truy vấn dữ liệu đọc cho ứng dụng Chat Chain.
    Mô phỏng cách ứng dụng khách tải vài khối mới nhất bằng get_latest(k)
    và tải thêm các khối cũ hơn bằng get_block(height) khi người dùng cuộn lên.
    """

    def __init__(self, ledger: Ledger, state: State | None = None) -> None:
        self.ledger: Ledger = ledger
        self.state: State | None = state

    def get_latest(self, k: int, include_genesis: bool = False) -> list[Block]:
        """
        Lấy tối đa k khối đã finalize mới nhất từ sổ cái, sắp xếp theo chiều cao tăng dần.
        Mặc định bỏ qua khối khởi nguyên (height 0 - không chứa tin nhắn chat) trừ khi
        include_genesis=True.
        """
        if k <= 0:
            return []

        latest_h = self.ledger.latest_height
        min_h = 0 if include_genesis else 1
        if latest_h < min_h:
            return [self.ledger.get(0)] if (include_genesis and self.ledger.get(0) is not None) else []

        start_h = max(min_h, latest_h - k + 1)
        blocks: list[Block] = []
        for h in range(start_h, latest_h + 1):
            blk = self.ledger.get(h)
            if blk is not None:
                blocks.append(blk)
        return blocks

    def get_block(self, height: int) -> Block | None:
        """
        Lấy khối đã finalize tại chiều cao height.
        Trả về None nếu chiều cao đó chưa được finalize.
        """
        if height < 0 or height > self.ledger.latest_height:
            return None
        return self.ledger.get(height)

    def get_chat_messages(
        self,
        blocks: Sequence[Block] | None = None,
        last: int | None = None,
        height: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Trích xuất danh sách tin nhắn chat theo đúng thứ tự chuẩn của sổ cái:
        sắp xếp theo chiều cao khối (height), sau đó theo vị trí giao dịch trong khối.
        """
        if blocks is not None:
            target_blocks = list(blocks)
        elif height is not None:
            blk = self.get_block(height)
            target_blocks = [blk] if blk is not None else []
        elif last is not None:
            target_blocks = self.get_latest(last)
        else:
            target_blocks = self.ledger.all_blocks(include_genesis=False)

        messages: list[dict[str, Any]] = []
        for blk in target_blocks:
            if blk is None:
                continue
            for idx, tx in enumerate(blk.transactions):
                messages.append(
                    {
                        "height": blk.height,
                        "index": idx,
                        "account": tx.account,
                        "nonce": tx.nonce,
                        "key": tx.key,
                        "value": tx.value,
                        "tx_id": str(tx.tx_id()),
                        "timestamp": blk.timestamp,
                        "block_hash": str(blk.block_hash()),
                    }
                )
        return messages

    def get_state(self) -> State:
        """
        Trả về đối tượng State đầy đủ của node (nếu chưa gắn self.state thì tự động
        tái tạo từ toàn bộ các khối đã finalize trong Ledger).
        """
        if self.state is not None:
            return self.state
        rebuilt = State()
        for blk in self.ledger.all_blocks(include_genesis=False):
            for tx in blk.transactions:
                rebuilt.set(tx.key, tx.value, account=tx.account, nonce=tx.nonce)
        return rebuilt

    def get_state_entries(self, account: str | None = None) -> dict[str, str]:
        """
        Lấy các mục trạng thái (key -> value) đã finalize của một tài khoản cụ thể
        hoặc toàn bộ trạng thái của node.
        """
        target_state = self.get_state()
        if account is not None:
            return target_state.get_account_entries(account)
        return target_state.to_dict()


# Các bí danh lớp và hàm tiện ích mức module
NodeQuery = ChatQuery
QueryInterface = ChatQuery


def get_latest(ledger: Ledger, k: int, include_genesis: bool = False) -> list[Block]:
    """Hàm tiện ích lấy k khối đã finalize mới nhất từ một đối tượng Ledger."""
    return ChatQuery(ledger).get_latest(k, include_genesis=include_genesis)


def get_block(ledger: Ledger, height: int) -> Block | None:
    """Hàm tiện ích lấy khối đã finalize ở chiều cao height từ một đối tượng Ledger."""
    return ChatQuery(ledger).get_block(height)
