"""
View: dữ liệu đang chờ xử lý của height hiện tại trong một Node (Mục 4 & 12 README).

Lưu:
- proposal đã nhận theo round (kể cả proposal mâu thuẫn của proposer equivocate),
- header theo block_hash (lấy từ proposal) và body theo block_hash (nhận qua BODY),
- kết quả kiểm tra body theo block_hash (tránh thực thi lại),
- các BODY_REQUEST đã gửi,
- bộ đếm vote (VoteCounter) của height hiện tại,
- bộ đệm message của các height tương lai trong cửa sổ [hiện tại + 1, hiện tại + 5].

View không biết gì về mạng, đồng hồ hay luật đồng thuận; consensus.py quyết định
khi nào dùng từng thứ.
"""

from __future__ import annotations

from typing import Any

from src.core.block import Block
from src.core.header import Header
from src.core.proposal import Proposal
from src.core.transaction import Transaction
from src.node.vote_counter import DEFAULT_F_PLUS_ONE, DEFAULT_QUORUM, VoteCounter

DEFAULT_FUTURE_HEIGHT_WINDOW: int = 5
DEFAULT_MAX_BUFFERED_PER_HEIGHT: int = 2000

# Phân loại height của một message so với height hiện tại
PAST: str = "PAST"
CURRENT: str = "CURRENT"
BUFFER: str = "BUFFER"
TOO_FUTURE: str = "TOO_FUTURE"


