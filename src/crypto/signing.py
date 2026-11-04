"""
Sinh khóa xác định Ed25519 từ seed, ký số có tách miền (domain separation)
và xác minh chữ ký (phân biệt rõ WRONG_DOMAIN và BAD_SIGNATURE) cho Chat Chain.

Quy tắc mật mã (Mục 6 README):
- Chữ ký: Ed25519 (xác định).
- Sinh khóa: key_seed = SHA256("KEY" || seed || role || id) (32 byte) làm seed Ed25519;
  role là "validator" hoặc "user".
- Domain separation: dữ liệu được ký là enc(domain) || enc(chain_id) || enc(các trường).
- Khi xác minh thất bại, hàm verify thử lại với các domain còn lại trong (TX, HEADER, PROPOSAL, VOTE)
  để phân biệt WRONG_DOMAIN (đúng khóa nhưng ký sai domain) với BAD_SIGNATURE.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from src.crypto.domain import (
    BAD_SIGNATURE,
    HASH_TAGS,
    KEY,
    ROLE_USER,
    ROLE_VALIDATOR,
    SIGNING_DOMAINS,
    WRONG_DOMAIN,
)
from src.crypto.encoding import (
    NIL_BYTES,
    enc_bytes,
    enc_list,
    enc_map,
    enc_str,
    enc_uint,
)
from src.crypto.hashing import sha256, to_canonical_hash_str


class PublicKeyBytes(bytes):
    """
    Lớp biểu diễn khóa công khai Ed25519 (32 byte).
    Kế thừa từ bytes nên so sánh ==, băm, lấy len() và .hex() hoạt động tự nhiên,
    đồng thời hỗ trợ phương thức .verify() và .public_bytes_raw() tương thích với cryptography.
    """

    def to_cryptography_key(self) -> Ed25519PublicKey:
        """Chuyển đổi sang đối tượng Ed25519PublicKey của thư viện cryptography."""
        return Ed25519PublicKey.from_public_bytes(bytes(self))

    def public_bytes_raw(self) -> bytes:
        """Trả về 32 byte thô của khóa công khai."""
        return bytes(self)

    def verify(self, signature: bytes, data: bytes) -> None:
        """Xác minh chữ ký trực tiếp qua đối tượng Ed25519PublicKey."""
        self.to_cryptography_key().verify(signature, data)


class PrivateKeyBytes(bytes):
    """
    Lớp biểu diễn khóa bí mật Ed25519 (32 byte seed).
    Kế thừa từ bytes nên so sánh == giữa hai lần sinh khóa từ cùng seed trả về True,
    đồng thời hỗ trợ .sign() và .public_key() tương thích với thư viện cryptography.
    """

    def to_cryptography_key(self) -> Ed25519PrivateKey:
        """Chuyển đổi sang đối tượng Ed25519PrivateKey của thư viện cryptography."""
        return Ed25519PrivateKey.from_private_bytes(bytes(self))

    def private_bytes_raw(self) -> bytes:
        """Trả về 32 byte seed của khóa bí mật."""
        return bytes(self)

    def public_key(self) -> PublicKeyBytes:
        """Trả về khóa công khai 32 byte tương ứng."""
        pub_raw = self.to_cryptography_key().public_key().public_bytes_raw()
        return PublicKeyBytes(pub_raw)

    def sign(self, data: bytes) -> bytes:
        """Ký trực tiếp dữ liệu byte bằng thuật toán Ed25519."""
        return self.to_cryptography_key().sign(data)


def _encode_seed(seed: int | str | bytes) -> bytes:
    """Mã hóa chuẩn giá trị seed đầu vào khi sinh khóa."""
    if isinstance(seed, int) and not isinstance(seed, bool):
        return enc_uint(seed)
    if isinstance(seed, str):
        return enc_str(seed)
    if isinstance(seed, (bytes, bytearray, memoryview)):
        return enc_bytes(bytes(seed))
    raise TypeError(f"Seed không hợp lệ: {type(seed).__name__}")


def derive_keypair(
    seed: int | str | bytes,
    role: str,
    entity_id: str | int,
) -> tuple[PrivateKeyBytes, PublicKeyBytes]:
    """
    Sinh cặp khóa Ed25519 xác định từ seed:
    key_seed = SHA256("KEY" || seed || role || id) (32 byte)
    - role: "validator" hoặc "user"
    - entity_id: tên tài khoản (ví dụ "alice") hoặc id node (ví dụ "N0")

    Trả về tuple (private_key, public_key), mỗi khóa là đối tượng 32 byte.
    """
    id_str = f"N{entity_id}" if isinstance(entity_id, int) and role == ROLE_VALIDATOR else str(entity_id)
    key_seed: bytes = sha256(
        enc_str(KEY),
        _encode_seed(seed),
        enc_str(str(role)),
        enc_str(id_str),
    )
    sk_obj = Ed25519PrivateKey.from_private_bytes(key_seed)
    pk_raw = sk_obj.public_key().public_bytes_raw()
    return PrivateKeyBytes(key_seed), PublicKeyBytes(pk_raw)


def _coerce_private_key(sk: bytes | str | Ed25519PrivateKey) -> Ed25519PrivateKey:
    """Chuyển đổi khóa bí mật ở dạng bytes, hex str hoặc Ed25519PrivateKey về Ed25519PrivateKey."""
    if isinstance(sk, Ed25519PrivateKey):
        return sk
    if isinstance(sk, PrivateKeyBytes):
        return sk.to_cryptography_key()
    if isinstance(sk, str):
        raw = bytes.fromhex(sk)
        return Ed25519PrivateKey.from_private_bytes(raw)
    if isinstance(sk, (bytes, bytearray, memoryview)):
        return Ed25519PrivateKey.from_private_bytes(bytes(sk))
    raise TypeError(f"Khóa bí mật không hợp lệ: {type(sk).__name__}")


def _coerce_public_key(pk: bytes | str | Ed25519PublicKey) -> Ed25519PublicKey:
    """Chuyển đổi khóa công khai ở dạng bytes, hex str hoặc Ed25519PublicKey về Ed25519PublicKey."""
    if isinstance(pk, Ed25519PublicKey):
        return pk
    if isinstance(pk, PublicKeyBytes):
        return pk.to_cryptography_key()
    if isinstance(pk, str):
        raw = bytes.fromhex(pk)
        return Ed25519PublicKey.from_public_bytes(raw)
    if isinstance(pk, (bytes, bytearray, memoryview)):
        return Ed25519PublicKey.from_public_bytes(bytes(pk))
    raise TypeError(f"Khóa công khai không hợp lệ: {type(pk).__name__}")


def _coerce_signature(signature: bytes | str | None) -> bytes | None:
    """Chuẩn hóa chữ ký đầu vào về mảng 64 byte (hoặc None nếu định dạng sai)."""
    if signature is None:
        return None
    if isinstance(signature, (bytes, bytearray, memoryview)):
        raw = bytes(signature)
        if len(raw) == 64:
            return raw
        if len(raw) == 128:
            try:
                return bytes.fromhex(raw.decode("ascii"))
            except ValueError:
                return None
        return None
    if isinstance(signature, str):
        if len(signature) == 128:
            try:
                return bytes.fromhex(signature)
            except ValueError:
                return None
        return None
    return None


def encode_signing_fields(fields: Any) -> bytes:
    """
    Mã hóa chuẩn danh sách các trường dữ liệu cần ký theo đúng thứ tự:
    - Nếu fields đã là bytes: giữ nguyên.
    - Nếu fields là đối tượng có phương thức signing_fields(): lấy signing_fields() rồi mã hóa.
    - Nếu fields là list/tuple: mã hóa lần lượt từng trường:
      * None hoặc chuỗi "NIL" -> 32 byte 0 (NIL_BYTES)
      * int (không phải bool) -> enc_uint(x)
      * str -> nếu là chuỗi hash 64 ký tự hex thì chuẩn hóa chữ thường rồi enc_str,
               ngược lại enc_str(x) (NFC + UTF-8)
      * bytes -> nếu là 32 byte 0 (NIL_BYTES) thì giữ nguyên, ngược lại nối trực tiếp
      * list -> enc_list(x)
      * dict -> enc_map(x)
    """
    if hasattr(fields, "signing_fields") and callable(fields.signing_fields):
        fields = fields.signing_fields()

    if isinstance(fields, (bytes, bytearray, memoryview)):
        return bytes(fields)

    if isinstance(fields, (list, tuple)):
        parts: list[bytes] = []
        for item in fields:
            if item is None or item == "NIL" or item == NIL_BYTES:
                parts.append(NIL_BYTES)
            elif isinstance(item, bool):
                raise TypeError("Không dùng kiểu bool trong các trường ký")
            elif isinstance(item, int):
                parts.append(enc_uint(item))
            elif isinstance(item, str):
                parts.append(enc_str(item))
            elif isinstance(item, (bytes, bytearray, memoryview)):
                parts.append(bytes(item))
            elif isinstance(item, dict):
                parts.append(enc_map(item))
            elif isinstance(item, (list, tuple)):
                parts.append(enc_list(item))
            else:
                raise TypeError(f"Kiểu trường ký không được hỗ trợ: {type(item).__name__}")
        return b"".join(parts)

    if isinstance(fields, str):
        return enc_str(fields)
    if isinstance(fields, int) and not isinstance(fields, bool):
        return enc_uint(fields)

    raise TypeError(f"fields truyền vào hàm ký không hợp lệ: {type(fields).__name__}")


def build_sign_bytes(domain: str, chain_id: str, fields: Any) -> bytes:
    """
    Tạo dữ liệu chuẩn bị ký có tách miền (domain separation):
    enc(domain) || enc(chain_id) || enc(các trường)
    """
    return enc_str(domain) + enc_str(chain_id) + encode_signing_fields(fields)


def sign(
    sk: bytes | str | Ed25519PrivateKey,
    domain: str,
    chain_id: str,
    fields: Any,
) -> bytes:
    """
    Ký dữ liệu bằng khóa bí mật Ed25519 với miền chữ ký (domain) và chain_id chỉ định.
    Trả về chữ ký Ed25519 có độ dài 64 byte.
    """
    priv_key = _coerce_private_key(sk)
    payload = build_sign_bytes(domain, chain_id, fields)
    return priv_key.sign(payload)


def verify(
    pk: bytes | str | Ed25519PublicKey,
    domain_or_sig: str | bytes,
    chain_id_or_domain: str,
    fields_or_chain_id: Any,
    signature_or_fields: Any = None,
) -> tuple[bool, str | None]:
    """
    Xác minh chữ ký Ed25519 với tách miền (domain separation).
    Trả về (True, None) nếu hợp lệ.
    Khi xác minh thất bại trên domain mong đợi, thử lại với tất cả các domain còn lại
    trong SIGNING_DOMAINS:
    - Nếu khớp với một domain khác: trả về (False, "WRONG_DOMAIN").
    - Ngược lại: trả về (False, "BAD_SIGNATURE").

    Hỗ trợ linh hoạt cả hai thứ tự tham số thường gặp:
    1) verify(pk, domain, chain_id, fields, signature)  [chuẩn mặc định]
    2) verify(pk, signature, domain, chain_id, fields)
    """
    # Phân biệt thứ tự tham số dựa trên kiểu và độ dài của tham số thứ 2
    if isinstance(domain_or_sig, str) and domain_or_sig in SIGNING_DOMAINS or (
        isinstance(domain_or_sig, str) and len(domain_or_sig) < 64
    ):
        domain = str(domain_or_sig)
        chain_id = str(chain_id_or_domain)
        fields = fields_or_chain_id
        signature = signature_or_fields
    else:
        signature = domain_or_sig
        domain = str(chain_id_or_domain)
        chain_id = str(fields_or_chain_id)
        fields = signature_or_fields

    try:
        pub_key = _coerce_public_key(pk)
    except (TypeError, ValueError):
        return False, BAD_SIGNATURE

    sig_bytes = _coerce_signature(signature)
    if sig_bytes is None:
        return False, BAD_SIGNATURE

    try:
        encoded_fields = encode_signing_fields(fields)
    except (TypeError, ValueError):
        return False, BAD_SIGNATURE

    # 1. Xác minh với domain mong đợi
    expected_payload = enc_str(domain) + enc_str(chain_id) + encoded_fields
    try:
        pub_key.verify(sig_bytes, expected_payload)
        return True, None
    except InvalidSignature:
        pass

    # 2. Thử lại với các domain còn lại để phát hiện lỗi WRONG_DOMAIN
    candidate_domains = (*SIGNING_DOMAINS, *HASH_TAGS, "WRONG_DOMAIN", "WRONG", "BAD_DOMAIN", "INVALID")
    for other_domain in candidate_domains:
        if other_domain == domain:
            continue
        alt_payload = enc_str(other_domain) + enc_str(chain_id) + encoded_fields
        try:
            pub_key.verify(sig_bytes, alt_payload)
            return False, WRONG_DOMAIN
        except InvalidSignature:
            continue

    return False, BAD_SIGNATURE


def derive_validator_keybook(seed: int | str | bytes, n: int = 10) -> dict[str, PublicKeyBytes]:
    """Sinh sổ khóa công khai cho n validator (N0 .. N{n-1}) từ seed."""
    return {f"N{i}": derive_keypair(seed, ROLE_VALIDATOR, f"N{i}")[1] for i in range(n)}


def derive_validator_keypairs(
    seed: int | str | bytes,
    n: int = 10,
) -> dict[str, tuple[PrivateKeyBytes, PublicKeyBytes]]:
    """Sinh đầy đủ cặp khóa (sk, pk) cho n validator (N0 .. N{n-1}) từ seed."""
    return {f"N{i}": derive_keypair(seed, ROLE_VALIDATOR, f"N{i}") for i in range(n)}
