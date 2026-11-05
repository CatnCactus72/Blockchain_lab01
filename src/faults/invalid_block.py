"""Cố ý đề xuất block sai; phải dùng hàm dựng block từ Người 2/3."""
from .base import Behavior, refresh_wire_message

class InvalidBlockBehavior(Behavior):
    def __init__(self,mode: str = 'bad_state_hash'):
        if mode not in {'bad_state_hash','oversized','replayed_tx'}:
            raise ValueError('Mode invalid_block không hỗ trợ')
        self.mode = mode

    def on_make_proposal(self,node,proposal):
        callback = getattr(node,'make_invalid_proposal',None)
        if callback is None:
            raise NotImplementedError('Cần node.make_invalid_proposal(proposal,mode) từ Người 2/3')
        invalid = callback(proposal,self.mode)
        return [(list(node.env.peers),refresh_wire_message(node,proposal,invalid))]
