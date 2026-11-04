"""
Định nghĩa các loại gói tin mạng (wire message), lớp Message (bất biến, được băm tính msg_id)
và lớp Envelope (thay đổi theo từng hop truyền qua mạng, không nằm trong msg_id).

Phân nhóm các loại wire message (Mục 5.6 README):
- Quản lý peer: HELLO, PING, PONG
- Giao dịch: TX
- Block: BODY_REQUEST, BODY
- Đồng thuận: PROPOSAL, PREVOTE, PRECOMMIT
- Đồng bộ: STATUS, GET_BLOCKS, BLOCKS, GET_VOTES, VOTES

Quy tắc msg_id:
msg_id = SHA256("MSG" || kind || origin || enc(payload))
Peer chuyển tiếp (from_peer, to_peer trong Envelope) cố ý không nằm trong msg_id
để khử trùng chính xác khi cùng một tin đi qua nhiều đường khác nhau.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.core.block import Block
from src.core.proposal import Proposal
from src.core.transaction import Transaction
from src.core.vote import CommitCertificate, Vote
from src.crypto.encoding import (
    NIL_BYTES,
    dec_bytes,
    dec_list,
    dec_map,
    dec_str,
    dec_uint,
    enc_bytes,
    enc_list,
    enc_map,
    enc_str,
    enc_uint,
    enc_value,
)
from src.crypto.hashing import HashHex, msg_id as compute_msg_id

# ============================================================================
# Các loại gói tin mạng (Wire Message Kinds)
# ============================================================================
# Nhóm quản lý peer
HELLO: str = "HELLO"
PING: str = "PING"
PONG: str = "PONG"

# Nhóm giao dịch (tin nhắn chat)
TX: str = "TX"

# Nhóm tải phần thân khối (header đi trước qua PROPOSAL, body đi sau khi yêu cầu)
BODY_REQUEST: str = "BODY_REQUEST"
BODY: str = "BODY"

# Nhóm đồng thuận
PROPOSAL: str = "PROPOSAL"
PREVOTE: str = "PREVOTE"
PRECOMMIT: str = "PRECOMMIT"

# Nhóm đồng bộ bù mất mát
STATUS: str = "STATUS"
GET_BLOCKS: str = "GET_BLOCKS"
BLOCKS: str = "BLOCKS"
GET_VOTES: str = "GET_VOTES"
VOTES: str = "VOTES"

# Tập hợp phân loại phục vụ định tuyến Gossip và gửi trực tiếp (Mục 5.3 README)
ALL_KINDS: tuple[str, ...] = (
    HELLO,
    PING,
    PONG,
    TX,
    BODY_REQUEST,
    BODY,
    PROPOSAL,
    PREVOTE,
    PRECOMMIT,
    STATUS,
    GET_BLOCKS,
    BLOCKS,
    GET_VOTES,
    VOTES,
)

# Chỉ gossip 4 loại: TX, PROPOSAL, PREVOTE, PRECOMMIT
GOSSIP_KINDS: tuple[str, ...] = (TX, PROPOSAL, PREVOTE, PRECOMMIT)

# Các loại gửi trực tiếp 1-1 giữa hai peer
DIRECT_KINDS: tuple[str, ...] = (
    HELLO,
    PING,
    PONG,
    BODY_REQUEST,
    BODY,
    STATUS,
    GET_BLOCKS,
    BLOCKS,
    GET_VOTES,
    VOTES,
)


def is_gossip_kind(kind: str) -> bool:
    """Kiểm tra xem loại wire message này có được lan truyền qua cơ chế Gossip hay không."""
    return kind in GOSSIP_KINDS


def encode_payload(kind: str, payload: Any) -> bytes:
    """
    Mã hóa chuẩn payload cho từng loại wire message (kind) để tính msg_id xác định.
    Hỗ trợ linh hoạt cả đối tượng chuyên biệt (Transaction, Proposal, Vote, Block...)
    lẫn cấu trúc dict/list/primitive.
    """
    if payload is None:
        return NIL_BYTES

    if isinstance(payload, (bytes, bytearray, memoryview)):
        return enc_bytes(bytes(payload))

    # Nếu đối tượng có sẵn phương thức encode() chuẩn (Transaction, Proposal, Vote, Block, Header...)
    if hasattr(payload, "encode") and callable(payload.encode):
        encoded = payload.encode()
        if isinstance(encoded, bytes):
            return encoded

    # Mã hóa chi tiết cho các cấu trúc payload dạng dict/tuple của từng kind
    if kind == STATUS and isinstance(payload, Mapping):
        height = int(payload.get("height", 0))
        last_hash = str(payload.get("last_hash", payload.get("block_hash", "")))
        return enc_uint(height) + enc_str(last_hash)

    if kind == GET_BLOCKS and isinstance(payload, Mapping):
        from_h = int(payload.get("from_height", payload.get("from", 1)))
        to_h = int(payload.get("to_height", payload.get("to", from_h)))
        return enc_uint(from_h) + enc_uint(to_h)

    if kind == BODY_REQUEST and isinstance(payload, Mapping):
        height = int(payload.get("height", 0))
        block_hash = str(payload.get("block_hash", ""))
        return enc_uint(height) + enc_str(block_hash)

    if kind == BODY:
        if isinstance(payload, Mapping):
            height = int(payload.get("height", 0))
            block_hash = str(payload.get("block_hash", ""))
            txs = payload.get("transactions", payload.get("body", payload.get("txs", [])))
            enc_txs = enc_list([tx.encode() if hasattr(tx, "encode") else enc_value(tx) for tx in txs])
            return enc_uint(height) + enc_str(block_hash) + enc_txs
        if isinstance(payload, Sequence):
            return enc_list([tx.encode() if hasattr(tx, "encode") else enc_value(tx) for tx in payload])

    if kind == BLOCKS:
        if isinstance(payload, Mapping):
            if "entries" in payload:
                return _encode_blocks_sequence(payload["entries"])
            blocks_list = payload.get("blocks", [])
            certs = payload.get("certificates", [])
            if certs and len(certs) == len(blocks_list):
                return _encode_blocks_sequence(list(zip(blocks_list, certs)))
            return _encode_blocks_sequence(blocks_list)
        if isinstance(payload, Sequence):
            return _encode_blocks_sequence(payload)

    if kind == GET_VOTES and isinstance(payload, Mapping):
        height = int(payload.get("height", 0))
        round_num = int(payload.get("round", 0))
        return enc_uint(height) + enc_uint(round_num)

    if kind == VOTES:
        if isinstance(payload, Mapping):
            height = int(payload.get("height", 0))
            round_num = int(payload.get("round", 0))
            votes = payload.get("votes", [])
            enc_votes = enc_list([v.encode() if hasattr(v, "encode") else enc_value(v) for v in votes])
            return enc_uint(height) + enc_uint(round_num) + enc_votes
        if isinstance(payload, Sequence):
            return enc_list([v.encode() if hasattr(v, "encode") else enc_value(v) for v in payload])

    return enc_value(payload)


def _encode_blocks_sequence(items: Sequence[Any]) -> bytes:
    """Mã hóa danh sách các mục (block, certificate) trong gói BLOCKS."""
    encoded_list: list[bytes] = []
    for item in items:
        if isinstance(item, tuple) and len(item) == 2:
            blk, cert = item
            b_bytes = blk.encode() if hasattr(blk, "encode") else enc_value(blk)
            c_bytes = (
                NIL_BYTES
                if cert is None
                else (cert.encode() if hasattr(cert, "encode") else enc_value(cert))
            )
            encoded_list.append(b_bytes + c_bytes)
        elif hasattr(item, "block") and hasattr(item, "certificate"):
            b_bytes = item.block.encode()
            c_bytes = item.certificate.encode() if item.certificate is not None else NIL_BYTES
            encoded_list.append(b_bytes + c_bytes)
        elif isinstance(item, Mapping) and "block" in item:
            blk = item["block"]
            cert = item.get("certificate")
            b_bytes = blk.encode() if hasattr(blk, "encode") else enc_value(blk)
            c_bytes = (
                NIL_BYTES
                if cert is None
                else (cert.encode() if hasattr(cert, "encode") else enc_value(cert))
            )
            encoded_list.append(b_bytes + c_bytes)
        elif hasattr(item, "encode") and callable(item.encode):
            encoded_list.append(item.encode())
        else:
            encoded_list.append(enc_value(item))
    return enc_list(encoded_list)


def decode_payload(kind: str, data: bytes, offset: int = 0) -> tuple[Any, int]:
    """Giải mã payload từ mảng byte theo đúng loại wire message (kind)."""
    if kind == TX:
        return Transaction.decode(data, offset)
    if kind == PROPOSAL:
        return Proposal.decode(data, offset)
    if kind in (PREVOTE, PRECOMMIT):
        return Vote.decode(data, offset)
    if kind == STATUS:
        height, cur = dec_uint(data, offset)
        last_hash, cur = dec_str(data, cur)
        return {"height": height, "last_hash": last_hash}, cur
    if kind == GET_BLOCKS:
        from_h, cur = dec_uint(data, offset)
        to_h, cur = dec_uint(data, cur)
        return {"from_height": from_h, "to_height": to_h, "from": from_h, "to": to_h}, cur
    if kind == BODY_REQUEST:
        height, cur = dec_uint(data, offset)
        block_hash, cur = dec_str(data, cur)
        return {"height": height, "block_hash": block_hash}, cur
    if kind == BODY:
        height, cur = dec_uint(data, offset)
        block_hash, cur = dec_str(data, cur)
        txs, cur = dec_list(data, Transaction.decode, cur)
        return {"height": height, "block_hash": block_hash, "transactions": txs}, cur
    if kind == GET_VOTES:
        height, cur = dec_uint(data, offset)
        round_num, cur = dec_uint(data, cur)
        return {"height": height, "round": round_num}, cur
    if kind == VOTES:
        height, cur = dec_uint(data, offset)
        round_num, cur = dec_uint(data, cur)
        votes, cur = dec_list(data, Vote.decode, cur)
        return {"height": height, "round": round_num, "votes": votes}, cur
    if kind == BLOCKS:
        def _dec_block_cert(buf: bytes, pos: int) -> tuple[dict[str, Any], int]:
            blk, p = Block.decode(buf, pos)
            if p + 32 <= len(buf) and buf[p : p + 32] == NIL_BYTES:
                cert = None
                p += 32
            else:
                cert, p = CommitCertificate.decode(buf, p)
            return {"block": blk, "certificate": cert}, p

        entries, cur = dec_list(data, _dec_block_cert, offset)
        return {
            "entries": entries,
            "blocks": [e["block"] for e in entries],
            "certificates": [e["certificate"] for e in entries],
        }, cur

    # Trường hợp payload rỗng / None (32 byte 0)
    if offset + 32 == len(data) and data[offset : offset + 32] == NIL_BYTES:
        return None, offset + 32

    # Thử giải mã như bytes nếu tiền tố độ dài u32 khớp đúng phần còn lại của buffer
    if offset + 4 <= len(data):
        declared_len = int.from_bytes(data[offset : offset + 4], byteorder="big", signed=False)
        if offset + 4 + declared_len == len(data):
            return dec_bytes(data, offset)

    # Thử giải mã như map (dict) cho các gói quản lý peer như HELLO/PING/PONG
    try:
        mapping_val, cur = dec_map(data, offset)
        if cur == len(data):
            return mapping_val, cur
    except (ValueError, UnicodeDecodeError):
        pass

    raw, cur = dec_bytes(data, offset)
    return raw, cur


@dataclass
class Message:
    """
    Lớp biểu diễn nội dung bất biến của một gói tin mạng (Wire Message):
    - kind: loại gói tin (TX, PROPOSAL, PREVOTE, PRECOMMIT, BODY_REQUEST, BODY, STATUS, ...)
    - origin: định danh node hoặc thực thể khởi tạo gói tin (ví dụ "N0".."N9")
    - payload: dữ liệu mang theo của gói tin
    - signature: chữ ký tùy chọn của gói tin nếu có
    """

    kind: str
    origin: str
    payload: Any = None
    signature: bytes = b""

    def __post_init__(self) -> None:
        """Chuẩn hóa chữ ký nếu được truyền dạng chuỗi hex."""
        if isinstance(self.signature, str):
            self.signature = bytes.fromhex(self.signature) if self.signature else b""
        elif isinstance(self.signature, (bytearray, memoryview)):
            self.signature = bytes(self.signature)

    def encode_payload(self) -> bytes:
        """Mã hóa chuẩn phần payload của gói tin theo kind."""
        return encode_payload(self.kind, self.payload)

    @property
    def msg_id(self) -> HashHex:
        """
        Tính định danh duy nhất của gói tin mạng:
        msg_id = SHA256("MSG" || kind || origin || enc(payload))
        Nhờ lớp HashHex hỗ trợ __call__(), người dùng có thể truy cập msg.msg_id
        như thuộc tính hoặc gọi msg.msg_id() như phương thức đều nhận được cùng chuỗi hex.
        """
        return compute_msg_id(self)

    @property
    def short_id(self) -> str:
        """Trả về 6 ký tự hex đầu của msg_id để ghi vào file log theo chuẩn Mục 5.6 & 9."""
        return str(self.msg_id)[:6]

    @property
    def height(self) -> int | None:
        """Trích xuất chiều cao (height) từ payload nếu có (phục vụ ghi log sự kiện)."""
        if hasattr(self.payload, "height"):
            return int(self.payload.height)
        if isinstance(self.payload, Mapping):
            if "height" in self.payload:
                return int(self.payload["height"])
            if "from_height" in self.payload:
                return int(self.payload["from_height"])
        return None

    @property
    def round(self) -> int | None:
        """Trích xuất số vòng (round) từ payload nếu có (phục vụ ghi log sự kiện)."""
        if hasattr(self.payload, "round"):
            return int(self.payload.round)
        if isinstance(self.payload, Mapping) and "round" in self.payload:
            return int(self.payload["round"])
        return None

    def encode(self) -> bytes:
        """Mã hóa chuẩn toàn bộ Message thành mảng byte."""
        return (
            enc_str(self.kind)
            + enc_str(self.origin)
            + enc_bytes(self.encode_payload())
            + enc_bytes(self.signature)
        )

    to_bytes = encode

    @classmethod
    def decode(cls, data: bytes, offset: int = 0) -> tuple[Message, int]:
        """Giải mã đối tượng Message từ mảng byte tại vị trí offset."""
        kind, cur = dec_str(data, offset)
        origin, cur = dec_str(data, cur)
        payload_bytes, cur = dec_bytes(data, cur)
        signature, cur = dec_bytes(data, cur)
        payload, _ = decode_payload(kind, payload_bytes, 0)
        return cls(
            kind=kind,
            origin=origin,
            payload=payload,
            signature=signature,
        ), cur


@dataclass
class Envelope:
    """
    Lớp bao gói theo từng bước nhảy (hop) trên mạng:
    - message: đối tượng Message bất biến bên trong
    - from_peer: node gửi ở hop hiện tại (via)
    - to_peer: node nhận ở hop hiện tại
    - sent_at_ms: thời điểm ảo (ms) gửi gói tin trên liên kết này
    Thông tin của Envelope thay đổi ở mỗi hop và tuyệt đối không tham gia vào msg_id.
    """

    message: Message
    from_peer: str
    to_peer: str
    sent_at_ms: int = 0

    @property
    def msg(self) -> Message:
        """Bí danh ngắn cho thuộc tính message."""
        return self.message

    @property
    def msg_id(self) -> HashHex:
        """Truy cập nhanh msg_id của gói tin bên trong."""
        return self.message.msg_id

    @property
    def short_id(self) -> str:
        """Truy cập nhanh 6 ký tự đầu của msg_id."""
        return self.message.short_id

    @property
    def kind(self) -> str:
        """Loại gói tin bên trong."""
        return self.message.kind

    @property
    def origin(self) -> str:
        """Node khởi tạo ban đầu của gói tin."""
        return self.message.origin

    @property
    def payload(self) -> Any:
        """Payload của gói tin bên trong."""
        return self.message.payload

    def forward(self, new_from_peer: str, new_to_peer: str, sent_at_ms: int = 0) -> Envelope:
        """Tạo một Envelope mới cho hop chuyển tiếp kế tiếp nhưng giữ nguyên Message gốc."""
        return Envelope(
            message=self.message,
            from_peer=new_from_peer,
            to_peer=new_to_peer,
            sent_at_ms=sent_at_ms,
        )


# ============================================================================
# Các hàm tiện ích khởi tạo nhanh từng loại Wire Message
# ============================================================================
def make_tx_message(origin: str, tx: Transaction) -> Message:
    """Tạo gói tin mạng loại TX chứa một giao dịch chat."""
    return Message(kind=TX, origin=origin, payload=tx)


def make_proposal_message(origin: str, proposal: Proposal) -> Message:
    """Tạo gói tin mạng loại PROPOSAL chứa đề xuất khối."""
    return Message(kind=PROPOSAL, origin=origin, payload=proposal)


def make_vote_message(origin: str, vote: Vote) -> Message:
    """Tạo gói tin mạng loại PREVOTE hoặc PRECOMMIT từ đối tượng Vote."""
    return Message(kind=vote.phase, origin=origin, payload=vote)


def make_body_request_message(origin: str, height: int, block_hash: str) -> Message:
    """Tạo gói tin BODY_REQUEST yêu cầu peer gửi phần thân của khối."""
    return Message(
        kind=BODY_REQUEST,
        origin=origin,
        payload={"height": int(height), "block_hash": str(block_hash)},
    )


def make_body_message(
    origin: str,
    height: int,
    block_hash: str,
    transactions: Sequence[Transaction],
) -> Message:
    """Tạo gói tin BODY phản hồi danh sách giao dịch của khối."""
    return Message(
        kind=BODY,
        origin=origin,
        payload={
            "height": int(height),
            "block_hash": str(block_hash),
            "transactions": list(transactions),
        },
    )


def make_status_message(origin: str, height: int, last_hash: str) -> Message:
    """Tạo gói tin STATUS thông báo chiều cao và mã băm khối finalize cuối cùng."""
    return Message(
        kind=STATUS,
        origin=origin,
        payload={"height": int(height), "last_hash": str(last_hash)},
    )


def make_get_blocks_message(origin: str, from_height: int, to_height: int) -> Message:
    """Tạo gói tin GET_BLOCKS yêu cầu đồng bộ các khối đã finalize trong đoạn [from_height, to_height]."""
    return Message(
        kind=GET_BLOCKS,
        origin=origin,
        payload={
            "from_height": int(from_height),
            "to_height": int(to_height),
            "from": int(from_height),
            "to": int(to_height),
        },
    )


def make_blocks_message(
    origin: str,
    entries: Sequence[tuple[Block, CommitCertificate] | dict[str, Any]],
) -> Message:
    """Tạo gói tin BLOCKS gửi các khối đã finalize kèm chứng nhận CommitCertificate."""
    normalized_entries: list[dict[str, Any]] = []
    blocks: list[Block] = []
    certs: list[CommitCertificate] = []

    for item in entries:
        if isinstance(item, tuple) and len(item) == 2:
            blk, cert = item
        elif hasattr(item, "block") and hasattr(item, "certificate"):
            blk, cert = item.block, item.certificate
        elif isinstance(item, Mapping):
            blk, cert = item["block"], item["certificate"]
        else:
            raise TypeError("Phần tử trong make_blocks_message phải gồm (Block, CommitCertificate)")
        normalized_entries.append({"block": blk, "certificate": cert})
        blocks.append(blk)
        certs.append(cert)

    return Message(
        kind=BLOCKS,
        origin=origin,
        payload={
            "entries": normalized_entries,
            "blocks": blocks,
            "certificates": certs,
        },
    )


def make_get_votes_message(origin: str, height: int, round_num: int) -> Message:
    """Tạo gói tin GET_VOTES yêu cầu các phiếu bầu của một (height, round) khi node bị kẹt."""
    return Message(
        kind=GET_VOTES,
        origin=origin,
        payload={"height": int(height), "round": int(round_num)},
    )


def make_votes_message(origin: str, height: int, round_num: int, votes: Sequence[Vote]) -> Message:
    """Tạo gói tin VOTES phản hồi danh sách phiếu bầu của (height, round)."""
    return Message(
        kind=VOTES,
        origin=origin,
        payload={"height": int(height), "round": int(round_num), "votes": list(votes)},
    )
