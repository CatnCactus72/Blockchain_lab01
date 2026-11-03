"""Tiêm lỗi chữ ký. Mode cần ký lại được giao cho API node thuộc Người 2/3."""
from copy import copy
from dataclasses import is_dataclass, replace
from .base import Behavior, refresh_wire_message


def _replace_signature(message):
    """Đổi một byte chữ ký; không sửa message gốc. Hỗ trợ cả payload có signature."""
    sig = message.get('signature') if isinstance(message,dict) else getattr(message,'signature',None)
    if sig is None:
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
        return replace(message,signature=bad_sig)
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
        modified = refresh_wire_message(node,msg,modified)
        self._outbound_messages[identifier] = modified
        self._emitted_ids.add(message_id(modified))
        return [(to,modified)]
