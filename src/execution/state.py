"""
Định nghĩa lớp State lưu trữ trạng thái key-value và bộ đếm nonce đã áp dụng
theo từng tài khoản trong Chat Chain.

Quy tắc State (Mục 3.2 README):
- State là map key-value (ban đầu rỗng). Mỗi tin nhắn đã áp dụng ghi thêm một mục:
  '<account>/chat/<nonce>' = '<nội dung tin nhắn>'.
- state_hash = SHA256("STATE" || enc_map(state)) là mã băm phẳng trên map đã sắp xếp
  theo thứ tự byte của key, hoàn toàn độc lập với thứ tự chèn.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from src.crypto.encoding import normalize_nfc
from src.crypto.hashing import HashHex, state_hash as compute_state_hash


class State(Mapping[str, str]):
    """
    Lớp biểu diễn trạng thái thực thi của chuỗi (key-value map + bộ đếm nonce theo tài khoản).
    Hỗ trợ nhân bản (clone/copy) nhanh để proposer và validator thực thi thử mà không làm hỏng
    trạng thái chính thức của node.
    """

    def __init__(
        self,
        data: Mapping[str, str] | None = None,
        nonces: Mapping[str, int] | None = None,
    ) -> None:
        self._data: dict[str, str] = {}
        self._nonces: dict[str, int] = {}

        if nonces is not None:
            for acc, n_val in nonces.items():
                self._nonces[str(acc)] = int(n_val)

        if data is not None:
            for k, v in data.items():
                self.set(str(k), str(v))

    @property
    def data(self) -> dict[str, str]:
        """Trả về từ điển key-value bên trong của State."""
        return self._data

    @property
    def nonces(self) -> dict[str, int]:
        """Trả về từ điển bộ đếm nonce đã áp dụng của từng tài khoản."""
        return self._nonces

    def get(self, key: str, default: Any = None) -> Any:
        """Đọc giá trị của một key trong State (tự động chuẩn hóa key về NFC)."""
        norm_key = normalize_nfc(str(key))
        return self._data.get(norm_key, default)

    def set(
        self,
        key: str,
        value: str,
        account: str | None = None,
        nonce: int | None = None,
    ) -> None:
        """
        Ghi cặp (key, value) vào State và cập nhật bộ đếm nonce đã áp dụng của tài khoản.
        Nếu không truyền trực tiếp (account, nonce), hàm tự động tách từ key dạng '<account>/chat/<nonce>'.
        """
        norm_key = normalize_nfc(str(key))
        norm_val = normalize_nfc(str(value))
        self._data[norm_key] = norm_val

        if account is not None and nonce is not None:
            norm_acc = normalize_nfc(str(account))
            prev = self._nonces.get(norm_acc, 0)
            if nonce > prev:
                self._nonces[norm_acc] = int(nonce)
        else:
            parsed = self._parse_chat_key(norm_key)
            if parsed is not None:
                acc, parsed_nonce = parsed
                prev = self._nonces.get(acc, 0)
                if parsed_nonce > prev:
                    self._nonces[acc] = parsed_nonce

    @staticmethod
    def _parse_chat_key(key: str) -> tuple[str, int] | None:
        """Tách (account, nonce) từ key dạng '<account>/chat/<nonce>' nếu khớp."""
        parts = key.split("/")
        if len(parts) == 3 and parts[0] and parts[1] == "chat":
            try:
                n_val = int(parts[2])
                if n_val >= 1 and str(n_val) == parts[2]:
                    return parts[0], n_val
            except ValueError:
                return None
        return None

    def get_nonce(self, account: str) -> int:
        """Lấy nonce đã áp dụng gần nhất của tài khoản (mặc định là 0 nếu chưa có tin nào)."""
        return self._nonces.get(normalize_nfc(str(account)), 0)

    # Bí danh cho get_nonce
    applied_nonce = get_nonce

    def next_nonce(self, account: str) -> int:
        """Lấy số nonce hợp lệ tiếp theo của tài khoản ( bằng nonce_đã_áp_dụng + 1 )."""
        return self.get_nonce(account) + 1

    def set_nonce(self, account: str, nonce: int) -> None:
        """Đặt trực tiếp giá trị nonce đã áp dụng cho một tài khoản."""
        self._nonces[normalize_nfc(str(account))] = int(nonce)

    def state_hash(self) -> HashHex:
        """
        Tính mã băm cam kết của State:
        state_hash = SHA256("STATE" || enc_map(state))
        Kết quả luôn xác định và không phụ thuộc vào thứ tự chèn các key.
        """
        return compute_state_hash(self._data)

    def clone(self) -> State:
        """Nhân bản độc lập đối tượng State hiện tại để phục vụ thực thi thử (dry-run)."""
        cloned = State()
        cloned._data = dict(self._data)
        cloned._nonces = dict(self._nonces)
        return cloned

    # Bí danh cho clone()
    copy = clone

    def __copy__(self) -> State:
        return self.clone()

    def __deepcopy__(self, memo: Any) -> State:
        return self.clone()

    def replace_from(self, other: State) -> None:
        """Cập nhật toàn bộ dữ liệu và bộ đếm nonce từ một đối tượng State khác."""
        self._data = dict(other._data)
        self._nonces = dict(other._nonces)

    def get_account_entries(self, account: str) -> dict[str, str]:
        """
        Lấy tất cả các mục key-value thuộc không gian tên của một tài khoản ('<account>/...'),
        sắp xếp theo thứ tự nonce tăng dần rồi theo key.
        """
        norm_acc = normalize_nfc(str(account))
        prefix = f"{norm_acc}/"
        matched: list[tuple[tuple[int, str], str, str]] = []
        for k, v in self._data.items():
            if k.startswith(prefix):
                parsed = self._parse_chat_key(k)
                sort_nonce = parsed[1] if parsed is not None else (1 << 60)
                matched.append(((sort_nonce, k), k, v))
        matched.sort(key=lambda item: item[0])
        return {k: v for _, k, v in matched}

    def to_dict(self) -> dict[str, str]:
        """Trả về bản sao từ điển key-value đã được sắp xếp theo thứ tự byte của key."""
        return dict(sorted(self._data.items(), key=lambda kv: kv[0].encode("utf-8")))

    def __getitem__(self, key: str) -> str:
        return self._data[normalize_nfc(str(key))]

    def __setitem__(self, key: str, value: str) -> None:
        self.set(key, value)

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        return normalize_nfc(key) in self._data

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __bool__(self) -> bool:
        """
        Đảm bảo đối tượng State luôn có giá trị logic True kể cả khi map đang rỗng ({}).
        Điều này giúp câu lệnh `if new_state:` khi kiểm tra kết quả của apply_block() luôn đúng.
        """
        return True

    def __eq__(self, other: object) -> bool:
        if isinstance(other, State):
            return self._data == other._data and self._nonces == other._nonces
        if isinstance(other, Mapping):
            return self._data == dict(other)
        return False

    def __repr__(self) -> str:
        return f"State(entries={len(self._data)}, hash={str(self.state_hash())[:8]}...)"
