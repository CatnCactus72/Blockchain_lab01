"""Hook hành vi node lỗi. Consensus/Node gọi hook; mô phỏng không biết luật bỏ phiếu."""


def refresh_wire_message(node, original, modified):
    """Yêu cầu Core dựng lại ID chuẩn khi hook sửa một wire message có ID lưu sẵn."""
    from ..net.gossip import message_id
    has_id = 'msg_id' in original if isinstance(original, dict) else hasattr(original, 'msg_id')
    if not has_id:
        return modified
    if message_id(original) != message_id(modified):
        return modified
    callback = getattr(node, 'rebuild_wire_message', None)
    if not callable(callback):
        raise NotImplementedError('Cần node.rebuild_wire_message(message) tính lại msg_id qua Core/Wire')
    rebuilt = callback(modified)
    if message_id(original) == message_id(rebuilt):
        raise ValueError('Fault thay đổi thông điệp nhưng msg_id chưa được cập nhật')
    return rebuilt

class Behavior:
    """Đầu ra của on_make_vote/proposal: danh sách (danh_sách_peer, message)."""
    def on_receive(self, node, from_peer, msg):
        return msg

    def on_send(self, node, to, msg):
        return [(to, msg)]

    def on_make_proposal(self, node, proposal):
        return [(list(node.env.peers), proposal)]

    def on_make_vote(self, node, vote):
        return [(list(node.env.peers), vote)]

    def on_timer(self, node, name):
        return []

class Honest(Behavior):
    """Node trung thực giữ nguyên mọi thông điệp."""
    pass

def make_behavior(config: dict) -> Behavior:
    """Khởi tạo hành vi từ cấu hình kịch bản, import lười để tránh vòng phụ thuộc."""
    kind = config.get('type','honest').lower()
    if kind == 'honest':
        return Honest()
    if kind == 'silent':
        from .silent import SilentBehavior
        return SilentBehavior(config.get('from_ms',0))
    if kind == 'bad_signature':
        from .bad_signature import BadSignatureBehavior
        return BadSignatureBehavior(config.get('mode','bad_key'))
    if kind == 'replay':
        from .replay import ReplayBehavior
        return ReplayBehavior(int(config.get('copies',3)),int(config.get('delay_ms',1000)))
    if kind == 'equivocate':
        from .equivocate import EquivocateBehavior
        return EquivocateBehavior(config.get('target','both'))
    if kind == 'invalid_block':
        from .invalid_block import InvalidBlockBehavior
        return InvalidBlockBehavior(config.get('mode','bad_state_hash'))
    raise ValueError(f'Hành vi node lỗi không hỗ trợ: {kind}')
