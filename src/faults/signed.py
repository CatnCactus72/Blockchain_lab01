"""Adapter lỗi dùng cấu trúc và chữ ký thật; chỉ giữ khóa riêng của validator lỗi."""
from copy import deepcopy

from src.core.proposal import Proposal
from src.core.vote import Vote
from src.core.wire import Message
from src.crypto.signing import sign


class SignedFaultAdapter:
    """Người 3 gắn các method này thành callback của node Byzantine khi cần."""
    def __init__(self, node_id: str, private_key, chain_id: str):
        self.node_id = node_id
        self.private_key = private_key
        self.chain_id = chain_id

    def _own(self, value):
        owner = value.validator_id if isinstance(value, Vote) else value.proposer_id
        if owner != self.node_id:
            raise ValueError('Chỉ được ký bằng danh tính của chính validator lỗi')

    def make_conflicting_vote(self, vote: Vote) -> Vote:
        self._own(vote)
        other = deepcopy(vote)
        other.block_hash = None if vote.block_hash is not None else '1' * 64
        other.sign(self.private_key, self.chain_id)
        return other

    def make_conflicting_proposal(self, proposal: Proposal) -> Proposal:
        self._own(proposal)
        if proposal.pol_round != -1 or proposal.header.proposer_id != self.node_id:
            raise NotImplementedError('Đề xuất lại block đã khóa cần callback từ Block Builder')
        other = deepcopy(proposal)
        other.header.timestamp += 1
        other.header.sign(self.private_key)
        other.block_hash = str(other.header.block_hash())
        other.sign(self.private_key, self.chain_id, self.node_id)
        return other

    def resign_wrong_domain(self, message):
        other = deepcopy(message)
        value = other.payload if isinstance(other, Message) else other
        if not isinstance(value, (Vote, Proposal)):
            raise NotImplementedError('Ký sai domain cho TX cần khóa user do workload sở hữu')
        self._own(value)
        wrong_domain = 'PROPOSAL' if isinstance(value, Vote) else 'VOTE'
        value.signature = sign(self.private_key, wrong_domain, self.chain_id, value.signing_fields())
        return other

    def tamper_signed_message(self, message):
        other = deepcopy(message)
        value = other.payload if isinstance(other, Message) else other
        if isinstance(value, (Vote, Proposal)):
            value.block_hash = None if isinstance(value, Vote) and value.block_hash else (
                '3' * 64 if value.block_hash == '2' * 64 else '2' * 64)
        elif hasattr(value, 'value'):
            value.value += '!'
        else:
            raise ValueError('Không có trường dữ liệu đã ký để sửa')
        return other
