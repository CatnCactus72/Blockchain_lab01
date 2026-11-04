"""
Mã hóa chuẩn (canonical encoding) cho mọi dữ liệu được băm hoặc ký trong Chat Chain.
Tuyệt đối không dùng JSON hay hàm hash() của Python cho dữ liệu mật mã để đảm bảo
tính xác định tuyệt đối giữa các lần chạy.

Quy tắc mã hóa chuẩn (Mục 6 README):
- Số nguyên: u64 big-endian, độ rộng cố định 8 byte, không dùng số thực (float/bool).
- bytes: tiền tố độ dài u32 (4 byte big-endian) + nội dung.
- string: chuẩn hóa Unicode NFC rồi mã hóa UTF-8, đóng gói như bytes.
- list: u32 số phần tử + các phần tử đã mã hóa nối tiếp theo đúng thứ tự.
- map: các cặp (key, value) được sắp xếp theo thứ tự byte của key.
- NIL / không có: 32 byte 0.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping, Sequence
from typing import Any

# Hằng số biểu diễn giá trị NIL / không có (32 byte 0)
NIL_BYTES: bytes = b"\x00" * 32
NIL_STR: str = "NIL"

# Giới hạn số nguyên 64-bit
MAX_U64: int = (1 << 64) - 1
MIN_I64: int = -(1 << 63)
MAX_U32: int = (1 << 32) - 1


def normalize_nfc(text: str) -> str:
    """Chuẩn hóa chuỗi Unicode về dạng chuẩn NFC."""
    if not isinstance(text, str):
        raise TypeError(f"normalize_nfc yêu cầu kiểu str, nhận được {type(text).__name__}")
    return unicodedata.normalize("NFC", text)


def count_nfc_chars(text: str) -> int:
    """Đếm số lượng code point của chuỗi sau khi đã chuẩn hóa NFC."""
    return len(normalize_nfc(text))


def enc_u32(value: int) -> bytes:
    """Mã hóa số nguyên không dấu 32-bit theo chuẩn big-endian (4 byte) dùng làm tiền tố độ dài."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"enc_u32 chỉ nhận số nguyên int, nhận được {type(value).__name__}")
    if value < 0 or value > MAX_U32:
        raise ValueError(f"Giá trị u32 nằm ngoài phạm vi [0, {MAX_U32}]: {value}")
    return value.to_bytes(4, byteorder="big", signed=False)


def dec_u32(data: bytes, offset: int = 0) -> tuple[int, int]:
    """Giải mã số nguyên không dấu 32-bit big-endian tại vị trí offset."""
    if offset < 0 or offset + 4 > len(data):
        raise ValueError("Không đủ dữ liệu để giải mã u32")
    val = int.from_bytes(data[offset : offset + 4], byteorder="big", signed=False)
    return val, offset + 4


