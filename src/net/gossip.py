"""Khử trùng message theo id bất biến và chỉ forward khi node chấp nhận."""

GOSSIP_KINDS = frozenset({'TX', 'PROPOSAL', 'PREVOTE', 'PRECOMMIT'})

def message_kind(message) -> str:
    return message['kind'] if isinstance(message, dict) else str(message.kind)

def message_origin(message) -> str:
    return message['origin'] if isinstance(message, dict) else str(message.origin)

def message_id(message) -> str:
    """Gói tin sản xuất bởi Người 2 PHẢI có msg_id xác định; không hash JSON."""
    result = message.get('msg_id') if isinstance(message, dict) else getattr(message, 'msg_id', None)
    if callable(result):
        result = result()
    if isinstance(result, bytes):
        result = result.hex()
    if not isinstance(result, str) or not result:
        raise ValueError('Wire message phải mang msg_id hoặc hàm msg_id()')
    return result

class GossipTracker:
    def __init__(self):
        self._seen: dict[str,set[str]] = {}

    def mark_seen(self, node_id: str, message) -> bool:
        identifiers = self._seen.setdefault(node_id,set())
        msgid = message_id(message)
        if msgid in identifiers:
            return False
        identifiers.add(msgid)
        return True

def normalize_verdict(verdict) -> str:
    """Đọc ACCEPT / REJECT / IGNORE, kể cả enum hoặc Verdict object."""
    if isinstance(verdict, str):
        result = verdict
    else:
        result = getattr(verdict, 'status', getattr(verdict, 'kind', verdict))
        result = getattr(result, 'name', getattr(result, 'value', result))
    result = str(result).upper()
    if result not in {'ACCEPT','REJECT','IGNORE'}:
        raise ValueError('Node.on_message phải trả ACCEPT, REJECT hoặc IGNORE')
    return result
