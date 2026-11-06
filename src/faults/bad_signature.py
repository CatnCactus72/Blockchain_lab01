"""Tiêm lỗi chữ ký. Mode cần ký lại được giao cho API node thuộc Người 2/3."""
from copy import copy
from dataclasses import fields, is_dataclass, replace
from .base import Behavior, refresh_wire_message


def _own_signed(node, message):
    """Message này có được ký bằng danh tính của chính node lỗi không.

    Ký lại bằng khóa riêng chỉ hợp lệ cho vote/proposal DO node lỗi tạo ra:
    node Byzantine không thể giả danh danh tính validator khác (README mục 8).

    Trả None khi payload không phải Vote/Proposal (không kiểm tra được danh tính;
    giữ nguyên hợp đồng cũ: bơm qua node.resign_wrong_domain của Người 2/3).
    """
    from ..core.proposal import Proposal
    from ..core.vote import Vote
    from ..core.wire import Message

    payload = message.payload if isinstance(message, Message) else message
    if isinstance(payload, Vote):
        return payload.validator_id == node.node_id and message.origin == node.node_id
    if isinstance(payload, Proposal):
        return payload.header is not None and payload.header.proposer_id == node.node_id \
            and message.origin == node.node_id
    return None


def _replace_signature(message):
    """Đổi một byte chữ ký; không sửa message gốc. Hỗ trợ cả payload có signature."""
    sig = message.get('signature') if isinstance(message,dict) else getattr(message,'signature',None)
    if not sig:
        payload = message.get('payload') if isinstance(message,dict) else getattr(message,'payload',None)
        if payload is None:
            raise ValueError('Wire message không có payload hoặc signature')
        nested = _replace_signature(payload)
        if isinstance(message,dict):
            return {**message,'payload':nested}
        if is_dataclass(message):
            return replace(message,payload=nested)
        new = copy(message)
        setattr(new,'payload',nested)
        return new
    if isinstance(sig,bytes) and sig:
        bad_sig = bytes([sig[0]^1])+sig[1:]
    elif isinstance(sig,str) and sig:
        bad_sig = ('0' if sig[0] != '0' else '1') + sig[1:]
    else:
        raise ValueError('Đối tượng cần thuộc tính signature trước khi tiêm BAD_SIGNATURE')
    if isinstance(message,dict):
        return {**message,'signature':bad_sig}
    if is_dataclass(message):
        # Proposal dùng property signature nhưng trường dataclass là proposal_sig.
        name = 'signature' if 'signature' in {field.name for field in fields(message)} else 'proposal_sig'
        return replace(message,**{name:bad_sig})
    new = copy(message)
    setattr(new,'signature',bad_sig)
    return new

class BadSignatureBehavior(Behavior):
    def __init__(self, mode: str = 'bad_key'):
        if mode not in {'bad_key', 'wrong_domain', 'tamper', 'cycle'}:
            raise ValueError('Mode bad_signature không hỗ trợ')
        self.mode = mode
        self._counter = 0
        self._outbound_messages = {}
        self._emitted_ids = set()

    def _corrupt(self,node,message):
        # T3: lần lượt giả khóa sai, ký sai domain, sửa dữ liệu sau khi ký.
        mode = self.mode
        if mode == 'cycle':
            mode = ('bad_key','wrong_domain','tamper')[self._counter % 3]
            self._counter += 1
        if mode == 'bad_key':
            # Làm hỏng chữ ký; thư viện kiểm tra sẽ trả BAD_SIGNATURE.
            return _replace_signature(message)
        if mode == 'wrong_domain':
            # Node + crypto của Người 2 phải ký hợp lệ cho domain SAI.
            owned = _own_signed(node, message)
            if owned is False:
                # Không thể ký lại giúp message của người khác: chuyển tiếp nguyên dạng.
                return message
            if owned is None:
                from ..core.transaction import Transaction
                from ..core.wire import Message
                payload = message.payload if isinstance(message, Message) else message
                if isinstance(payload, Transaction):
                    # TX được ký bằng khóa user mà node không giữ: không thể ký lại domain sai.
                    # Hành vi Byzantine thay thế: sửa nội dung sau khi ký → quả quyết BAD_SIGNATURE.
                    tamper = getattr(node, 'tamper_signed_message', None)
                    if callable(tamper):
                        return tamper(message)
            callback = getattr(node,'resign_wrong_domain',None)
            if callback is None:
                raise NotImplementedError('Cần node.resign_wrong_domain(message) từ Người 2/3')
            return callback(message)
        if mode == 'tamper':
            callback = getattr(node,'tamper_signed_message',None)
            if callback is None:
                raise NotImplementedError('Cần node.tamper_signed_message(message) từ Người 2/3')
            return callback(message)
        raise ValueError(f'Mode bad_signature không hỗ trợ: {self.mode}')

    def on_send(self,node,to,msg):
        # Không cố phá chữ ký những gói trực tiếp không có chữ ký riêng như STATUS.
        from ..net.gossip import message_kind, message_id
        if message_kind(msg) not in {'TX','PROPOSAL','PREVOTE','PRECOMMIT'}:
            return [(to,msg)]
        identifier = message_id(msg)
        if identifier in self._emitted_ids:
            return [(to,msg)]
        if identifier in self._outbound_messages:
            return [(to,self._outbound_messages[identifier])]
        # Chỉ sửa tại outbound để hai hook liên tiếp không đảo byte chữ ký hai lần.
        modified = self._corrupt(node,msg)
        if modified is msg:
            return [(to,msg)]
        modified = refresh_wire_message(node,msg,modified)
        self._outbound_messages[identifier] = modified
        self._emitted_ids.add(message_id(modified))
        return [(to,modified)]
