"""Nhân bản ngay và phát lại gói cũ khi timer nổ."""
from .base import Behavior

class ReplayBehavior(Behavior):
    def __init__(self,copies: int = 3,delay_ms: int = 1000):
        if copies <= 0 or delay_ms < 0:
            raise ValueError('copies > 0 và delay_ms >= 0')
        self.copies,self.delay_ms = copies,delay_ms
        self._pending = {}
        self._sequence = 0
        self._already_replayed = set()

    def on_send(self,node,to,msg):
        from ..net.gossip import message_id
        key = (to,message_id(msg))
        if key in self._already_replayed:
            # Phát lại một lần, KHÔNG tạo timer mới gây lặp vô hạn.
            return [(to,msg)]
        self._already_replayed.add(key)
        self._sequence += 1
        timer_name = f'fault:replay:{self._sequence}'
        self._pending[timer_name] = (to,msg)
        # Người 3 cần gọi behavior.on_timer khi nhận timer bắt đầu bằng fault:.
        node.env.set_timer(timer_name,self.delay_ms)
        return [(to,msg) for _ in range(self.copies)]

    def on_timer(self,node,name):
        item = self._pending.pop(name,None)
        return [item] if item is not None else []
