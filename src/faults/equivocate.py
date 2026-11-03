"""Hai phiếu/đề xuất MÂU THUẪN nhưng đều được ký hợp lệ bằng khóa của node lỗi."""
from .base import Behavior, refresh_wire_message

class EquivocateBehavior(Behavior):
    def __init__(self,target: str = 'both'):
        if target not in {'vote','proposal','both'}:
            raise ValueError('target phải là vote, proposal hoặc both')
        self.target = target

    @staticmethod
    def _split(node,original,conflicting):
        peers = sorted(node.env.peers, key=lambda x:(0,int(x[1:])) if x.startswith('N') and x[1:].isdigit() else (1,x))
        mid = len(peers)//2
        return [(peers[:mid],original),(peers[mid:],conflicting)]

    def on_make_vote(self,node,vote):
        if self.target == 'proposal':
            return super().on_make_vote(node,vote)
        callback = getattr(node,'make_conflicting_vote',None)
        if callback is None:
            raise NotImplementedError('Cần node.make_conflicting_vote(vote) tạo phiếu khác có chữ ký HỢP LỆ')
        conflicting = callback(vote)
        if conflicting == vote:
            raise ValueError('Callback equivocation phải tạo thông điệp mâu thuẫn')
        return self._split(node,vote,refresh_wire_message(node,vote,conflicting))

    def on_make_proposal(self,node,proposal):
        if self.target == 'vote':
            return super().on_make_proposal(node,proposal)
        callback = getattr(node,'make_conflicting_proposal',None)
        if callback is None:
            raise NotImplementedError('Cần node.make_conflicting_proposal(proposal) trả proposal khác có chữ ký hợp lệ')
        conflicting = callback(proposal)
        if conflicting == proposal:
            raise ValueError('Callback equivocation phải tạo thông điệp mâu thuẫn')
        return self._split(node,proposal,refresh_wire_message(node,proposal,conflicting))
