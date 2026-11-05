"""Hạn mức gửi và cơ chế tạm chặn peer gửi quá dày."""
from collections import defaultdict, deque

class OutboundRateLimiter:
    def __init__(self, max_per_second: int):
        if max_per_second <= 0:
            raise ValueError('max_per_second phải dương')
        self.limit = max_per_second
        self._reserved = defaultdict(int)

    def reserve(self, now_ms: int) -> int:
        """Đặt trước ô gửi đầu tiên còn chỗ, không làm mất gói."""
        window = now_ms // 1000
        while self._reserved[window] >= self.limit:
            window += 1
        self._reserved[window] += 1
        return max(now_ms, window * 1000)

class InboundRateLimiter:
    def __init__(self, window_ms: int, max_count: int, block_ms: int):
        if min(window_ms, max_count, block_ms) <= 0:
            raise ValueError('Giá trị hạn mức phải dương')
        self.window_ms, self.max_count, self.block_ms = window_ms, max_count, block_ms
        self._recent = defaultdict(deque)
        self._blocked_until: dict[tuple[str,str],int] = {}

    def receive(self, receiver: str, sender: str, now_ms: int) -> tuple[str,int | None]:
        key = (receiver, sender)
        if now_ms < self._blocked_until.get(key, -1):
            return 'PEER_BLOCKED', self._blocked_until[key]
        recent = self._recent[key]
        while recent and recent[0] <= now_ms - self.window_ms:
            recent.popleft()
        if len(recent) >= self.max_count:
            until = now_ms + self.block_ms
            self._blocked_until[key] = until
            return 'BLOCK', until
        recent.append(now_ms)
        return 'ALLOW', None

    def clear_block(self, receiver: str, sender: str, until_ms: int, now_ms: int) -> bool:
        """Chỉ mở đúng lệnh block hiện tại (tránh timer cũ mở nhầm)."""
        key = (receiver, sender)
        if self._blocked_until.get(key) == until_ms and now_ms >= until_ms:
            del self._blocked_until[key]
            return True
        return False
