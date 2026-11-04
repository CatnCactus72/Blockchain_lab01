"""
Các hàm băm mật mã SHA-256 và hàm tiện ích tính định danh cho Chat Chain:
- sha256(*parts): băm SHA-256 trả về 32 byte digest.
- sha256_hex(*parts): băm SHA-256 trả về chuỗi hex 64 ký tự (HashHex).
- tx_id: SHA256("TXID" || account || nonce || enc(key) || enc(value))
- state_hash: SHA256("STATE" || enc_map(state))
- tx_root: SHA256("TXROOT" || enc_list(tx_id...))
- block_hash: SHA256("BLOCK" || enc(header không gồm signature))
- genesis_hash: SHA256("GENESIS" || chain_id)
- msg_id: SHA256("MSG" || kind || origin || enc(payload))
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from src.crypto.domain import BLOCK, GENESIS, MSG, STATE, TXID, TXROOT
from src.crypto.encoding import NIL_BYTES, enc_bytes, enc_list, enc_map, enc_str, enc_uint, enc_value


class HashHex(str):
    """
    Lớp chuỗi hex 64 ký tự biểu diễn giá trị băm SHA-256.
    Kế thừa từ str nên hoạt động hoàn toàn như chuỗi thông thường (cắt [:6], so sánh ==, in log),
    đồng thời hỗ trợ:
    - .hex() trả về chính chuỗi hex (tương thích nếu nơi gọi coi hash như bytes).
    - .digest() và bytes(h) trả về 32 byte nhị phân gốc.
    - h() cho phép gọi như phương thức hoặc truy cập như thuộc tính.
    """

    def hex(self) -> str:
        """Trả về chuỗi hex 64 ký tự."""
        return str(self)

    def digest(self) -> bytes:
        """Trả về mảng 32 byte gốc của mã băm."""
        return bytes.fromhex(self)

    def to_bytes(self) -> bytes:
        """Trả về mảng 32 byte gốc của mã băm."""
        return bytes.fromhex(self)

    def __bytes__(self) -> bytes:
        """Hỗ trợ ép kiểu bytes(h)."""
        return bytes.fromhex(self)

    def __call__(self) -> HashHex:
        """Cho phép gọi đối tượng như hàm (ví dụ msg.msg_id() hoặc msg.msg_id đều hoạt động)."""
        return self


def to_canonical_hash_str(value: str | bytes | None) -> str:
    """
    Chuẩn hóa một giá trị hash (dạng chuỗi hex 64 ký tự hoặc 32 byte thô) về chuỗi hex chữ thường.
    Nếu là None hoặc 'NIL' hoặc 32 byte 0 thì trả về chuỗi rỗng đại diện NIL.
    """
    if value is None or value == "NIL" or value == "" or value == NIL_BYTES:
        return ""
    if isinstance(value, HashHex):
        return str(value).lower()
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        if raw == NIL_BYTES:
            return ""
        if len(raw) == 32:
            return raw.hex()
        # Trường hợp bytes chứa chuỗi ASCII hex 64 ký tự
        if len(raw) == 64:
            try:
                text = raw.decode("ascii").lower()
                bytes.fromhex(text)
                return text
            except ValueError:
                pass
        return raw.hex()
    if isinstance(value, str):
        return value.lower()
    raise TypeError(f"Không thể chuẩn hóa giá trị hash từ kiểu {type(value).__name__}")


def _part_to_bytes(part: Any) -> bytes:
    """Chuyển một thành phần đầu vào của hàm băm sang mảng byte chuẩn."""
    if isinstance(part, (bytes, bytearray, memoryview)):
        return bytes(part)
    if isinstance(part, str):
        return enc_str(part)
    if isinstance(part, int) and not isinstance(part, bool):
        return enc_uint(part)
    return enc_value(part)


def sha256(*parts: Any) -> bytes:
    """
    Tính hàm băm SHA-256 trên các phần dữ liệu đã mã hóa chuẩn.
    Trả về đối tượng bytes dài đúng 32 byte.
    """
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(_part_to_bytes(part))
    return hasher.digest()


def sha256_hex(*parts: Any) -> HashHex:
    """
    Tính hàm băm SHA-256 trên các phần dữ liệu và trả về chuỗi hex 64 ký tự (HashHex).
    """
    return HashHex(sha256(*parts).hex())


def tx_id(
    account_or_tx: Any,
    nonce: int | None = None,
    key: str | None = None,
    value: str | None = None,
) -> HashHex:
    """
    Tính định danh giao dịch (tin nhắn chat):
    tx_id = SHA256("TXID" || account || nonce || enc(key) || enc(value))

    Hỗ trợ 2 cách gọi:
    - tx_id(tx_obj): truyền đối tượng Transaction.
    - tx_id(account, nonce, key, value): truyền trực tiếp 4 trường.
    """
    if nonce is None and key is None and value is None and hasattr(account_or_tx, "account"):
        tx_obj = account_or_tx
        acc = tx_obj.account
        tx_nonce = tx_obj.nonce
        tx_key = tx_obj.key
        tx_val = tx_obj.value
    else:
        if nonce is None or key is None or value is None:
            raise ValueError("tx_id cần truyền đủ (account, nonce, key, value) hoặc một đối tượng Transaction")
        acc = str(account_or_tx)
        tx_nonce = int(nonce)
        tx_key = str(key)
        tx_val = str(value)

    return sha256_hex(
        enc_str(TXID),
        enc_str(acc),
        enc_uint(tx_nonce),
        enc_str(tx_key),
        enc_str(tx_val),
    )


def state_hash(state: Mapping[str, Any] | Any) -> HashHex:
    """
    Tính mã băm trạng thái phẳng trên map key-value đã sắp xếp theo byte của key:
    state_hash = SHA256("STATE" || enc_map(state))
    """
    if hasattr(state, "data") and isinstance(state.data, Mapping):
        mapping: Mapping[str, Any] = state.data
    elif hasattr(state, "to_dict") and callable(state.to_dict):
        mapping = state.to_dict()
    elif isinstance(state, Mapping):
        mapping = state
    else:
        raise TypeError(f"state_hash yêu cầu dict hoặc đối tượng State, nhận được {type(state).__name__}")

    return sha256_hex(enc_str(STATE), enc_map(mapping))


def tx_root(tx_items: Sequence[Any]) -> HashHex:
    """
    Tính mã băm gốc danh sách giao dịch trong block:
    tx_root = SHA256("TXROOT" || enc_list(tx_id...))

    Cho phép truyền danh sách các chuỗi tx_id hoặc danh sách các đối tượng Transaction.
    """
    normalized_ids: list[bytes] = []
    for item in tx_items:
        if hasattr(item, "tx_id"):
            tid = item.tx_id() if callable(item.tx_id) else item.tx_id
            normalized_ids.append(enc_str(to_canonical_hash_str(tid)))
        elif isinstance(item, str):
            normalized_ids.append(enc_str(to_canonical_hash_str(item)))
        elif isinstance(item, (bytes, bytearray, memoryview)):
            normalized_ids.append(enc_str(to_canonical_hash_str(bytes(item))))
        else:
            raise TypeError(f"Phần tử trong tx_root không hợp lệ: {type(item).__name__}")

    return sha256_hex(enc_str(TXROOT), enc_list(normalized_ids))


def genesis_hash(chain_id: str = "lab01-chain") -> HashHex:
    """
    Tính mã băm cho khối khởi nguyên (Genesis Block):
    block_hash = SHA256("GENESIS" || chain_id)
    """
    return sha256_hex(enc_str(GENESIS), enc_str(chain_id))


def block_hash(header_or_block: Any) -> HashHex:
    """
    Tính mã băm của một block từ Header (không bao gồm chữ ký):
    - Nếu là khối Genesis (height == 0 và parent_hash rỗng, proposer_id rỗng):
      block_hash = SHA256("GENESIS" || chain_id)
    - Với các block thường:
      block_hash = SHA256("BLOCK" || enc(header không gồm signature))
    """
    # Nếu truyền vào đối tượng Block thì lấy thuộc tính .header
    target = header_or_block.header if hasattr(header_or_block, "header") else header_or_block

    if isinstance(target, (bytes, bytearray, memoryview)):
        return sha256_hex(enc_str(BLOCK), bytes(target))

    # Kiểm tra trường hợp khối Genesis ở height 0
    if (
        hasattr(target, "height")
        and getattr(target, "height") == 0
        and not getattr(target, "parent_hash", "")
        and not getattr(target, "proposer_id", "")
    ):
        chain_id = getattr(target, "chain_id", "lab01-chain")
        return genesis_hash(chain_id)

    if hasattr(target, "encode_without_signature") and callable(target.encode_without_signature):
        header_bytes = target.encode_without_signature()
        return sha256_hex(enc_str(BLOCK), header_bytes)

    if hasattr(target, "signing_fields") and hasattr(target, "chain_id"):
        # Dự phòng nếu đối tượng chỉ cung cấp chain_id và các trường header
        h_bytes = (
            enc_str(target.chain_id)
            + enc_uint(target.height)
            + enc_str(to_canonical_hash_str(target.parent_hash))
            + enc_str(to_canonical_hash_str(target.tx_root))
            + enc_str(to_canonical_hash_str(target.state_hash))
            + enc_str(target.proposer_id)
            + enc_uint(target.timestamp)
        )
        return sha256_hex(enc_str(BLOCK), h_bytes)

    raise TypeError(f"block_hash yêu cầu Header, Block hoặc bytes, nhận được {type(header_or_block).__name__}")


def msg_id(
    kind_or_msg: Any,
    origin: str | None = None,
    payload: Any = None,
) -> HashHex:
    """
    Tính định danh gói tin mạng (wire message):
    msg_id = SHA256("MSG" || kind || origin || enc(payload))

    Hỗ trợ 2 cách gọi:
    - msg_id(message_obj): truyền đối tượng wire.Message.
    - msg_id(kind, origin, payload): truyền trực tiếp 3 thành phần.
    """
    if origin is None and payload is None and hasattr(kind_or_msg, "kind") and hasattr(kind_or_msg, "origin"):
        msg_obj = kind_or_msg
        msg_kind = str(msg_obj.kind)
        msg_origin = str(msg_obj.origin)
        if hasattr(msg_obj, "encode_payload") and callable(msg_obj.encode_payload):
            payload_bytes = msg_obj.encode_payload()
        else:
            payload_bytes = _encode_wire_payload_fallback(msg_kind, msg_obj.payload)
    else:
        if origin is None:
            raise ValueError("msg_id cần truyền (kind, origin, payload) hoặc một đối tượng Message")
        msg_kind = str(kind_or_msg)
        msg_origin = str(origin)
        payload_bytes = _encode_wire_payload_fallback(msg_kind, payload)

    return sha256_hex(
        enc_str(MSG),
        enc_str(msg_kind),
        enc_str(msg_origin),
        payload_bytes,
    )


def _encode_blocks_entries_fallback(items: Sequence[Any]) -> bytes:
    """Mã hóa danh sách các cặp (block, certificate) trong gói BLOCKS."""
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


def _encode_wire_payload_fallback(kind: str, payload: Any) -> bytes:
    """Mã hóa chuẩn cho payload của wire message theo từng loại kind khi tính msg_id."""
    if payload is None:
        return NIL_BYTES
    if isinstance(payload, (bytes, bytearray, memoryview)):
        return enc_bytes(bytes(payload))
    if hasattr(payload, "encode") and callable(payload.encode):
        res = payload.encode()
        if isinstance(res, bytes):
            return res

    if kind == "STATUS" and isinstance(payload, Mapping):
        height = int(payload.get("height", 0))
        last_hash = str(payload.get("last_hash", payload.get("block_hash", "")))
        return enc_uint(height) + enc_str(last_hash)

    if kind == "GET_BLOCKS" and isinstance(payload, Mapping):
        from_h = int(payload.get("from_height", payload.get("from", 1)))
        to_h = int(payload.get("to_height", payload.get("to", from_h)))
        return enc_uint(from_h) + enc_uint(to_h)

    if kind == "BODY_REQUEST" and isinstance(payload, Mapping):
        height = int(payload.get("height", 0))
        b_hash = str(payload.get("block_hash", ""))
        return enc_uint(height) + enc_str(b_hash)

    if kind == "BODY":
        if isinstance(payload, Mapping):
            height = int(payload.get("height", 0))
            b_hash = str(payload.get("block_hash", ""))
            txs = payload.get("transactions", payload.get("body", payload.get("txs", [])))
            enc_txs = enc_list([tx.encode() if hasattr(tx, "encode") else enc_value(tx) for tx in txs])
            return enc_uint(height) + enc_str(b_hash) + enc_txs
        if isinstance(payload, Sequence):
            return enc_list([tx.encode() if hasattr(tx, "encode") else enc_value(tx) for tx in payload])

    if kind == "BLOCKS":
        if isinstance(payload, Mapping):
            if "entries" in payload:
                return _encode_blocks_entries_fallback(payload["entries"])
            blocks_list = payload.get("blocks", [])
            certs = payload.get("certificates", [])
            if certs and len(certs) == len(blocks_list):
                return _encode_blocks_entries_fallback(list(zip(blocks_list, certs)))
            return _encode_blocks_entries_fallback(blocks_list)
        if isinstance(payload, Sequence):
            return _encode_blocks_entries_fallback(payload)

    if kind == "GET_VOTES" and isinstance(payload, Mapping):
        height = int(payload.get("height", 0))
        round_num = int(payload.get("round", 0))
        return enc_uint(height) + enc_uint(round_num)

    if kind == "VOTES":
        if isinstance(payload, Mapping):
            height = int(payload.get("height", 0))
            round_num = int(payload.get("round", 0))
            votes = payload.get("votes", [])
            enc_votes = enc_list([v.encode() if hasattr(v, "encode") else enc_value(v) for v in votes])
            return enc_uint(height) + enc_uint(round_num) + enc_votes
        if isinstance(payload, Sequence):
            return enc_list([v.encode() if hasattr(v, "encode") else enc_value(v) for v in payload])

    return enc_value(payload)
