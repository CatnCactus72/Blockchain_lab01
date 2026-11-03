"""Node im lặng: dừng nhận và/hoặc phát từ thời điểm cấu hình."""
from .base import Behavior

def _active(node, start_ms: int) -> bool:
    return node.env.now() >= start_ms

class SilentBehavior(Behavior):
    def __init__(self, from_ms: int = 0):
        self.from_ms = int(from_ms)

    def on_receive(self,node,from_peer,msg):
        return None if _active(node,self.from_ms) else msg

    def on_send(self,node,to,msg):
        return [] if _active(node,self.from_ms) else [(to,msg)]

    def on_make_proposal(self,node,proposal):
        return [] if _active(node,self.from_ms) else super().on_make_proposal(node,proposal)

    def on_make_vote(self,node,vote):
        return [] if _active(node,self.from_ms) else super().on_make_vote(node,vote)
