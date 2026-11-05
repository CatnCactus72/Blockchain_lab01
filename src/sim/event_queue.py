"""Hàng đợi sự kiện với thứ tự ổn định theo (thời gian, số thứ tự)."""
from dataclasses import dataclass, field
from heapq import heappop, heappush
from typing import Callable, Any

@dataclass(order=True)
class ScheduledEvent:
    at_ms: int
    seq: int
    name: str = field(compare=False)
    callback: Callable[..., Any] = field(compare=False)
    args: tuple = field(default_factory=tuple, compare=False)
    kwargs: dict = field(default_factory=dict, compare=False)

class EventQueue:
    def __init__(self):
        self._heap: list[ScheduledEvent] = []
        self._next_seq = 0

    def push(self, at_ms: int, name: str, callback: Callable, *args, **kwargs) -> ScheduledEvent:
        if not isinstance(at_ms, int) or at_ms < 0:
            raise ValueError("Thời điểm sự kiện phải là số nguyên không âm")
        if not callable(callback):
            raise TypeError("callback phải gọi được")
        # seq tăng đơn điệu; khi cùng thời điểm thì chạy theo thứ tự tạo sự kiện.
        event = ScheduledEvent(at_ms, self._next_seq, name, callback, args, kwargs)
        self._next_seq += 1
        heappush(self._heap, event)
        return event

    def pop(self) -> ScheduledEvent:
        return heappop(self._heap)

    def peek(self) -> ScheduledEvent | None:
        return self._heap[0] if self._heap else None

    def __len__(self) -> int:
        return len(self._heap)
