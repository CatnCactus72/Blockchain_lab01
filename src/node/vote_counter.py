"""
Bộ đếm phiếu bầu (VoteCounter) của một Node trong Chat Chain.

Quy tắc (Mục 4 README, "Đếm vote"):
- Mỗi (validator, height, round, phase) chỉ tính vote hợp lệ ĐẦU TIÊN.
- Cùng nội dung đến lần nữa  -> bỏ qua, trả DUPLICATE (reason DUPLICATE_VOTE).
- Khác nội dung của cùng validator -> từ chối, không chuyển tiếp, lưu bằng chứng
  (reason CONFLICTING_VOTE).
- Quorum = 7/10 cho: một block cụ thể, NIL, hoặc "bất kỳ" (không cần cùng giá trị).
- Nhảy round: thấy f+1 = 4 validator khác nhau đã bỏ phiếu ở round cao hơn.

Lớp này KHÔNG kiểm tra chữ ký hay tư cách validator; việc đó do validate_vote()
làm trước khi gọi add(). Lớp này cũng không biết gì về mạng hay đồng hồ.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from src.core.vote import (
    PRECOMMIT,
    REASON_CONFLICTING_VOTE,
    REASON_DUPLICATE_VOTE,
    VALID_PHASES,
    CommitCertificate,
    Vote,
)

DEFAULT_QUORUM: int = 7
DEFAULT_F_PLUS_ONE: int = 4

# Trạng thái kết quả của add()
ADDED: str = "ADDED"
DUPLICATE: str = "DUPLICATE"
CONFLICT: str = "CONFLICT"


def _normalize_hash(block_hash: str | None) -> str | None:
    """None, '' hoặc 'NIL' đều là NIL (None); còn lại là hex chữ thường."""
    if block_hash is None or block_hash == "" or block_hash == "NIL":
        return None
    return str(block_hash).lower()


def _validator_sort_key(validator_id: str) -> tuple[int, int, str]:
    """Sắp validator theo số thứ tự (N2 trước N10), id lạ xếp cuối theo chuỗi."""
    text = str(validator_id)
    if text.startswith("N") and text[1:].isdigit():
        return (0, int(text[1:]), "")
    return (1, 0, text)


@dataclass
class AddResult:
    """Kết quả của VoteCounter.add()."""

    status: str
    vote: Vote
    previous: Vote | None = None

    @property
    def added(self) -> bool:
        return self.status == ADDED

    @property
    def is_duplicate(self) -> bool:
        return self.status == DUPLICATE

    @property
    def is_conflict(self) -> bool:
        return self.status == CONFLICT

    @property
    def reason(self) -> str | None:
        """Mã lý do theo đặc tả (None nếu vote được tính)."""
        if self.status == DUPLICATE:
            return REASON_DUPLICATE_VOTE
        if self.status == CONFLICT:
            return REASON_CONFLICTING_VOTE
        return None


class VoteCounter:
    """Đếm vote theo (height, round, phase), chống trùng và mâu thuẫn."""

    def __init__(
        self,
        quorum: int = DEFAULT_QUORUM,
        f_plus_one: int = DEFAULT_F_PLUS_ONE,
    ) -> None:
        if quorum <= 0 or f_plus_one <= 0:
            raise ValueError("quorum và f_plus_one phải dương")
        self.quorum: int = quorum
        self.f_plus_one: int = f_plus_one
        # (height, round, phase) -> {validator_id: Vote đầu tiên}
        self._votes: dict[tuple[int, int, str], dict[str, Vote]] = {}
        # height -> {validator_id: round cao nhất validator đó từng bỏ phiếu}
        self._max_round: dict[int, dict[str, int]] = {}
        # Bằng chứng equivocation: (vote đã tính, vote mâu thuẫn)
        self._evidence: list[tuple[Vote, Vote]] = []

    # ------------------------------------------------------------------
    # Thêm vote
    # ------------------------------------------------------------------
    def add(self, vote: Vote) -> AddResult:
        """
        Ghi nhận một vote ĐÃ được kiểm tra hợp lệ (chữ ký, validator, phase).
        Trả về AddResult với status ADDED, DUPLICATE hoặc CONFLICT.
        """
        if vote.phase not in VALID_PHASES:
            raise ValueError(f"phase không hợp lệ: {vote.phase}")

        slot = self._votes.setdefault((vote.height, vote.round, vote.phase), {})
        previous = slot.get(vote.validator_id)
        if previous is not None:
            if previous.block_hash == vote.block_hash:
                return AddResult(DUPLICATE, vote, previous)
            self._evidence.append((previous, vote))
            return AddResult(CONFLICT, vote, previous)

        slot[vote.validator_id] = vote
        rounds = self._max_round.setdefault(vote.height, {})
        if vote.round > rounds.get(vote.validator_id, -1):
            rounds[vote.validator_id] = vote.round
        return AddResult(ADDED, vote)

    def has_vote(self, validator_id: str, height: int, round_num: int, phase: str) -> bool:
        """Validator này đã có vote được tính ở (height, round, phase) chưa."""
        return validator_id in self._votes.get((height, round_num, phase), {})

    def get_vote(
        self, validator_id: str, height: int, round_num: int, phase: str
    ) -> Vote | None:
        """Lấy vote đã được tính của validator ở (height, round, phase)."""
        return self._votes.get((height, round_num, phase), {}).get(validator_id)

    # ------------------------------------------------------------------
    # Đếm
    # ------------------------------------------------------------------
    def count_for(
        self, height: int, round_num: int, phase: str, block_hash: str | None
    ) -> int:
        """Số vote cho đúng block_hash này (block_hash None = NIL)."""
        target = _normalize_hash(block_hash)
        slot = self._votes.get((height, round_num, phase), {})
        return sum(1 for vote in slot.values() if vote.block_hash == target)

    def count_nil(self, height: int, round_num: int, phase: str) -> int:
        """Số vote NIL."""
        return self.count_for(height, round_num, phase, None)

    def count_any(self, height: int, round_num: int, phase: str) -> int:
        """Tổng số vote hợp lệ (bất kể giá trị)."""
        return len(self._votes.get((height, round_num, phase), {}))

    def tally(self, height: int, round_num: int, phase: str) -> dict[str | None, int]:
        """Bảng đếm {block_hash hoặc None(NIL): số vote}, sắp theo số vote giảm dần rồi theo hash."""
        counts: dict[str | None, int] = {}
        for vote in self._votes.get((height, round_num, phase), {}).values():
            counts[vote.block_hash] = counts.get(vote.block_hash, 0) + 1
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0] is None, kv[0] or ""))
        return dict(ordered)

    # ------------------------------------------------------------------
    # Quorum
    # ------------------------------------------------------------------
    def has_quorum_for(
        self, height: int, round_num: int, phase: str, block_hash: str | None
    ) -> bool:
        """Có >= quorum vote cho đúng block_hash (None = NIL) không."""
        return self.count_for(height, round_num, phase, block_hash) >= self.quorum

    def has_quorum_nil(self, height: int, round_num: int, phase: str) -> bool:
        """Có >= quorum vote NIL không."""
        return self.count_nil(height, round_num, phase) >= self.quorum

    def has_quorum_any(self, height: int, round_num: int, phase: str) -> bool:
        """Có >= quorum vote bất kỳ (dù không cùng giá trị) không."""
        return self.count_any(height, round_num, phase) >= self.quorum

    def quorum_block(self, height: int, round_num: int, phase: str) -> str | None:
        """
        block_hash (khác NIL) đang có >= quorum vote ở (height, round, phase), hoặc None.
        Vì mỗi validator chỉ được tính một vote mỗi slot, tối đa một block đạt quorum.
        """
        for block_hash, count in self.tally(height, round_num, phase).items():
            if block_hash is not None and count >= self.quorum:
                return block_hash
        return None

    def precommit_quorum_any_round(self, height: int) -> tuple[int, str] | None:
        """
        Finalize: tìm (round, block_hash) có >= quorum PRECOMMIT cùng một block
        ở MỘT round bất kỳ của height này (round nhỏ nhất trước). None nếu chưa có.
        """
        rounds = sorted(r for (h, r, phase) in self._votes if h == height and phase == PRECOMMIT)
        for round_num in rounds:
            block_hash = self.quorum_block(height, round_num, PRECOMMIT)
            if block_hash is not None:
                return round_num, block_hash
        return None

    # ------------------------------------------------------------------
    # Nhảy round (f+1)
    # ------------------------------------------------------------------
    def round_to_skip_to(self, height: int, current_round: int) -> int | None:
        """
        Round cao nhất R > current_round mà ít nhất f+1 validator khác nhau đã bỏ phiếu
        ở round >= R (trong cùng height). Trả None nếu chưa đủ f+1.
        """
        per_validator = self._max_round.get(height, {})
        best = sorted(per_validator.values(), reverse=True)
        if len(best) < self.f_plus_one:
            return None
        candidate = best[self.f_plus_one - 1]
        return candidate if candidate > current_round else None

    # ------------------------------------------------------------------
    # Truy xuất vote (certificate, GET_VOTES/VOTES)
    # ------------------------------------------------------------------
    def votes_for(
        self, height: int, round_num: int, phase: str, block_hash: str | None
    ) -> list[Vote]:
        """Các vote cho đúng block_hash, sắp theo thứ tự validator."""
        target = _normalize_hash(block_hash)
        slot = self._votes.get((height, round_num, phase), {})
        return [
            slot[vid]
            for vid in sorted(slot, key=_validator_sort_key)
            if slot[vid].block_hash == target
        ]

    def votes_in_round(self, height: int, round_num: int) -> list[Vote]:
        """Mọi vote đã được tính của (height, round): PREVOTE trước, rồi PRECOMMIT, mỗi nhóm theo validator."""
        result: list[Vote] = []
        for phase in sorted(VALID_PHASES, reverse=True):  # PREVOTE > PRECOMMIT theo chữ cái giảm dần
            slot = self._votes.get((height, round_num, phase), {})
            result.extend(slot[vid] for vid in sorted(slot, key=_validator_sort_key))
        return result

    def validators_voted(self, height: int, round_num: int, phase: str) -> list[str]:
        """Danh sách validator đã có vote được tính ở (height, round, phase)."""
        return sorted(self._votes.get((height, round_num, phase), {}), key=_validator_sort_key)

    def build_certificate(
        self, height: int, round_num: int, block_hash: str
    ) -> CommitCertificate | None:
        """
        Dựng CommitCertificate từ đúng `quorum` PRECOMMIT đầu tiên (theo thứ tự validator)
        cho block_hash ở (height, round). Trả None nếu chưa đủ quorum.
        """
        votes = self.votes_for(height, round_num, PRECOMMIT, block_hash)
        if len(votes) < self.quorum:
            return None
        return CommitCertificate(
            height=height,
            block_hash=str(block_hash),
            votes=votes[: self.quorum],
            round=round_num,
        )

    # ------------------------------------------------------------------
    # Bằng chứng, dọn dẹp
    # ------------------------------------------------------------------
    @property
    def evidence(self) -> list[tuple[Vote, Vote]]:
        """Các cặp vote mâu thuẫn đã phát hiện (bản sao danh sách)."""
        return list(self._evidence)

    def conflicting_validators(self) -> list[str]:
        """Danh sách validator bị phát hiện equivocate (không trùng, có thứ tự)."""
        seen: set[str] = set()
        for first, _ in self._evidence:
            seen.add(first.validator_id)
        return sorted(seen, key=_validator_sort_key)

    def heights(self) -> list[int]:
        """Các height đang có dữ liệu vote."""
        return sorted({h for (h, _, _) in self._votes})

    def prune_below(self, height: int) -> None:
        """Xóa toàn bộ vote của các height < height."""
        for key in [k for k in self._votes if k[0] < height]:
            del self._votes[key]
        for h in [h for h in self._max_round if h < height]:
            del self._max_round[h]

    def clear(self) -> None:
        """Xóa toàn bộ dữ liệu."""
        self._votes.clear()
        self._max_round.clear()
        self._evidence.clear()


def extend_counter(counter: VoteCounter, votes: Iterable[Vote]) -> list[AddResult]:
    """Hàm tiện ích: thêm nhiều vote và trả danh sách kết quả theo thứ tự."""
    return [counter.add(vote) for vote in votes]