def enc_uint(value: int) -> bytes:
    """
    Mã hóa số nguyên thành 8 byte u64 big-endian cố định.
    Hỗ trợ số âm trong phạm vi i64 (ví dụ pol_round = -1) bằng biểu diễn bù 2 64-bit,
    và từ chối kiểu float hoặc bool để đảm bảo tính xác định.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"enc_uint chỉ nhận số nguyên int (không nhận float/bool), nhận được {type(value).__name__}")
    if value < MIN_I64 or value > MAX_U64:
        raise ValueError(f"Số nguyên vượt quá phạm vi 64-bit: {value}")
    # Chuyển số âm (như pol_round = -1) sang biểu diễn 64-bit không dấu tương ứng
    unsigned_val = value & MAX_U64
    return unsigned_val.to_bytes(8, byteorder="big", signed=False)


# Bí danh cho enc_uint
enc_u64 = enc_uint
enc_int = enc_uint


def dec_uint(data: bytes, offset: int = 0) -> tuple[int, int]:
    """Giải mã số nguyên không dấu 64-bit big-endian từ chuỗi byte tại vị trí offset."""
    if offset < 0 or offset + 8 > len(data):
        raise ValueError("Không đủ dữ liệu để giải mã u64")
    val = int.from_bytes(data[offset : offset + 8], byteorder="big", signed=False)
    return val, offset + 8


def dec_int(data: bytes, offset: int = 0) -> tuple[int, int]:
    """Giải mã số nguyên có dấu 64-bit big-endian (dùng cho trường có thể bằng -1 như pol_round)."""
    if offset < 0 or offset + 8 > len(data):
        raise ValueError("Không đủ dữ liệu để giải mã i64")
    val = int.from_bytes(data[offset : offset + 8], byteorder="big", signed=True)
    return val, offset + 8


def enc_nil() -> bytes:
    """Mã hóa giá trị NIL / không có thành 32 byte 0."""
    return NIL_BYTES


def enc_bytes(data: bytes | bytearray | memoryview | None) -> bytes:
    """
    Mã hóa mảng byte với tiền tố độ dài u32 (4 byte big-endian) + nội dung.
    Nếu data là None, trả về 32 byte 0 (NIL_BYTES).
    """
    if data is None:
        return NIL_BYTES
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"enc_bytes yêu cầu kiểu bytes, nhận được {type(data).__name__}")
    raw = bytes(data)
    return enc_u32(len(raw)) + raw


def dec_bytes(data: bytes, offset: int = 0) -> tuple[bytes, int]:
    """Giải mã mảng byte có tiền tố độ dài u32 tại vị trí offset."""
    length, next_offset = dec_u32(data, offset)
    end_offset = next_offset + length
    if end_offset > len(data):
        raise ValueError(f"Không đủ dữ liệu để giải mã bytes (cần {length} byte)")
    return bytes(data[next_offset:end_offset]), end_offset


def enc_str(text: str) -> bytes:
    """
    Mã hóa chuỗi ký tự: chuẩn hóa Unicode sang NFC, chuyển thành UTF-8,
    sau đó đóng gói như bytes (tiền tố độ dài u32 + nội dung UTF-8).
    """
    if not isinstance(text, str):
        raise TypeError(f"enc_str yêu cầu kiểu str, nhận được {type(text).__name__}")
    normalized_utf8 = normalize_nfc(text).encode("utf-8")
    return enc_bytes(normalized_utf8)


def dec_str(data: bytes, offset: int = 0) -> tuple[str, int]:
    """Giải mã chuỗi ký tự từ dữ liệu đã mã hóa chuẩn và chuẩn hóa về NFC."""
    raw_bytes, next_offset = dec_bytes(data, offset)
    text = raw_bytes.decode("utf-8")
    return normalize_nfc(text), next_offset


def enc_value(val: Any) -> bytes:
    """
    Hàm tiện ích tự động chọn quy tắc mã hóa chuẩn dựa trên kiểu dữ liệu của phần tử:
    - None -> 32 byte 0 (NIL_BYTES)
    - bytes/bytearray/memoryview -> nếu đã là phần tử byte hoặc dữ liệu thô
    - str -> enc_str(val)
    - int (không phải bool) -> enc_uint(val)
    - list/tuple -> enc_list(val)
    - dict/Mapping -> enc_map(val)
    - Đối tượng có phương thức encode() -> val.encode()
    """
    if val is None:
        return NIL_BYTES
    if isinstance(val, bool):
        raise TypeError("Không dùng kiểu bool trực tiếp trong mã hóa chuẩn (dùng int hoặc str)")
    if isinstance(val, int):
        return enc_uint(val)
    if isinstance(val, str):
        return enc_str(val)
    if isinstance(val, (bytes, bytearray, memoryview)):
        return enc_bytes(bytes(val))
    if isinstance(val, Mapping):
        return enc_map(val)
    if isinstance(val, (list, tuple)):
        return enc_list(val)
    if hasattr(val, "encode") and callable(val.encode):
        encoded = val.encode()
        if isinstance(encoded, bytes):
            return encoded
    raise TypeError(f"Không hỗ trợ kiểu dữ liệu trong mã hóa chuẩn: {type(val).__name__}")


def enc_list(
    items: Sequence[Any],
    item_encoder: Callable[[Any], bytes] | None = None,
) -> bytes:
    """
    Mã hóa danh sách phần tử: tiền tố u32 (số lượng phần tử) + các phần tử nối tiếp theo thứ tự.
    - Nếu truyền item_encoder: áp dụng item_encoder cho từng phần tử.
    - Nếu phần tử đã là bytes: nối trực tiếp phần tử bytes đó.
    - Nếu phần tử là str/int/dict/list/None: tự động mã hóa chuẩn từng phần tử.
    """
    if not isinstance(items, (Sequence, list, tuple)) or isinstance(items, (str, bytes, bytearray)):
        raise TypeError("enc_list yêu cầu đầu vào là một danh sách (list/tuple)")
    parts: list[bytes] = [enc_u32(len(items))]
    for item in items:
        if item_encoder is not None:
            parts.append(item_encoder(item))
        elif isinstance(item, (bytes, bytearray, memoryview)):
            parts.append(bytes(item))
        else:
            parts.append(enc_value(item))
    return b"".join(parts)


def dec_list(
    data: bytes,
    item_decoder: Callable[[bytes, int], tuple[Any, int]] = dec_str,
    offset: int = 0,
) -> tuple[list[Any], int]:
    """Giải mã danh sách phần tử tại vị trí offset bằng hàm giải mã phần tử item_decoder."""
    count, cur_offset = dec_u32(data, offset)
    result: list[Any] = []
    for _ in range(count):
        item, cur_offset = item_decoder(data, cur_offset)
        result.append(item)
    return result, cur_offset


def _key_to_raw_and_encoded(key: str | bytes) -> tuple[bytes, bytes]:
    """
    Chuyển key của map thành cặp (raw_bytes để sắp xếp, encoded_bytes để ghi).
    Đảm bảo các cặp trong map luôn được sắp xếp theo đúng thứ tự byte của key.
    """
    if isinstance(key, str):
        raw_key = normalize_nfc(key).encode("utf-8")
        return raw_key, enc_bytes(raw_key)
    if isinstance(key, (bytes, bytearray, memoryview)):
        raw_key = bytes(key)
        return raw_key, enc_bytes(raw_key)
    raise TypeError(f"Key của map phải là str hoặc bytes, nhận được {type(key).__name__}")


def enc_map(
    mapping: Mapping[Any, Any],
    value_encoder: Callable[[Any], bytes] | None = None,
) -> bytes:
    """
    Mã hóa map (từ điển key-value):
    Các cặp (key, value) được sắp xếp tăng dần theo mảng byte của key (UTF-8 NFC đối với chuỗi),
    đảm bảo kết quả mã hóa hoàn toàn độc lập với thứ tự chèn key vào dict.
    """
    if not isinstance(mapping, Mapping):
        raise TypeError(f"enc_map yêu cầu kiểu Mapping/dict, nhận được {type(mapping).__name__}")

    prepared_pairs: list[tuple[bytes, bytes, bytes]] = []
    for k, v in mapping.items():
        raw_key, enc_k = _key_to_raw_and_encoded(k)
        if value_encoder is not None:
            enc_v = value_encoder(v)
        elif isinstance(v, (bytes, bytearray, memoryview)):
            enc_v = enc_bytes(bytes(v))
        else:
            enc_v = enc_value(v)
        prepared_pairs.append((raw_key, enc_k, enc_v))

    # Sắp xếp nghiêm ngặt theo thứ tự byte của key
    prepared_pairs.sort(key=lambda item: item[0])

    parts: list[bytes] = [enc_u32(len(prepared_pairs))]
    for _, enc_k, enc_v in prepared_pairs:
        parts.append(enc_k)
        parts.append(enc_v)
    return b"".join(parts)


def dec_map(
    data: bytes,
    offset: int = 0,
    key_decoder: Callable[[bytes, int], tuple[Any, int]] = dec_str,
    value_decoder: Callable[[bytes, int], tuple[Any, int]] = dec_str,
) -> tuple[dict[Any, Any], int]:
    """Giải mã map đã được mã hóa bằng enc_map tại vị trí offset."""
    count, cur_offset = dec_u32(data, offset)
    result: dict[Any, Any] = {}
    for _ in range(count):
        k, cur_offset = key_decoder(data, cur_offset)
        v, cur_offset = value_decoder(data, cur_offset)
        result[k] = v
    return result, cur_offset
