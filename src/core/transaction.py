"""
Định nghĩa lớp Transaction (một tin nhắn chat trên chuỗi) cùng các phương thức
mã hóa/giải mã chuẩn, tính tx_id, ký/xác minh chữ ký và kiểm tra giới hạn kích thước.

Mô hình dữ liệu Transaction (Mục 3.1 README):
- account: Tên tài khoản người gửi (alice, bob, carol, dave, erin)
- nonce: Số thứ tự tin của tài khoản, bắt đầu từ 1
- key: Bắt buộc đúng dạng <account>/chat/<nonce>
- value: Nội dung tin nhắn (văn bản, tối đa 200 ký tự NFC, không rỗng)
- signature: Chữ ký Ed25519 trên domain TX
- Tổng kích thước mã hóa của toàn bộ tx tối đa 1024 byte.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.crypto.domain import TX
from src.crypto.encoding import (
    count_nfc_chars,
    dec_bytes,
    dec_str,
    dec_uint,
    enc_bytes,
    enc_str,
    enc_uint,
    normalize_nfc,
)
from src.crypto.hashing import HashHex, tx_id as compute_tx_id
from src.crypto.signing import sign as crypto_sign, verify as crypto_verify

# Các hằng giới hạn mặc định của giao dịch theo cấu hình base.json
DEFAULT_CHAIN_ID: str = "lab01-chain"
MAX_TEXT_CHARS: int = 200
MAX_TX_BYTES: int = 1024

# Các mã lý do từ chối liên quan đến Transaction
REASON_NOT_OWNER: str = "NOT_OWNER"
REASON_BAD_KEY: str = "BAD_KEY"
REASON_TX_TOO_LONG: str = "TX_TOO_LONG"


@dataclass
class Transaction:
    """
    Lớp biểu diễn một giao dịch (tin nhắn chat) trong hệ thống Chat Chain.
    """

    account: str
    nonce: int
    key: str
    value: str
    signature: bytes = b""

    def __post_init__(self) -> None:
        """Chuẩn hóa NFC cho các trường chuỗi và chuẩn hóa chữ ký (chấp nhận cả hex str hoặc bytes)."""
        if isinstance(self.account, str):
            self.account = normalize_nfc(self.account)
        if isinstance(self.key, str):
            self.key = normalize_nfc(self.key)
        if isinstance(self.value, str):
            self.value = normalize_nfc(self.value)
        if isinstance(self.signature, str):
            self.signature = bytes.fromhex(self.signature) if self.signature else b""
        elif isinstance(self.signature, (bytearray, memoryview)):
            self.signature = bytes(self.signature)

    def signing_fields(self) -> tuple[str, int, str, str]:
        """
        Trả về tuple các trường được ký theo thứ tự cố định của domain TX:
        (account, nonce, key, value).
        """
        return (self.account, self.nonce, self.key, self.value)

    def signing_bytes(self) -> bytes:
        """Trả về mảng byte mã hóa chuẩn của các trường được ký (không gồm chữ ký)."""
        return (
            enc_str(self.account)
            + enc_uint(self.nonce)
            + enc_str(self.key)
            + enc_str(self.value)
        )

    def tx_id(self) -> HashHex:
        """
        Tính định danh duy nhất của giao dịch:
        tx_id = SHA256("TXID" || account || nonce || enc(key) || enc(value))
        """
        return compute_tx_id(self.account, self.nonce, self.key, self.value)

    def sign(self, private_key: bytes | str, chain_id: str = DEFAULT_CHAIN_ID) -> bytes:
        """Ký giao dịch bằng khóa bí mật của người dùng trên domain TX và gán vào self.signature."""
        self.signature = crypto_sign(private_key, TX, chain_id, self.signing_fields())
        return self.signature

    def verify_signature(
        self,
        public_key: bytes | str,
        chain_id: str = DEFAULT_CHAIN_ID,
    ) -> tuple[bool, str | None]:
        """
        Xác minh chữ ký của giao dịch bằng khóa công khai của account.
        Trả về (True, None) nếu hợp lệ, hoặc (False, "BAD_SIGNATURE" | "WRONG_DOMAIN").
        """
        return crypto_verify(public_key, TX, chain_id, self.signing_fields(), self.signature)

    def encode(self) -> bytes:
        """
        Mã hóa chuẩn toàn bộ giao dịch (bao gồm cả chữ ký) thành mảng byte.
        Dùng để truyền qua mạng, lưu trữ và kiểm tra giới hạn 1024 byte.
        """
        return (
            enc_str(self.account)
            + enc_uint(self.nonce)
            + enc_str(self.key)
            + enc_str(self.value)
            + enc_bytes(self.signature)
        )

    # Bí danh cho encode()
    to_bytes = encode

    @classmethod
    def decode(cls, data: bytes, offset: int = 0) -> tuple[Transaction, int]:
        """Giải mã một đối tượng Transaction từ mảng byte tại vị trí offset."""
        account, cur = dec_str(data, offset)
        nonce, cur = dec_uint(data, cur)
        key, cur = dec_str(data, cur)
        value, cur = dec_str(data, cur)
        signature, cur = dec_bytes(data, cur)
        return cls(
            account=account,
            nonce=nonce,
            key=key,
            value=value,
            signature=signature,
        ), cur

    @classmethod
    def from_bytes(cls, data: bytes) -> Transaction:
        """Giải mã hoàn chỉnh một Transaction từ mảng byte."""
        tx, end_offset = cls.decode(data, 0)
        if end_offset != len(data):
            raise ValueError("Dữ liệu byte của Transaction còn dư byte không hợp lệ")
        return tx

    def char_count(self) -> int:
        """Đếm số ký tự (code point) của nội dung tin nhắn sau khi chuẩn hóa NFC."""
        return count_nfc_chars(self.value)

    def byte_size(self) -> int:
        """Tính kích thước mã hóa chuẩn của toàn bộ giao dịch (tính bằng byte)."""
        return len(self.encode())

    # Bí danh cho byte_size()
    encoded_size = byte_size

    def check_key_format(self) -> tuple[bool, str | None]:
        """
        Kiểm tra quy tắc 3 (Mục 3.1 README):
        - key phải bắt đầu bằng '<account>/' (nếu sai trả về NOT_OWNER).
        - key phải đúng định dạng '<account>/chat/<nonce>' (nếu sai trả về BAD_KEY).
        """
        if not isinstance(self.account, str) or not self.account:
            return False, REASON_NOT_OWNER

        owner_prefix = f"{self.account}/"
        if not isinstance(self.key, str) or not self.key.startswith(owner_prefix):
            return False, REASON_NOT_OWNER

        if not isinstance(self.nonce, int) or isinstance(self.nonce, bool):
            return False, REASON_BAD_KEY

        expected_key = f"{self.account}/chat/{self.nonce}"
        if self.key != expected_key:
            return False, REASON_BAD_KEY

        return True, None

    def check_limits(
        self,
        max_text_chars: int = MAX_TEXT_CHARS,
        max_tx_bytes: int = MAX_TX_BYTES,
    ) -> tuple[bool, str | None]:
        """
        Kiểm tra quy tắc 4 (Mục 3.1 README):
        - value không được rỗng và có độ dài tối đa max_text_chars (200) ký tự sau chuẩn hóa NFC.
        - Toàn bộ giao dịch sau mã hóa chuẩn có kích thước tối đa max_tx_bytes (1024) byte.
        Nếu vi phạm trả về (False, "TX_TOO_LONG").
        """
        if not isinstance(self.value, str):
            return False, REASON_TX_TOO_LONG

        nfc_len = self.char_count()
        if nfc_len == 0 or nfc_len > max_text_chars:
            return False, REASON_TX_TOO_LONG

        if self.byte_size() > max_tx_bytes:
            return False, REASON_TX_TOO_LONG

        return True, None

    def to_dict(self) -> dict[str, Any]:
        """Chuyển đổi Transaction sang dict phục vụ hiển thị hoặc tuần tự hóa."""
        return {
            "account": self.account,
            "nonce": self.nonce,
            "key": self.key,
            "value": normalize_nfc(self.value),
            "signature": self.signature.hex(),
            "tx_id": str(self.tx_id()),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transaction:
        """Tạo đối tượng Transaction từ dict."""
        sig = data.get("signature", b"")
        if isinstance(sig, str):
            sig = bytes.fromhex(sig) if sig else b""
        return cls(
            account=str(data["account"]),
            nonce=int(data["nonce"]),
            key=str(data["key"]),
            value=str(data["value"]),
            signature=sig,
        )
