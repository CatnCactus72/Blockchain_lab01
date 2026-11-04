"""
Sổ cái (Ledger) lưu trữ chuỗi các khối (Block) đã finalize kèm chứng nhận cam kết
(CommitCertificate) của một Node trong Chat Chain.

Quy tắc hoạt động của Ledger (Mục 3.5, 4 & 12 README):
- Khởi tạo sẵn khối khởi nguyên (Genesis Block) ở height 0.
- Chỉ cho phép nối thêm (append) khối mới ở height tiếp theo (latest_height + 1)
  khi khối đó nối đúng vào parent_hash của khối trước và có CommitCertificate hợp lệ
  (đủ 7 phiếu PRECOMMIT hợp lệ cho cùng block_hash và height).
- Cung cấp các phương thức truy vấn: append(block, certificate), get(height), latest(),
  get_certificate(height), get_entry(height), get_range(from_height, to_height).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from src.core.block import Block, make_genesis_block
from src.core.header import DEFAULT_CHAIN_ID
from src.core.vote import DEFAULT_QUORUM, CommitCertificate
from src.crypto.hashing import HashHex
from src.node.validation import (
    BAD_PARENT,
    BAD_SIGNATURE,
    WRONG_CHAIN,
    validate_commit_certificate,
)


@dataclass
class LedgerEntry:
    """
    Một mục trong sổ cái gồm cặp (Block đã finalize, CommitCertificate chứng nhận).
    Với khối Genesis (height 0), certificate là None.
    """

    block: Block
    certificate: CommitCertificate | None = None

    @property
    def height(self) -> int:
        return self.block.height

    @property
    def block_hash(self) -> HashHex:
        return self.block.block_hash()


class Ledger:
    """
    Sổ cái lưu chuỗi khối đã finalize của một Node.
    Đảm bảo bất biến an toàn: mọi khối từ height >= 1 trong sổ cái đều đi kèm
    một chứng nhận CommitCertificate đã được xác minh đủ quorum (7 precommit).
    """

    def __init__(
        self,
        chain_id: str = DEFAULT_CHAIN_ID,
        validator_pubkeys: Mapping[str, bytes | str] | None = None,
        quorum: int = DEFAULT_QUORUM,
        genesis_block: Block | None = None,
    ) -> None:
        self.chain_id: str = chain_id
        self.validator_pubkeys: dict[str, bytes | str] | None = (
            dict(validator_pubkeys) if validator_pubkeys is not None else None
        )
        self.quorum: int = quorum

        genesis = genesis_block if genesis_block is not None else make_genesis_block(chain_id=chain_id)
        self._entries: dict[int, LedgerEntry] = {
            0: LedgerEntry(block=genesis, certificate=None),
        }
        self._latest_height: int = 0

    @property
    def latest_height(self) -> int:
        """Chiều cao của khối finalize mới nhất trong sổ cái (ban đầu là 0 - Genesis)."""
        return self._latest_height

    def height(self) -> int:
        """Trả về chiều cao hiện tại của sổ cái."""
        return self._latest_height

    def latest(self) -> Block:
        """Trả về đối tượng Block đã finalize mới nhất trong sổ cái."""
        return self._entries[self._latest_height].block

    def latest_entry(self) -> LedgerEntry:
        """Trả về mục LedgerEntry (Block + Certificate) mới nhất."""
        return self._entries[self._latest_height]

    def latest_hash(self) -> HashHex:
        """Trả về mã băm block_hash của khối finalize mới nhất."""
        return self.latest().block_hash()

    def get(self, height: int) -> Block | None:
        """Lấy khối đã finalize ở chiều cao height (trả về None nếu chưa có)."""
        entry = self._entries.get(int(height))
        return entry.block if entry is not None else None

    def get_certificate(self, height: int) -> CommitCertificate | None:
        """Lấy chứng nhận CommitCertificate của khối ở chiều cao height."""
        entry = self._entries.get(int(height))
        return entry.certificate if entry is not None else None

    def get_entry(self, height: int) -> LedgerEntry | None:
        """Lấy cặp (Block, CommitCertificate) ở chiều cao height."""
        return self._entries.get(int(height))

    def get_range(self, from_height: int, to_height: int) -> list[LedgerEntry]:
        """
        Lấy danh sách các mục LedgerEntry liên tiếp trong đoạn [from_height, to_height]
        (phục vụ phản hồi gói tin đồng bộ GET_BLOCKS).
        """
        start = max(0, int(from_height))
        end = min(self._latest_height, int(to_height))
        if start > end:
            return []
        result: list[LedgerEntry] = []
        for h in range(start, end + 1):
            entry = self._entries.get(h)
            if entry is not None:
                result.append(entry)
        return result

    def append(
        self,
        block: Block,
        certificate: CommitCertificate | None,
        validator_pubkeys: Mapping[str, bytes | str] | None = None,
        quorum: int | None = None,
    ) -> tuple[bool, str | None]:
        """
        Thêm một khối mới vào sổ cái sau khi kiểm tra nghiêm ngặt:
        1. chain_id của khối khớp với chain_id của sổ cái (WRONG_CHAIN).
        2. height của khối phải bằng latest_height + 1 và parent_hash phải khớp với
           block_hash của khối finalize cuối cùng (BAD_PARENT).
        3. Chứng nhận CommitCertificate phải tồn tại và hợp lệ (đủ 7 phiếu PRECOMMIT hợp lệ
           cho đúng height và block_hash của khối).
        Trả về (True, None) nếu ghi thành công, hoặc (False, reason) nếu bị từ chối.
        """
        if block.chain_id != self.chain_id:
            return False, WRONG_CHAIN

        expected_height = self._latest_height + 1
        parent_block = self.latest()
        if block.height != expected_height:
            return False, BAD_PARENT
        if block.parent_hash != str(parent_block.block_hash()):
            return False, BAD_PARENT

        if certificate is None:
            return False, BAD_SIGNATURE

        pubkeys = validator_pubkeys if validator_pubkeys is not None else self.validator_pubkeys
        req_quorum = quorum if quorum is not None else self.quorum

        ok_cert, cert_reason = validate_commit_certificate(
            certificate=certificate,
            validator_pubkeys=pubkeys,
            chain_id=self.chain_id,
            quorum=req_quorum,
            expected_height=block.height,
            expected_block_hash=str(block.block_hash()),
        )
        if not ok_cert:
            return False, cert_reason

        self._entries[block.height] = LedgerEntry(block=block, certificate=certificate)
        self._latest_height = block.height
        return True, None

    def all_blocks(self, include_genesis: bool = True) -> list[Block]:
        """Trả về danh sách tất cả các khối đã finalize theo thứ tự chiều cao tăng dần."""
        start_h = 0 if include_genesis else 1
        return [
            self._entries[h].block
            for h in range(start_h, self._latest_height + 1)
            if h in self._entries
        ]

    def summary_chain(self) -> list[tuple[int, str]]:
        """Trả về danh sách (height, block_hash) của toàn bộ chuỗi đã finalize."""
        return [
            (h, str(self._entries[h].block.block_hash()))
            for h in range(0, self._latest_height + 1)
            if h in self._entries
        ]

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[Block]:
        return iter(self.all_blocks(include_genesis=True))
