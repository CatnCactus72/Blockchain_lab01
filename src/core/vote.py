"""
Định nghĩa lớp Vote (phiếu bầu PREVOTE / PRECOMMIT, hỗ trợ bầu NIL) và
lớp CommitCertificate (chứng nhận đủ 7 phiếu precommit hợp lệ để finalize block).

Mô hình dữ liệu Vote & CommitCertificate (Mục 3.5 & 6 README):
- Vote = (height, round, phase PREVOTE|PRECOMMIT, block_hash hoặc NIL, validator_id, signature)
- Domain ký: VOTE, các trường được ký: (height, round, phase, block_hash hoặc NIL, validator_id)
- NIL được mã hóa chuẩn thành 32 byte 0 (NIL_BYTES).
- CommitCertificate: tập ít nhất 7 phiếu PRECOMMIT hợp lệ của các validator khác nhau
  cho cùng một block_hash (khác NIL) ở cùng một height.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.crypto.domain import BAD_SIGNATURE, VOTE
from src.crypto.encoding import (
    NIL_BYTES,
    dec_bytes,
    dec_list,
    dec_str,
    dec_uint,
    enc_bytes,
    enc_list,
    enc_str,
    enc_uint,
)
from src.crypto.hashing import to_canonical_hash_str
from src.crypto.signing import sign as crypto_sign, verify as crypto_verify

DEFAULT_CHAIN_ID: str = "lab01-chain"
DEFAULT_QUORUM: int = 7

# Hai pha bỏ phiếu trong đồng thuận BFT
PREVOTE: str = "PREVOTE"
PRECOMMIT: str = "PRECOMMIT"
VALID_PHASES: tuple[str, ...] = (PREVOTE, PRECOMMIT)

# Giá trị đại diện cho phiếu bầu trống (NIL)
NIL: None = None
NIL_HASH_STR: str = "NIL"

# Mã lý do từ chối vote
REASON_DUPLICATE_VOTE: str = "DUPLICATE_VOTE"
REASON_CONFLICTING_VOTE: str = "CONFLICTING_VOTE"


@dataclass
class Vote:
    """
    Lớp biểu diễn một phiếu bầu (PREVOTE hoặc PRECOMMIT) của một validator.
    Nếu block_hash là None, "" hoặc "NIL" thì đây là phiếu bầu cho NIL.
    """

    height: int
    round: int
    phase: str
    block_hash: str | None
    validator_id: str
    signature: bytes = b""

    def __post_init__(self) -> None:
        """Chuẩn hóa trường block_hash (None cho NIL, hoặc chuỗi hex 64 ký tự) và signature."""
        if (
            self.block_hash is None
            or self.block_hash == ""
            or self.block_hash == NIL_HASH_STR
            or self.block_hash == NIL_BYTES
        ):
            self.block_hash = None
        else:
            self.block_hash = to_canonical_hash_str(self.block_hash)

        if isinstance(self.signature, str):
            self.signature = bytes.fromhex(self.signature) if self.signature else b""
        elif isinstance(self.signature, (bytearray, memoryview)):
            self.signature = bytes(self.signature)

    @property
    def is_nil(self) -> bool:
        """Kiểm tra xem phiếu bầu này có phải là phiếu bầu cho NIL hay không."""
        return self.block_hash is None

    def signing_fields(self) -> tuple[int, int, str, str | None, str]:
        """
        Trả về tuple các trường được ký theo thứ tự cố định của domain VOTE (Mục 6 README):
        (height, round, phase, block_hash (hoặc None cho NIL), validator_id).
        Khi block_hash là None, hàm mã hóa chuẩn sẽ tự chuyển thành 32 byte 0 (NIL_BYTES).
        """
        return (
            self.height,
            self.round,
            self.phase,
            self.block_hash,
            self.validator_id,
        )

    def sign(self, private_key: bytes | str, chain_id: str = DEFAULT_CHAIN_ID) -> bytes:
        """Ký phiếu bầu bằng khóa bí mật của validator trên domain VOTE."""
        self.signature = crypto_sign(private_key, VOTE, chain_id, self.signing_fields())
        return self.signature

    def verify_signature(
        self,
        public_key: bytes | str,
        chain_id: str = DEFAULT_CHAIN_ID,
    ) -> tuple[bool, str | None]:
        """
        Xác minh chữ ký của phiếu bầu trên domain VOTE.
        Trả về (True, None) nếu hợp lệ, hoặc (False, "BAD_SIGNATURE" | "WRONG_DOMAIN").
        """
        if self.phase not in VALID_PHASES:
            return False, BAD_SIGNATURE
        return crypto_verify(public_key, VOTE, chain_id, self.signing_fields(), self.signature)

    def encode(self) -> bytes:
        """Mã hóa chuẩn toàn bộ đối tượng Vote thành mảng byte (NIL dùng 32 byte 0)."""
        enc_hash = NIL_BYTES if self.block_hash is None else enc_str(self.block_hash)
        return (
            enc_uint(self.height)
            + enc_uint(self.round)
            + enc_str(self.phase)
            + enc_hash
            + enc_str(self.validator_id)
            + enc_bytes(self.signature)
        )

    to_bytes = encode

    @classmethod
    def decode(cls, data: bytes, offset: int = 0) -> tuple[Vote, int]:
        """Giải mã đối tượng Vote từ mảng byte tại vị trí offset."""
        height, cur = dec_uint(data, offset)
        round_num, cur = dec_uint(data, cur)
        phase, cur = dec_str(data, cur)
        if cur + 32 <= len(data) and data[cur : cur + 32] == NIL_BYTES:
            block_hash = None
            cur += 32
        else:
            hash_str, cur = dec_str(data, cur)
            block_hash = None if hash_str == "" or hash_str == NIL_HASH_STR else hash_str
        validator_id, cur = dec_str(data, cur)
        signature, cur = dec_bytes(data, cur)
        return cls(
            height=height,
            round=round_num,
            phase=phase,
            block_hash=block_hash,
            validator_id=validator_id,
            signature=signature,
        ), cur

    @classmethod
    def from_bytes(cls, data: bytes) -> Vote:
        """Giải mã hoàn chỉnh một đối tượng Vote từ mảng byte."""
        vote, end_offset = cls.decode(data, 0)
        if end_offset != len(data):
            raise ValueError("Dữ liệu byte của Vote còn dư byte không hợp lệ")
        return vote

    def to_dict(self) -> dict[str, Any]:
        """Chuyển đổi Vote sang dict."""
        return {
            "height": self.height,
            "round": self.round,
            "phase": self.phase,
            "block_hash": self.block_hash if self.block_hash is not None else NIL_HASH_STR,
            "validator_id": self.validator_id,
            "signature": self.signature.hex(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Vote:
        """Tạo đối tượng Vote từ dict."""
        sig = data.get("signature", b"")
        if isinstance(sig, str):
            sig = bytes.fromhex(sig) if sig else b""
        bh = data.get("block_hash")
        if bh == NIL_HASH_STR or bh == "":
            bh = None
        return cls(
            height=int(data["height"]),
            round=int(data["round"]),
            phase=str(data["phase"]),
            block_hash=bh,
            validator_id=str(data["validator_id"]),
            signature=sig,
        )


@dataclass
class CommitCertificate:
    """
    Chứng nhận cam kết (Commit Certificate): tập hợp tối thiểu 7 phiếu PRECOMMIT hợp lệ
    cho cùng một block_hash ở cùng một height.
    Sổ cái (Ledger) lưu chứng nhận này đi kèm mỗi khối đã finalize để các node bị tụt lại
    tự kiểm tra tính hợp lệ khi đồng bộ mà không cần tin tưởng peer.
    """

    height: int
    block_hash: str
    votes: list[Vote] = field(default_factory=list)
    round: int = 0
    _round_specified: bool = field(default=False, init=False, repr=False, compare=False)

    def __init__(
        self,
        height: int,
        block_hash: str,
        votes: Sequence[Vote] | None = None,
        round: int | None = None,
    ) -> None:
        self.height = int(height)
        self.block_hash = to_canonical_hash_str(block_hash)
        self.votes = list(votes) if votes is not None else []
        if round is None:
            if self.votes:
                self.round = int(self.votes[0].round)
                self._round_specified = True
            else:
                self.round = 0
                self._round_specified = False
        else:
            self.round = int(round)
            self._round_specified = True

    @property
    def precommits(self) -> list[Vote]:
        """Bí danh cho danh sách phiếu precommit trong chứng nhận."""
        return self.votes

    def verify(
        self,
        validator_pubkeys: Mapping[str, bytes | str] | None = None,
        chain_id: str = DEFAULT_CHAIN_ID,
        quorum: int = DEFAULT_QUORUM,
        expected_height: int | None = None,
        expected_block_hash: str | None = None,
    ) -> tuple[bool, str | None]:
        """
        Kiểm tra chứng nhận CommitCertificate có đủ quorum (7) phiếu PRECOMMIT hợp lệ hay không:
        1. Khớp expected_height và expected_block_hash (nếu truyền vào).
        2. block_hash không được rỗng / NIL.
        3. Từng phiếu trong danh sách phải có chữ ký hợp lệ (nếu cung cấp validator_pubkeys)
           và cùng height với chứng nhận; nếu cùng validator có 2 phiếu khác nhau (khác block_hash,
           khác round hoặc khác phase) thì từ chối ngay với CONFLICTING_VOTE.
        4. Mọi phiếu hợp lệ phải có phase == PRECOMMIT, cùng block_hash (khác NIL) và cùng round
           với self.round của chứng nhận.
        5. Tổng số validator hợp lệ duy nhất phải >= quorum (mặc định 7).
        """
        if expected_height is not None and self.height != expected_height:
            return False, BAD_SIGNATURE

        if expected_block_hash is not None:
            norm_expected = to_canonical_hash_str(expected_block_hash)
            if self.block_hash != norm_expected:
                return False, BAD_SIGNATURE

        if not self.block_hash:
            return False, BAD_SIGNATURE

        if not self.votes:
            return False, BAD_SIGNATURE

        if self.round < 0:
            return False, BAD_SIGNATURE

        seen_validators: dict[str, Vote] = {}
        target_round: int | None = (
            self.round if (getattr(self, "_round_specified", True) or self.round != 0) else None
        )

        # Bước 1: Kiểm tra chữ ký từng phiếu và phát hiện phiếu mâu thuẫn (CONFLICTING_VOTE)
        # từ cùng một validator trước khi đối chiếu với block_hash và round của chứng nhận.
        for vote in self.votes:
            if vote.phase not in VALID_PHASES:
                return False, BAD_SIGNATURE
            if vote.height != self.height:
                return False, BAD_SIGNATURE

            # Kiểm tra validator và chữ ký nếu có sổ khóa validator
            if validator_pubkeys is not None:
                if vote.validator_id not in validator_pubkeys:
                    return False, BAD_SIGNATURE
                ok, reason = vote.verify_signature(
                    validator_pubkeys[vote.validator_id],
                    chain_id=chain_id,
                )
                if not ok:
                    return False, reason

            # Kiểm tra trùng hoặc mâu thuẫn từ cùng một validator
            if vote.validator_id in seen_validators:
                prev_vote = seen_validators[vote.validator_id]
                if (
                    prev_vote.block_hash != vote.block_hash
                    or prev_vote.round != vote.round
                    or prev_vote.phase != vote.phase
                ):
                    return False, REASON_CONFLICTING_VOTE
                # Cùng nội dung đến lần nữa: bỏ qua không đếm lần hai
                continue

            seen_validators[vote.validator_id] = vote

        # Bước 2: Kiểm tra mọi phiếu đều là PRECOMMIT cho đúng block_hash và khớp round
        for vote in seen_validators.values():
            if vote.phase != PRECOMMIT:
                return False, BAD_SIGNATURE
            if vote.is_nil or vote.block_hash != self.block_hash:
                return False, BAD_SIGNATURE

            if target_round is None:
                target_round = vote.round
            elif vote.round != target_round:
                return False, BAD_SIGNATURE

        if len(seen_validators) < quorum:
            return False, BAD_SIGNATURE

        return True, None

    def encode(self) -> bytes:
        """Mã hóa chuẩn CommitCertificate thành mảng byte."""
        return (
            enc_uint(self.height)
            + enc_str(self.block_hash)
            + enc_uint(self.round)
            + enc_list([v.encode() for v in self.votes])
        )

    to_bytes = encode

    @classmethod
    def decode(cls, data: bytes, offset: int = 0) -> tuple[CommitCertificate, int]:
        """Giải mã đối tượng CommitCertificate từ mảng byte tại vị trí offset."""
        height, cur = dec_uint(data, offset)
        block_hash, cur = dec_str(data, cur)
        round_num, cur = dec_uint(data, cur)
        votes, cur = dec_list(data, Vote.decode, cur)
        return cls(
            height=height,
            block_hash=block_hash,
            votes=votes,
            round=round_num,
        ), cur

    @classmethod
    def from_bytes(cls, data: bytes) -> CommitCertificate:
        """Giải mã hoàn chỉnh một CommitCertificate từ mảng byte."""
        cert, end_offset = cls.decode(data, 0)
        if end_offset != len(data):
            raise ValueError("Dữ liệu byte của CommitCertificate còn dư byte không hợp lệ")
        return cert

    def to_dict(self) -> dict[str, Any]:
        """Chuyển đổi CommitCertificate sang dict."""
        return {
            "height": self.height,
            "round": self.round,
            "block_hash": self.block_hash,
            "votes": [v.to_dict() for v in self.votes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommitCertificate:
        """Tạo đối tượng CommitCertificate từ dict."""
        votes = [
            v if isinstance(v, Vote) else Vote.from_dict(v)
            for v in data.get("votes", data.get("precommits", []))
        ]
        round_val = int(data["round"]) if "round" in data and data["round"] is not None else None
        return cls(
            height=int(data["height"]),
            block_hash=str(data["block_hash"]),
            votes=votes,
            round=round_val,
        )


def verify_commit_certificate(
    cert: CommitCertificate,
    validator_pubkeys: Mapping[str, bytes | str] | None = None,
    chain_id: str = DEFAULT_CHAIN_ID,
    quorum: int = DEFAULT_QUORUM,
    expected_height: int | None = None,
    expected_block_hash: str | None = None,
) -> tuple[bool, str | None]:
    """Hàm tiện ích kiểm tra tính hợp lệ của một CommitCertificate."""
    if not isinstance(cert, CommitCertificate):
        return False, BAD_SIGNATURE
    return cert.verify(
        validator_pubkeys=validator_pubkeys,
        chain_id=chain_id,
        quorum=quorum,
        expected_height=expected_height,
        expected_block_hash=expected_block_hash,
    )
