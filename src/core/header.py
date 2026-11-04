"""
Định nghĩa lớp Header của một Block trong Chat Chain.

Cấu trúc Header (Mục 3.3 README):
- chain_id: định danh chuỗi (mặc định "lab01-chain")
- height: chiều cao khối (số nguyên >= 0)
- parent_hash: mã băm của khối cha (chuỗi hex 64 ký tự; rỗng ở khối genesis)
- tx_root: SHA256("TXROOT" || enc_list(tx_id...))
- state_hash: mã băm trạng thái sau khi thực thi danh sách giao dịch trong body
- proposer_id: định danh node tạo khối (ví dụ "N1")
- timestamp: thời gian ảo (ms), phải lớn hơn timestamp của khối cha
- signature: chữ ký Ed25519 của người tạo khối trên domain HEADER (không nằm trong block_hash)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.crypto.domain import HEADER, WRONG_CHAIN
from src.crypto.encoding import dec_bytes, dec_str, dec_uint, enc_bytes, enc_str, enc_uint
from src.crypto.hashing import HashHex, block_hash as compute_block_hash, to_canonical_hash_str
from src.crypto.signing import sign as crypto_sign, verify as crypto_verify

DEFAULT_CHAIN_ID: str = "lab01-chain"


@dataclass
class Header:
    """
    Lớp biểu diễn phần đầu (Header) của một Block trong chuỗi Chat Chain.
    """

    chain_id: str
    height: int
    parent_hash: str
    tx_root: str
    state_hash: str
    proposer_id: str
    timestamp: int
    signature: bytes = b""

    def __post_init__(self) -> None:
        """Chuẩn hóa các trường hash và chữ ký sau khi khởi tạo."""
        self.parent_hash = to_canonical_hash_str(self.parent_hash)
        self.tx_root = to_canonical_hash_str(self.tx_root)
        self.state_hash = to_canonical_hash_str(self.state_hash)
        if isinstance(self.signature, str):
            self.signature = bytes.fromhex(self.signature) if self.signature else b""
        elif isinstance(self.signature, (bytearray, memoryview)):
            self.signature = bytes(self.signature)

    def signing_fields(self) -> tuple[int, str, str, str, str, int]:
        """
        Trả về tuple các trường được ký theo thứ tự cố định của domain HEADER (Mục 6 README):
        (height, parent_hash, tx_root, state_hash, proposer_id, timestamp).
        """
        return (
            self.height,
            self.parent_hash,
            self.tx_root,
            self.state_hash,
            self.proposer_id,
            self.timestamp,
        )

    def encode_without_signature(self) -> bytes:
        """
        Mã hóa chuẩn toàn bộ các trường của Header ngoại trừ signature.
        Dùng để tính block_hash = SHA256("BLOCK" || enc(header không gồm signature)).
        """
        return (
            enc_str(self.chain_id)
            + enc_uint(self.height)
            + enc_str(self.parent_hash)
            + enc_str(self.tx_root)
            + enc_str(self.state_hash)
            + enc_str(self.proposer_id)
            + enc_uint(self.timestamp)
        )

    def block_hash(self) -> HashHex:
        """
        Tính mã băm định danh của khối:
        - Nếu là khối Genesis (height == 0, parent_hash == "", proposer_id == ""):
          SHA256("GENESIS" || chain_id)
        - Ngược lại:
          SHA256("BLOCK" || enc(header không gồm signature))
        """
        return compute_block_hash(self)

    def sign(self, private_key: bytes | str) -> bytes:
        """Ký Header bằng khóa bí mật của người tạo khối trên domain HEADER."""
        self.signature = crypto_sign(private_key, HEADER, self.chain_id, self.signing_fields())
        return self.signature

    def verify_signature(
        self,
        public_key: bytes | str,
        expected_chain_id: str | None = None,
    ) -> tuple[bool, str | None]:
        """
        Xác minh chữ ký của Header trên domain HEADER.
        Nếu truyền expected_chain_id mà khác self.chain_id thì trả về (False, "WRONG_CHAIN").
        """
        if expected_chain_id is not None and self.chain_id != expected_chain_id:
            return False, WRONG_CHAIN
        return crypto_verify(public_key, HEADER, self.chain_id, self.signing_fields(), self.signature)

    def encode(self) -> bytes:
        """Mã hóa chuẩn toàn bộ Header (bao gồm cả chữ ký)."""
        return self.encode_without_signature() + enc_bytes(self.signature)

    to_bytes = encode

    @classmethod
    def decode(cls, data: bytes, offset: int = 0) -> tuple[Header, int]:
        """Giải mã đối tượng Header từ mảng byte tại vị trí offset."""
        chain_id, cur = dec_str(data, offset)
        height, cur = dec_uint(data, cur)
        parent_hash, cur = dec_str(data, cur)
        tx_root, cur = dec_str(data, cur)
        state_hash, cur = dec_str(data, cur)
        proposer_id, cur = dec_str(data, cur)
        timestamp, cur = dec_uint(data, cur)
        signature, cur = dec_bytes(data, cur)
        return cls(
            chain_id=chain_id,
            height=height,
            parent_hash=parent_hash,
            tx_root=tx_root,
            state_hash=state_hash,
            proposer_id=proposer_id,
            timestamp=timestamp,
            signature=signature,
        ), cur

    @classmethod
    def from_bytes(cls, data: bytes) -> Header:
        """Giải mã hoàn chỉnh một Header từ mảng byte."""
        header, end_offset = cls.decode(data, 0)
        if end_offset != len(data):
            raise ValueError("Dữ liệu byte của Header còn dư byte không hợp lệ")
        return header

    def to_dict(self) -> dict[str, Any]:
        """Chuyển đổi Header sang dict phục vụ hiển thị hoặc debug."""
        return {
            "chain_id": self.chain_id,
            "height": self.height,
            "parent_hash": self.parent_hash,
            "tx_root": self.tx_root,
            "state_hash": self.state_hash,
            "proposer_id": self.proposer_id,
            "timestamp": self.timestamp,
            "signature": self.signature.hex(),
            "block_hash": str(self.block_hash()),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Header:
        """Khởi tạo đối tượng Header từ dict."""
        sig = data.get("signature", b"")
        if isinstance(sig, str):
            sig = bytes.fromhex(sig) if sig else b""
        return cls(
            chain_id=str(data.get("chain_id", DEFAULT_CHAIN_ID)),
            height=int(data["height"]),
            parent_hash=str(data.get("parent_hash", "")),
            tx_root=str(data.get("tx_root", "")),
            state_hash=str(data.get("state_hash", "")),
            proposer_id=str(data.get("proposer_id", "")),
            timestamp=int(data.get("timestamp", 0)),
            signature=sig,
        )
