"""Hợp đồng Node/Env độc lập tầng mô phỏng để Người 3 ghép consensus."""
from dataclasses import dataclass
from random import Random
from typing import Protocol, runtime_checkable

from src.core.wire import Message
from src.logsys.event import REASONS


@dataclass(frozen=True)
class Verdict:
    """Kết quả validation; chỉ ACCEPT mới được mạng chuyển tiếp gossip."""
    status: str
    reason: str | None = None

    def __post_init__(self):
        if self.status not in {'ACCEPT', 'REJECT', 'IGNORE'}:
            raise ValueError('Verdict không hợp lệ')
        if self.status == 'REJECT' and self.reason not in REASONS:
            raise ValueError('REJECT phải có reason thuộc đặc tả')
        if self.status != 'REJECT' and self.reason is not None:
            raise ValueError('Chỉ REJECT được mang reason')

    @classmethod
    def accept(cls):
        return cls('ACCEPT')

    @classmethod
    def reject(cls, reason):
        return cls('REJECT', reason)

    @classmethod
    def ignore(cls):
        return cls('IGNORE')


@runtime_checkable
class NodeEnv(Protocol):
    """Node chỉ dùng giao diện này, không import sim hoặc net."""
    node_id: str

    def now(self) -> int: ...
    @property
    def peers(self) -> list[str]: ...
    def rng(self, *labels) -> Random: ...
    def send(self, peer: str, message: Message, h: int = -1, r: int | None = None) -> None: ...
    def gossip(self, message: Message, h: int = -1, r: int | None = None) -> None: ...
    def log(self, ev: str, h: int = -1, **fields) -> str: ...
    def set_timer(self, name: str, delay_ms: int) -> int: ...
    def cancel_timer(self, token: int) -> None: ...


@runtime_checkable
class NodeCallbacks(Protocol):
    """Factory build_node trả về đối tượng tuân thủ các callback này."""
    def on_start(self) -> None: ...
    def on_message(self, from_peer: str, message: Message) -> Verdict | str: ...
    def on_timer(self, name: str) -> None: ...
    def finalized_chain(self) -> list: ...
    def final_state_hash(self) -> str: ...