class View:
    """Trạng thái tạm thời của height hiện tại cùng bộ đệm các height tương lai."""

    def __init__(
        self,
        height: int = 1,
        quorum: int = DEFAULT_QUORUM,
        f_plus_one: int = DEFAULT_F_PLUS_ONE,
        future_height_window: int = DEFAULT_FUTURE_HEIGHT_WINDOW,
        max_buffered_per_height: int = DEFAULT_MAX_BUFFERED_PER_HEIGHT,
    ) -> None:
        self.height: int = height
        self.future_height_window: int = future_height_window
        self.max_buffered_per_height: int = max_buffered_per_height
        self.votes: VoteCounter = VoteCounter(quorum=quorum, f_plus_one=f_plus_one)

        self._proposals: dict[int, list[Proposal]] = {}  # round -> proposal theo thứ tự đến
        self._headers: dict[str, Header] = {}  # block_hash -> header
        self._bodies: dict[str, list[Transaction]] = {}  # block_hash -> danh sách tx
        self._body_validity: dict[str, tuple[bool, str | None]] = {}
        self._body_requests: dict[str, list[str]] = {}  # block_hash -> peer đã được hỏi
        self._future: dict[int, list[tuple[str, Any]]] = {}  # height -> [(from_peer, message)]

    # ------------------------------------------------------------------
    # Phân loại height
    # ------------------------------------------------------------------
    def classify_height(self, height: int) -> str:
        """
        PAST: height < hiện tại (bỏ qua, dựa vào đồng bộ).
        CURRENT: xử lý ngay.
        BUFFER: nằm trong (hiện tại, hiện tại + window] (đệm lại).
        TOO_FUTURE: vượt cửa sổ (trả FUTURE_HEIGHT).
        """
        if height < self.height:
            return PAST
        if height == self.height:
            return CURRENT
        if height <= self.height + self.future_height_window:
            return BUFFER
        return TOO_FUTURE

    # ------------------------------------------------------------------
    # Proposal và header
    # ------------------------------------------------------------------
    def add_proposal(self, proposal: Proposal) -> bool:
        """
        Lưu proposal của height hiện tại. Trả False nếu sai height hoặc đã có
        proposal giống hệt (cùng round, block_hash, pol_round, proposer_id).
        """
        if proposal.height != self.height:
            return False
        existing = self._proposals.setdefault(proposal.round, [])
        for other in existing:
            if (
                other.block_hash == proposal.block_hash
                and other.pol_round == proposal.pol_round
                and other.proposer_id == proposal.proposer_id
            ):
                return False
        existing.append(proposal)
        self._headers.setdefault(proposal.block_hash, proposal.header)
        return True

    def proposals_for_round(self, round_num: int) -> list[Proposal]:
        """Các proposal đã nhận ở round này theo thứ tự đến (bản sao danh sách)."""
        return list(self._proposals.get(round_num, []))

    def get_proposal(self, round_num: int, block_hash: str | None = None) -> Proposal | None:
        """Proposal đầu tiên của round (hoặc đúng block_hash nếu truyền vào)."""
        for proposal in self._proposals.get(round_num, []):
            if block_hash is None or proposal.block_hash == block_hash:
                return proposal
        return None

    def proposal_rounds(self) -> list[int]:
        """Các round đã có proposal, tăng dần."""
        return sorted(self._proposals)

    def get_header(self, block_hash: str) -> Header | None:
        """Header của block_hash (lấy từ proposal đã nhận)."""
        return self._headers.get(block_hash)

    def register_header(self, header: Header) -> str:
        """Ghi header của block do chính node dựng (chưa qua proposal); trả về block_hash."""
        block_hash = str(header.block_hash())
        self._headers.setdefault(block_hash, header)
        return block_hash

    # ------------------------------------------------------------------
    # Body
    # ------------------------------------------------------------------
    def add_body(self, block_hash: str, transactions: list[Transaction]) -> bool:
        """Lưu body của block_hash. Trả False nếu đã có body cho hash này."""
        if block_hash in self._bodies:
            return False
        self._bodies[block_hash] = list(transactions)
        return True

    def has_body(self, block_hash: str) -> bool:
        return block_hash in self._bodies

    def get_body(self, block_hash: str) -> list[Transaction] | None:
        """Body (danh sách tx) của block_hash, hoặc None nếu chưa có."""
        body = self._bodies.get(block_hash)
        return list(body) if body is not None else None

    def get_block(self, block_hash: str) -> Block | None:
        """Ghép Block đầy đủ khi đã có cả header lẫn body, ngược lại None."""
        header = self._headers.get(block_hash)
        body = self._bodies.get(block_hash)
        if header is None or body is None:
            return None
        return Block(header=header, transactions=list(body))

    def set_body_validity(self, block_hash: str, ok: bool, reason: str | None = None) -> None:
        """Ghi kết quả kiểm tra body để không thực thi lại cùng một block."""
        self._body_validity[block_hash] = (ok, reason)

    def get_body_validity(self, block_hash: str) -> tuple[bool, str | None] | None:
        """(ok, reason) nếu đã kiểm tra, None nếu chưa."""
        return self._body_validity.get(block_hash)

    # ------------------------------------------------------------------
    # BODY_REQUEST đã gửi
    # ------------------------------------------------------------------
    def mark_body_requested(self, block_hash: str, peer: str) -> bool:
        """Ghi đã hỏi `peer` body của block_hash. Trả True nếu đây là lần đầu hỏi peer này."""
        peers = self._body_requests.setdefault(block_hash, [])
        if peer in peers:
            return False
        peers.append(peer)
        return True

    def body_requested_from(self, block_hash: str) -> list[str]:
        """Các peer đã được hỏi body của block_hash, theo thứ tự hỏi."""
        return list(self._body_requests.get(block_hash, []))

    # ------------------------------------------------------------------
    # Bộ đệm message tương lai
    # ------------------------------------------------------------------
    def buffer_future(self, height: int, from_peer: str, message: Any) -> bool:
        """
        Đệm message của height trong (hiện tại, hiện tại + window].
        Trả False nếu ngoài cửa sổ hoặc bộ đệm của height đó đã đầy.
        """
        if self.classify_height(height) != BUFFER:
            return False
        queue = self._future.setdefault(height, [])
        if len(queue) >= self.max_buffered_per_height:
            return False
        queue.append((from_peer, message))
        return True

    def buffered_count(self, height: int | None = None) -> int:
        """Số message đang đệm (của một height hoặc tất cả)."""
        if height is not None:
            return len(self._future.get(height, []))
        return sum(len(queue) for queue in self._future.values())

    # ------------------------------------------------------------------
    # Sang height mới
    # ------------------------------------------------------------------
    def advance(self, new_height: int) -> list[tuple[str, Any]]:
        """
        Chuyển sang height mới (có thể nhảy nhiều height khi đồng bộ):
        - Xóa proposal, header, body, kiểm tra body, vote của các height cũ.
        - Trả về các message đã đệm cho đúng new_height (theo thứ tự đến) để xử lý lại;
          message đệm của các height nhỏ hơn bị bỏ.
        """
        if new_height <= self.height:
            raise ValueError("new_height phải lớn hơn height hiện tại")
        self.height = new_height
        self._proposals.clear()
        self._headers.clear()
        self._bodies.clear()
        self._body_validity.clear()
        self._body_requests.clear()
        self.votes.prune_below(new_height)

        ready = self._future.pop(new_height, [])
        for stale in [h for h in self._future if h < new_height]:
            del self._future[stale]
        return ready