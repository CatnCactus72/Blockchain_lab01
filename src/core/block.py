"""
Định nghĩa lớp Block (Header + Body) và hàm khởi tạo khối khởi nguyên (Genesis Block).

Cấu trúc Block (Mục 3.3 README):
- Header: thông tin siêu dữ liệu và cam kết (tx_root, state_hash, parent_hash, chữ ký)
- Body: danh sách giao dịch (Transaction) có thứ tự, tổng kích thước mã hóa <= 4096 byte, có thể rỗng.
- Genesis Block: height 0, chain_id = "lab01-chain", block_hash = SHA256("GENESIS" || chain_id), state rỗng.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.core.header import DEFAULT_CHAIN_ID, Header
from src.core.transaction import Transaction
from src.crypto.encoding import dec_list, enc_list
from src.crypto.hashing import (
    HashHex,
    state_hash as compute_state_hash,
    tx_root as compute_tx_root,
)

# Giới hạn tổng kích thước mã hóa của danh sách giao dịch trong Body (Mục 3.3 & 7 README)
MAX_BLOCK_BYTES: int = 4096


@dataclass
class Block:
    """
    Lớp biểu diễn một khối hoàn chỉnh (Block = Header + Body) trong Chat Chain.
    """

    header: Header
    transactions: list[Transaction] = field(default_factory=list)

    @property
    def body(self) -> list[Transaction]:
        """Bí danh cho danh sách giao dịch (transactions) trong phần thân khối."""
        return self.transactions

    @body.setter
    def body(self, value: list[Transaction]) -> None:
        self.transactions = list(value)

    @property
    def txs(self) -> list[Transaction]:
        """Bí danh ngắn gọn cho danh sách giao dịch (transactions)."""
        return self.transactions

    @property
    def chain_id(self) -> str:
        """Định danh chuỗi của khối."""
        return self.header.chain_id

    @property
    def height(self) -> int:
        """Chiều cao của khối."""
        return self.header.height

    @property
    def parent_hash(self) -> str:
        """Mã băm của khối cha."""
        return self.header.parent_hash

    @property
    def tx_root(self) -> str:
        """Mã băm gốc các giao dịch ghi trong Header."""
        return self.header.tx_root

    @property
    def state_hash(self) -> str:
        """Mã băm trạng thái sau khi thực thi khối ghi trong Header."""
        return self.header.state_hash

    @property
    def proposer_id(self) -> str:
        """Định danh node đã tạo khối."""
        return self.header.proposer_id

    @property
    def timestamp(self) -> int:
        """Thời gian ảo (ms) ghi trong Header."""
        return self.header.timestamp

    def block_hash(self) -> HashHex:
        """Tính mã băm của khối thông qua Header."""
        return self.header.block_hash()

    def body_size(self) -> int:
        """
        Tính tổng kích thước mã hóa chuẩn (byte) của tất cả giao dịch trong Body.
        Khối hợp lệ phải thỏa mãn body_size() <= 4096 byte.
        """
        return sum(tx.byte_size() for tx in self.transactions)

    def compute_tx_root(self) -> HashHex:
        """Tính lại tx_root từ danh sách giao dịch thực tế trong Body."""
        return compute_tx_root(self.transactions)

    def encode_body(self) -> bytes:
        """Mã hóa chuẩn danh sách giao dịch trong Body."""
        return enc_list([tx.encode() for tx in self.transactions])

    @classmethod
    def decode_body(cls, data: bytes, offset: int = 0) -> tuple[list[Transaction], int]:
        """Giải mã danh sách giao dịch của Body từ mảng byte tại vị trí offset."""
        return dec_list(data, Transaction.decode, offset)

    def encode(self) -> bytes:
        """Mã hóa chuẩn toàn bộ Block (Header + Body)."""
        return self.header.encode() + self.encode_body()

    to_bytes = encode

    @classmethod
    def decode(cls, data: bytes, offset: int = 0) -> tuple[Block, int]:
        """Giải mã một Block từ mảng byte tại vị trí offset."""
        header, cur = Header.decode(data, offset)
        txs, cur = cls.decode_body(data, cur)
        return cls(header=header, transactions=txs), cur

    @classmethod
    def from_bytes(cls, data: bytes) -> Block:
        """Giải mã hoàn chỉnh một Block từ mảng byte."""
        block, end_offset = cls.decode(data, 0)
        if end_offset != len(data):
            raise ValueError("Dữ liệu byte của Block còn dư byte không hợp lệ")
        return block

    @classmethod
    def genesis(cls, chain_id: str = DEFAULT_CHAIN_ID) -> Block:
        """
        Khởi tạo khối khởi nguyên (Genesis Block) ở height 0:
        - height = 0, chain_id = chain_id
        - state rỗng, danh sách giao dịch rỗng
        - block_hash = SHA256("GENESIS" || chain_id)
        """
        empty_tx_root = str(compute_tx_root([]))
        empty_state_hash = str(compute_state_hash({}))
        header = Header(
            chain_id=chain_id,
            height=0,
            parent_hash="",
            tx_root=empty_tx_root,
            state_hash=empty_state_hash,
            proposer_id="",
            timestamp=0,
            signature=b"",
        )
        return cls(header=header, transactions=[])

    def to_dict(self) -> dict[str, Any]:
        """Chuyển đổi Block sang dict."""
        return {
            "header": self.header.to_dict(),
            "transactions": [tx.to_dict() for tx in self.transactions],
            "block_hash": str(self.block_hash()),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Block:
        """Tạo đối tượng Block từ dict."""
        header = Header.from_dict(data["header"])
        txs = [
            tx if isinstance(tx, Transaction) else Transaction.from_dict(tx)
            for tx in data.get("transactions", data.get("body", []))
        ]
        return cls(header=header, transactions=txs)


def make_genesis_block(chain_id: str = DEFAULT_CHAIN_ID) -> Block:
    """Hàm tiện ích dựng khối khởi nguyên (Genesis Block) cho chuỗi."""
    return Block.genesis(chain_id=chain_id)


# Các bí danh hàm dựng khối Genesis
create_genesis_block = make_genesis_block
build_genesis_block = make_genesis_block
