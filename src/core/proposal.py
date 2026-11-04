"""
Định nghĩa lớp Proposal (đề xuất một khối ở một round cụ thể, bao gồm cả đề xuất lại
khối đã khóa từ round trước) và các hàm kiểm tra proposer hợp lệ của round.

Cấu trúc PROPOSAL (Mục 3.4 & 6 README):
- height, round: chiều cao và vòng đồng thuận hiện tại
- block_hash: mã băm của khối được đề xuất
- pol_round: round đã thấy đủ 7 prevote cho block này, hoặc -1 nếu là block mới
- header: đối tượng Header kèm chữ ký người tạo ban đầu (domain HEADER)
- proposal_sig: chữ ký của proposer ở round hiện tại (domain PROPOSAL)
  trên bộ 4 trường (height, round, block_hash, pol_round).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.core.header import DEFAULT_CHAIN_ID, Header
from src.crypto.domain import BAD_SIGNATURE, PROPOSAL, WRONG_CHAIN
from src.crypto.encoding import dec_bytes, dec_int, dec_str, dec_uint, enc_bytes, enc_str, enc_uint
from src.crypto.hashing import to_canonical_hash_str
from src.crypto.signing import sign as crypto_sign, verify as crypto_verify
from src.node.proposer import (
    DEFAULT_NUM_VALIDATORS,
    expected_proposer_id,
    get_proposer,
    is_expected_proposer,
    is_proposer,
    normalize_validator_id,
    proposer_index,
)

REASON_NOT_PROPOSER: str = "NOT_PROPOSER"


@dataclass
class Proposal:
    """
    Lớp biểu diễn thông điệp đề xuất khối (PROPOSAL) trong một vòng đồng thuận.
    Người tạo khối (header.proposer_id) và người đề xuất ở round hiện tại (proposer_id)
    trùng nhau khi tạo khối mới (pol_round == -1), nhưng có thể khác nhau khi đề xuất lại
    khối đã khóa từ round trước (pol_round >= 0).
    """

    height: int
    round: int
    block_hash: str
    pol_round: int
    header: Header
    proposal_sig: bytes = b""
    proposer_id: str = ""

    def __post_init__(self) -> None:
        """Chuẩn hóa block_hash, chữ ký proposal_sig và proposer_id."""
        self.block_hash = to_canonical_hash_str(self.block_hash)
        if not self.block_hash and self.header is not None:
            self.block_hash = str(self.header.block_hash())

        if isinstance(self.proposal_sig, str):
            self.proposal_sig = bytes.fromhex(self.proposal_sig) if self.proposal_sig else b""
        elif isinstance(self.proposal_sig, (bytearray, memoryview)):
            self.proposal_sig = bytes(self.proposal_sig)

        # Nếu không truyền proposer_id riêng thì mặc định:
        # - Khi pol_round == -1 (block mới): lấy theo header.proposer_id
        # - Khi đề xuất lại mà chưa gán: để trống để suy từ (height, round) hoặc header
        if not self.proposer_id and self.pol_round == -1 and self.header is not None:
            self.proposer_id = self.header.proposer_id

    @property
    def signature(self) -> bytes:
        """Bí danh cho proposal_sig."""
        return self.proposal_sig

    @signature.setter
    def signature(self, value: bytes) -> None:
        self.proposal_sig = value

    def signing_fields(self) -> tuple[int, int, str, int]:
        """
        Trả về tuple các trường được ký theo thứ tự cố định của domain PROPOSAL (Mục 6 README):
        (height, round, block_hash, pol_round).
        """
        return (
            self.height,
            self.round,
            self.block_hash,
            self.pol_round,
        )

    def sign(
        self,
        private_key: bytes | str,
        chain_id: str | None = None,
        proposer_id: str | None = None,
    ) -> bytes:
        """Ký đề xuất bằng khóa bí mật của proposer của round hiện tại trên domain PROPOSAL."""
        if proposer_id is not None:
            self.proposer_id = proposer_id
        target_chain = chain_id if chain_id is not None else self.header.chain_id
        self.proposal_sig = crypto_sign(private_key, PROPOSAL, target_chain, self.signing_fields())
        return self.proposal_sig

    def verify_proposal_sig(
        self,
        public_key: bytes | str,
        chain_id: str | None = None,
    ) -> tuple[bool, str | None]:
        """Xác minh chữ ký proposal_sig trên domain PROPOSAL."""
        target_chain = chain_id if chain_id is not None else self.header.chain_id
        return crypto_verify(public_key, PROPOSAL, target_chain, self.signing_fields(), self.proposal_sig)

    def verify_proposer_and_sig(
        self,
        validator_pubkeys: Mapping[str, bytes | str] | None = None,
        chain_id: str = DEFAULT_CHAIN_ID,
        sender_id: str | int | None = None,
        n: int = DEFAULT_NUM_VALIDATORS,
        validators: Sequence[str] | None = None,
    ) -> tuple[bool, str | None]:
        """
        Kiểm tra toàn diện proposer đúng của round và chữ ký proposal_sig:
        1. Kiểm tra chain_id của header khớp chain_id mong đợi (WRONG_CHAIN).
        2. Tính proposer kỳ vọng của (height, round): expected = N_{(height + round) mod n}.
        3. Kiểm tra proposer_id (và header.proposer_id nếu pol_round == -1) có đúng là
           expected hay không (nếu sai trả về NOT_PROPOSER).
        4. Xác minh chữ ký proposal_sig bằng khóa công khai của expected proposer (nếu có validator_pubkeys):
           - Nếu thất bại với WRONG_DOMAIN -> trả về WRONG_DOMAIN.
           - Nếu thất bại với BAD_SIGNATURE: chỉ trả về NOT_PROPOSER khi sender_id != expected
             và sender_id thực sự là người đã ký proposal_sig bằng khóa riêng của sender_id;
             ngược lại trả về BAD_SIGNATURE (tránh báo nhầm NOT_PROPOSER khi proposal của đúng
             proposer bị hỏng chữ ký nhưng được chuyển tiếp qua hop trung gian).
        5. Kiểm tra pol_round hợp lệ (-1 <= pol_round < round) và block_hash khớp header.block_hash().
        """
        if self.header.chain_id != chain_id:
            return False, WRONG_CHAIN

        exp_proposer = expected_proposer_id(self.height, self.round, n=n, validators=validators)

        # Nếu proposer_id được gắn tường minh trong Proposal mà khác proposer kỳ vọng của round -> NOT_PROPOSER
        if self.proposer_id:
            norm_prop = (
                self.proposer_id
                if (validators is not None and self.proposer_id in validators)
                else normalize_validator_id(self.proposer_id)
            )
            if norm_prop != exp_proposer:
                return False, REASON_NOT_PROPOSER

        # Nếu là khối mới (pol_round == -1) thì người tạo khối trong header cũng phải là proposer của round
        if self.pol_round == -1 and self.header.proposer_id != exp_proposer:
            return False, REASON_NOT_PROPOSER

        if validator_pubkeys is not None:
            if exp_proposer not in validator_pubkeys:
                return False, REASON_NOT_PROPOSER

            ok, reason = self.verify_proposal_sig(validator_pubkeys[exp_proposer], chain_id=chain_id)
            if not ok:
                if reason == "WRONG_DOMAIN":
                    return False, reason
                if sender_id is not None:
                    norm_sender = (
                        str(sender_id)
                        if str(sender_id) in validator_pubkeys
                        else normalize_validator_id(sender_id)
                    )
                    if norm_sender != exp_proposer and norm_sender in validator_pubkeys:
                        ok_sender, _ = self.verify_proposal_sig(
                            validator_pubkeys[norm_sender],
                            chain_id=chain_id,
                        )
                        if ok_sender:
                            return False, REASON_NOT_PROPOSER
                return False, reason

        # pol_round phải là -1 hoặc một round nhỏ hơn round hiện tại
        if self.pol_round < -1 or (self.pol_round >= 0 and self.pol_round >= self.round):
            return False, BAD_SIGNATURE

        if self.block_hash != str(self.header.block_hash()):
            return False, BAD_SIGNATURE

        return True, None

    def encode(self) -> bytes:
        """Mã hóa chuẩn đối tượng Proposal thành mảng byte."""
        return (
            enc_uint(self.height)
            + enc_uint(self.round)
            + enc_str(self.block_hash)
            + enc_uint(self.pol_round)
            + self.header.encode()
            + enc_bytes(self.proposal_sig)
            + enc_str(self.proposer_id)
        )

    to_bytes = encode

    @classmethod
    def decode(cls, data: bytes, offset: int = 0) -> tuple[Proposal, int]:
        """Giải mã đối tượng Proposal từ mảng byte tại vị trí offset."""
        height, cur = dec_uint(data, offset)
        round_num, cur = dec_uint(data, cur)
        block_hash, cur = dec_str(data, cur)
        pol_round, cur = dec_int(data, cur)
        header, cur = Header.decode(data, cur)
        proposal_sig, cur = dec_bytes(data, cur)
        proposer_id = ""
        if cur < len(data):
            proposer_id, cur = dec_str(data, cur)
        return cls(
            height=height,
            round=round_num,
            block_hash=block_hash,
            pol_round=pol_round,
            header=header,
            proposal_sig=proposal_sig,
            proposer_id=proposer_id,
        ), cur

    @classmethod
    def from_bytes(cls, data: bytes) -> Proposal:
        """Giải mã hoàn chỉnh một Proposal từ mảng byte."""
        proposal, end_offset = cls.decode(data, 0)
        if end_offset != len(data):
            raise ValueError("Dữ liệu byte của Proposal còn dư byte không hợp lệ")
        return proposal

    def to_dict(self) -> dict[str, Any]:
        """Chuyển đổi Proposal sang dict."""
        return {
            "height": self.height,
            "round": self.round,
            "block_hash": self.block_hash,
            "pol_round": self.pol_round,
            "header": self.header.to_dict(),
            "proposal_sig": self.proposal_sig.hex(),
            "proposer_id": self.proposer_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Proposal:
        """Tạo đối tượng Proposal từ dict."""
        sig = data.get("proposal_sig", data.get("signature", b""))
        if isinstance(sig, str):
            sig = bytes.fromhex(sig) if sig else b""
        header = data["header"]
        if not isinstance(header, Header):
            header = Header.from_dict(header)
        return cls(
            height=int(data["height"]),
            round=int(data["round"]),
            block_hash=str(data.get("block_hash", header.block_hash())),
            pol_round=int(data.get("pol_round", -1)),
            header=header,
            proposal_sig=sig,
            proposer_id=str(data.get("proposer_id", "")),
        )
