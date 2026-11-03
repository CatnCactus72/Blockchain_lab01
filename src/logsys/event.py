"""Danh mục sự kiện, lý do từ chối, thứ tự trường và chuẩn hóa một dòng log."""
from urllib.parse import quote

EVENTS = frozenset({
    'SEND', 'RECV', 'DROP', 'DELAY', 'DUP', 'BLOCK', 'UNBLOCK',
    'PROPOSE', 'PREVOTE', 'PRECOMMIT', 'LOCK', 'TIMEOUT', 'NEW_ROUND', 'FINALIZE',
    'REJECT', 'TX_APPLIED', 'TX_SKIPPED', 'SIM_START', 'SIM_END'
})
REASONS = frozenset({
    'BAD_SIGNATURE', 'WRONG_DOMAIN', 'WRONG_CHAIN', 'UNKNOWN_ACCOUNT',
    'NOT_OWNER', 'BAD_KEY', 'TX_TOO_LONG', 'BAD_NONCE', 'REPLAYED_TX',
    'BAD_PARENT', 'BAD_TX_ROOT', 'BAD_STATE_HASH', 'BAD_TIMESTAMP',
    'BLOCK_TOO_LARGE', 'NOT_PROPOSER', 'DUPLICATE_MSG', 'DUPLICATE_VOTE',
    'CONFLICTING_VOTE', 'FUTURE_HEIGHT', 'PEER_BLOCKED', 'RATE_LIMIT'
})
FIELDS = ('r', 'msg', 'kind', 'origin', 'via', 'first', 'reason', 'details', 'hash', 'state')

def format_time(ms: int) -> str:
    minutes, remainder = divmod(ms, 60_000)
    seconds, milli = divmod(remainder, 1_000)
    return f'{minutes:02d}:{seconds:02d}:{milli:03d}'

def _scalar(value) -> str:
    if isinstance(value, bool):
        value = 'true' if value else 'false'
    if value is None:
        value = '-'
    # Không cho khoảng trắng/xuống dòng phá cấu trúc key=value.
    return quote(str(value), safe='._-:/')

def format_event(ms: int, seq: int, node: str, ev: str, height: int = -1, **fields) -> str:
    if ev not in EVENTS:
        raise ValueError(f'Loại sự kiện không hợp lệ: {ev}')
    if fields.get('reason') is not None and fields['reason'] not in REASONS:
        raise ValueError(f'Mã lý do không có trong đặc tả: {fields["reason"]}')
    if any(key not in FIELDS for key in fields):
        raise ValueError('Log chứa trường ngoài danh sách đã thống nhất')
    height_text = '-' if height == -1 else str(height)
    pieces = [format_time(ms), f'seq={seq:05d}', f'node={_scalar(node)}', f'ev={ev}', f'h={height_text}']
    pieces.extend(f'{name}={_scalar(fields[name])}' for name in FIELDS if fields.get(name) is not None)
    return ' '.join(pieces)
