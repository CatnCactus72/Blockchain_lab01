"""Đồng hồ thời gian ảo, không phụ thuộc thời gian thực của máy."""

class VirtualClock:
    def __init__(self, start_ms: int = 0):
        if not isinstance(start_ms, int) or start_ms < 0:
            raise ValueError("start_ms phải là số nguyên không âm")
        self._now_ms = start_ms

    def now(self) -> int:
        """Lấy thời gian hiện tại, tính bằng mili-giây."""
        return self._now_ms

    def advance_to(self, target_ms: int) -> None:
        """Chỉ cho phép đồng hồ tiến lên, tuyệt đối không quay ngược."""
        if not isinstance(target_ms, int) or target_ms < self._now_ms:
            raise ValueError("Không được đưa đồng hồ ảo quay ngược")
        self._now_ms = target_ms
