"""
Hàm chọn proposer theo vòng tròn xác định (round-robin) cho từng cặp (height, round)
và kiểm tra xem một node có phải là proposer hợp lệ của (height, round) hay không.

Quy tắc chọn proposer (Mục 4 & 12 README):
- Với tập n validator cố định (mặc định n = 10, N0..N9):
  chỉ số proposer = (height + round) mod n
  định danh proposer = f"N{(height + round) % n}" (hoặc phần tử tương ứng trong danh sách validators).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# Số lượng validator mặc định của mạng (N0..N9)
DEFAULT_NUM_VALIDATORS: int = 10


def normalize_validator_id(node_id: str | int) -> str:
    """
    Chuẩn hóa định danh validator về dạng 'N<i>' (ví dụ: 3 -> 'N3', '3' -> 'N3', 'n3' -> 'N3', 'N3' -> 'N3').
    Nếu định danh là tên tùy chỉnh khác thì giữ nguyên chuỗi đã cắt khoảng trắng.
    """
    if isinstance(node_id, bool):
        raise TypeError("Định danh validator không được là kiểu bool")
    if isinstance(node_id, int):
        return f"N{node_id}"
    raw = str(node_id).strip()
    if raw.isdigit():
        return f"N{int(raw)}"
    if raw.upper().startswith("N") and raw[1:].isdigit():
        return f"N{int(raw[1:])}"
    return raw


def proposer_index(
    height: int,
    round_num: int | None = None,
    n: int | Sequence[str] = DEFAULT_NUM_VALIDATORS,
    *,
    round: int | None = None,
) -> int:
    """
    Tính chỉ số (index) của proposer cho cặp (height, round) theo công thức:
        index = (height + round) mod n
    Hỗ trợ truyền vòng đồng thuận qua tham số vị trí `round_num` hoặc từ khóa `round`,
    và hỗ trợ truyền `n` là số nguyên hoặc danh sách validators.
    """
    r = round if round_num is None and round is not None else (0 if round_num is None else round_num)
    if isinstance(height, bool) or isinstance(r, bool) or isinstance(n, bool):
        raise TypeError("height, round và n không được là kiểu bool")
    if isinstance(n, Sequence) and not isinstance(n, (str, bytes, bytearray)):
        actual_n = len(n)
    else:
        actual_n = int(n)
    if actual_n <= 0:
        raise ValueError(f"Số lượng validator n phải lớn hơn 0, nhận được: {actual_n}")
    if int(height) < 0 or int(r) < 0:
        raise ValueError(f"height và round không được âm: height={height}, round={r}")
    return (int(height) + int(r)) % actual_n


def expected_proposer_id(
    height: int,
    round_num: int | None = None,
    n: int | Sequence[str] = DEFAULT_NUM_VALIDATORS,
    validators: Sequence[str] | None = None,
    *,
    round: int | None = None,
) -> str:
    """
    Xác định định danh validator làm proposer cho cặp (height, round) theo công thức:
        proposer_index = (height + round) mod n (Mục 4 & 12 README).
    Nếu truyền danh sách `validators` (qua tham số `validators` hoặc vị trí thứ 3 `n`)
    thì lấy phần tử tại vị trí `proposer_index`, ngược lại trả về chuỗi định danh chuẩn `f"N{idx}"`.
    """
    r = round if round_num is None and round is not None else (0 if round_num is None else round_num)
    if validators is None and isinstance(n, Sequence) and not isinstance(n, (str, bytes, bytearray)):
        validators = n
    if validators is not None and len(validators) > 0:
        idx = proposer_index(height, r, n=len(validators))
        return str(validators[idx])
    actual_n = DEFAULT_NUM_VALIDATORS if isinstance(n, Sequence) else int(n)
    idx = proposer_index(height, r, n=actual_n)
    return f"N{idx}"


# Các bí danh thông dụng để thuận tiện tích hợp với consensus.py, block_builder.py và validation.py
get_proposer = expected_proposer_id
get_proposer_id = expected_proposer_id
select_proposer = expected_proposer_id
proposer_for = expected_proposer_id


def is_expected_proposer(
    node_id: str | int | None = None,
    height: int = 0,
    round_num: int | str | None = None,
    n: int | Sequence[str] = DEFAULT_NUM_VALIDATORS,
    validators: Sequence[str] | None = None,
    *,
    round: int | None = None,
    validator_id: str | int | None = None,
    proposer_id: str | int | None = None,
) -> bool:
    """
    Kiểm tra xem `node_id` có phải là proposer hợp lệ của cặp (height, round) hay không.
    Hỗ trợ cả kiểu truyền chuẩn `(node_id, height, round)` lẫn `(height, round, node_id)`
    khi `node_id` là chuỗi định danh validator, cũng như truyền qua từ khóa `validator_id`/`proposer_id`.
    """
    if validators is None and isinstance(n, Sequence) and not isinstance(n, (str, bytes, bytearray)):
        validators = n
        actual_n = len(validators) if len(validators) > 0 else DEFAULT_NUM_VALIDATORS
    else:
        actual_n = int(n) if not isinstance(n, Sequence) else DEFAULT_NUM_VALIDATORS

    if node_id is None:
        node_id = validator_id if validator_id is not None else proposer_id
    if node_id is None:
        raise ValueError("Cần cung cấp node_id (hoặc validator_id / proposer_id)")

    # Hỗ trợ trường hợp gọi is_proposer(height, round, node_id) với node_id là chuỗi 'N...'
    if (
        isinstance(node_id, int)
        and not isinstance(node_id, bool)
        and isinstance(height, int)
        and not isinstance(height, bool)
        and isinstance(round_num, str)
    ):
        actual_height = node_id
        actual_round = height
        candidate = round_num
        if validators is not None and candidate in validators:
            norm_candidate = candidate
        else:
            norm_candidate = normalize_validator_id(candidate)
        return norm_candidate == expected_proposer_id(
            actual_height,
            actual_round,
            n=actual_n,
            validators=validators,
        )

    r = round if round_num is None and round is not None else (0 if round_num is None else int(round_num))
    if validators is not None and str(node_id) in validators:
        norm_node = str(node_id)
    else:
        norm_node = normalize_validator_id(node_id)
    exp_id = expected_proposer_id(height, r, n=actual_n, validators=validators)
    return norm_node == exp_id


# Các bí danh cho hàm kiểm tra proposer
is_proposer = is_expected_proposer
check_proposer = is_expected_proposer


@dataclass(frozen=True)
class ProposerSelector:
    """
    Lớp tiện ích quản lý lịch chọn proposer xác định theo cấu hình số lượng validator `n`
    hoặc danh sách định danh `validators`.
    """

    n: int = DEFAULT_NUM_VALIDATORS
    validators: tuple[str, ...] | None = None

    def __init__(
        self,
        n: int | Sequence[str] = DEFAULT_NUM_VALIDATORS,
        validators: Sequence[str] | None = None,
    ) -> None:
        if validators is None and isinstance(n, Sequence) and not isinstance(n, (str, bytes, bytearray)):
            validators = n
            n = len(validators) if len(validators) > 0 else DEFAULT_NUM_VALIDATORS
        val_tuple = tuple(str(v) for v in validators) if validators is not None else None
        actual_n = len(val_tuple) if val_tuple else int(n)  # type: ignore[arg-type]
        if actual_n <= 0:
            raise ValueError(f"Số lượng validator n phải lớn hơn 0, nhận được: {actual_n}")
        object.__setattr__(self, "n", actual_n)
        object.__setattr__(self, "validators", val_tuple)

    def index(self, height: int, round_num: int = 0) -> int:
        """Trả về chỉ số proposer (height + round) mod n."""
        return proposer_index(height, round_num, n=self.n)

    def get_proposer(self, height: int, round_num: int = 0) -> str:
        """Trả về định danh proposer của (height, round)."""
        return expected_proposer_id(
            height,
            round_num,
            n=self.n,
            validators=self.validators,
        )

    proposer_for = get_proposer

    def is_proposer(self, node_id: str | int, height: int, round_num: int = 0) -> bool:
        """Kiểm tra node_id có phải proposer của (height, round) hay không."""
        return is_expected_proposer(
            node_id,
            height,
            round_num,
            n=self.n,
            validators=self.validators,
        )


ProposerSchedule = ProposerSelector
