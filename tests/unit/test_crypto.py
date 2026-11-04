"""
Kiểm thử đơn vị (Unit Test) cho tầng mật mã (src/crypto/):
- Ký và xác minh chữ ký đúng trên các domain (TX, HEADER, PROPOSAL, VOTE).
- Ký đúng khóa nhưng sai domain phải trả về WRONG_DOMAIN.
- Sửa dữ liệu sau khi ký hoặc dùng khóa khác phải trả về BAD_SIGNATURE.
- Mã hóa chuẩn (enc_uint, enc_bytes, enc_str NFC, enc_list, enc_map) xác định.
- Sinh khóa từ seed lặp lại được hoàn toàn giữa các lần gọi.
"""

from __future__ import annotations

import unicodedata
import unittest

from src.crypto.domain import (
    BAD_SIGNATURE,
    HEADER,
    PROPOSAL,
    ROLE_USER,
    ROLE_VALIDATOR,
    TX,
    VOTE,
    WRONG_DOMAIN,
)
from src.crypto.encoding import (
    NIL_BYTES,
    dec_bytes,
    dec_int,
    dec_list,
    dec_map,
    dec_str,
    dec_uint,
    enc_bytes,
    enc_list,
    enc_map,
    enc_nil,
    enc_str,
    enc_uint,
)
from src.crypto.hashing import (
    block_hash,
    genesis_hash,
    msg_id,
    sha256,
    state_hash,
    tx_id,
    tx_root,
)
from src.crypto.signing import derive_keypair, sign, verify


class TestCrypto(unittest.TestCase):
    """Bộ kiểm thử cho các hàm mã hóa chuẩn, băm và chữ ký số Ed25519."""

    def test_deterministic_key_derivation(self) -> None:
        """Khóa sinh từ cùng seed, role, id phải giống hệt nhau; khác tham số phải khác nhau."""
        sk1, pk1 = derive_keypair(42, ROLE_USER, "alice")
        sk2, pk2 = derive_keypair(42, ROLE_USER, "alice")
        self.assertEqual(sk1, sk2)
        self.assertEqual(pk1, pk2)
        self.assertEqual(len(sk1), 32)
        self.assertEqual(len(pk1), 32)

        # Khác seed hoặc khác role hoặc khác id phải sinh ra cặp khóa khác
        _, pk_diff_seed = derive_keypair(43, ROLE_USER, "alice")
        _, pk_diff_role = derive_keypair(42, ROLE_VALIDATOR, "alice")
        _, pk_diff_id = derive_keypair(42, ROLE_USER, "bob")
        self.assertNotEqual(pk1, pk_diff_seed)
        self.assertNotEqual(pk1, pk_diff_role)
        self.assertNotEqual(pk1, pk_diff_id)

    def test_sign_and_verify_valid(self) -> None:
        """Ký và xác minh hợp lệ trên từng domain."""
        sk, pk = derive_keypair(42, ROLE_USER, "alice")
        fields = ("alice", 1, "alice/chat/1", "Xin chào cả nhà!")
        sig = sign(sk, TX, "lab01-chain", fields)
        self.assertEqual(len(sig), 64)

        ok, reason = verify(pk, TX, "lab01-chain", fields, sig)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_wrong_domain_detection(self) -> None:
        """Ký bằng đúng khóa bí mật nhưng xác minh ở domain khác phải trả về WRONG_DOMAIN."""
        sk, pk = derive_keypair(42, ROLE_VALIDATOR, "N0")
        fields = (1, 0, "ab" * 32, -1)
        sig = sign(sk, PROPOSAL, "lab01-chain", fields)

        # Xác minh nhầm sang domain HEADER hoặc VOTE hoặc TX phải báo WRONG_DOMAIN
        for wrong_dom in (TX, HEADER, VOTE):
            ok, reason = verify(pk, wrong_dom, "lab01-chain", fields, sig)
            self.assertFalse(ok)
            self.assertEqual(reason, WRONG_DOMAIN)

    def test_tampered_data_or_wrong_key_returns_bad_signature(self) -> None:
        """Sửa nội dung sau khi ký hoặc xác minh bằng khóa khác phải trả về BAD_SIGNATURE."""
        sk_alice, pk_alice = derive_keypair(42, ROLE_USER, "alice")
        _, pk_bob = derive_keypair(42, ROLE_USER, "bob")

        fields = ("alice", 1, "alice/chat/1", "Tin nhắn gốc")
        sig = sign(sk_alice, TX, "lab01-chain", fields)

        # 1. Sửa nội dung tin nhắn sau khi ký
        tampered_fields = ("alice", 1, "alice/chat/1", "Tin nhắn đã bị sửa")
        ok1, reason1 = verify(pk_alice, TX, "lab01-chain", tampered_fields, sig)
        self.assertFalse(ok1)
        self.assertEqual(reason1, BAD_SIGNATURE)

        # 2. Dùng khóa công khai của người khác (bob)
        ok2, reason2 = verify(pk_bob, TX, "lab01-chain", fields, sig)
        self.assertFalse(ok2)
        self.assertEqual(reason2, BAD_SIGNATURE)

        # 3. Đổi chain_id khác
        ok3, reason3 = verify(pk_alice, TX, "other-chain", fields, sig)
        self.assertFalse(ok3)
        self.assertEqual(reason3, BAD_SIGNATURE)

    def test_canonical_encoding_determinism(self) -> None:
        """Kiểm tra mã hóa chuẩn cho u64, bytes, string NFC, list, map và NIL."""
        # u64 big-endian
        encoded_num = enc_uint(258)
        self.assertEqual(len(encoded_num), 8)
        decoded_num, off = dec_uint(encoded_num, 0)
        self.assertEqual(decoded_num, 258)
        self.assertEqual(off, 8)

        # Hỗ trợ số âm như pol_round = -1
        encoded_neg = enc_uint(-1)
        decoded_neg, _ = dec_int(encoded_neg, 0)
        self.assertEqual(decoded_neg, -1)

        # Từ chối kiểu số thực (float) và bool
        with self.assertRaises(TypeError):
            enc_uint(1.5)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            enc_uint(True)

        # Chuẩn hóa NFC cho chuỗi tiếng Việt (NFC và NFD phải ra cùng mảng byte)
        s_nfc = unicodedata.normalize("NFC", "Tiếng Việt có dấu")
        s_nfd = unicodedata.normalize("NFD", "Tiếng Việt có dấu")
        self.assertNotEqual(len(s_nfc), len(s_nfd))
        self.assertEqual(enc_str(s_nfc), enc_str(s_nfd))
        dec_s, _ = dec_str(enc_str(s_nfd), 0)
        self.assertEqual(dec_s, s_nfc)

        # Mã hóa map không phụ thuộc thứ tự chèn key
        m1 = {"b": "2", "a": "1", "c": "3"}
        m2 = {"c": "3", "a": "1", "b": "2"}
        self.assertEqual(enc_map(m1), enc_map(m2))
        dec_m, _ = dec_map(enc_map(m1), 0)
        self.assertEqual(dec_m, m1)

        # NIL là 32 byte 0
        self.assertEqual(enc_nil(), b"\x00" * 32)
        self.assertEqual(len(NIL_BYTES), 32)

        # Mã hóa và giải mã list
        lst = ["mot", "hai", "ba"]
        enc_l = enc_list(lst)
        dec_l, _ = dec_list(enc_l, dec_str, 0)
        self.assertEqual(dec_l, lst)

        # Mã hóa và giải mã bytes
        raw = b"\x01\x02\x03\xff"
        dec_b, _ = dec_bytes(enc_bytes(raw), 0)
        self.assertEqual(dec_b, raw)

    def test_hashing_helpers(self) -> None:
        """Kiểm tra các hàm băm tiện ích tx_id, state_hash, tx_root, genesis_hash, msg_id."""
        self.assertEqual(len(sha256(b"abc")), 32)
        t1 = tx_id("alice", 1, "alice/chat/1", "hello")
        t2 = tx_id("alice", 1, "alice/chat/1", "hello")
        self.assertEqual(t1, t2)
        self.assertEqual(len(t1), 64)

        sh1 = state_hash({"alice/chat/1": "a", "bob/chat/1": "b"})
        sh2 = state_hash({"bob/chat/1": "b", "alice/chat/1": "a"})
        self.assertEqual(sh1, sh2)

        root = tx_root([t1, t2])
        self.assertEqual(len(root), 64)

        gh = genesis_hash("lab01-chain")
        self.assertEqual(len(gh), 64)

        mid = msg_id("STATUS", "N0", {"height": 1, "last_hash": gh})
        self.assertEqual(len(mid), 64)
        self.assertEqual(len(mid[:6]), 6)

    def test_msg_id_consistency_and_wire_roundtrip(self) -> None:
        """
        Kiểm tra tính nhất quán tuyệt đối giữa msg.msg_id, msg_id(msg) và msg_id(kind, origin, payload),
        cũng như mã hóa/giải mã round-trip cho toàn bộ 14 loại wire message và Vote NIL.
        """
        from src.core.block import make_genesis_block
        from src.core.user import User
        from src.core.vote import PREVOTE, Vote
        from src.core.wire import (
            HELLO,
            PING,
            PONG,
            Message,
            make_blocks_message,
            make_status_message,
            make_tx_message,
            make_vote_message,
        )

        u = User.from_seed(42, "alice")
        tx = u.make_message("Xin chào")
        m_tx = make_tx_message("N0", tx)
        self.assertEqual(m_tx.msg_id, msg_id(m_tx))
        self.assertEqual(m_tx.msg_id, msg_id(m_tx.kind, m_tx.origin, tx))

        gh = genesis_hash("lab01-chain")
        m_st = make_status_message("N0", 1, str(gh))
        self.assertEqual(m_st.msg_id, msg_id(m_st))
        self.assertEqual(m_st.msg_id, msg_id(m_st.kind, m_st.origin, m_st.payload))

        # Vote NIL phải dùng đúng 32 byte 0 (NIL_BYTES) khi encode() và giải mã round-trip chính xác
        v_nil = Vote(height=1, round=0, phase=PREVOTE, block_hash=None, validator_id="N0")
        self.assertIn(NIL_BYTES, v_nil.encode())
        v_dec = Vote.from_bytes(v_nil.encode())
        self.assertTrue(v_dec.is_nil)
        self.assertEqual(v_nil, v_dec)

        # Kiểm tra round-trip Message.encode() / Message.decode() cho HELLO, PING, PONG và BLOCKS có cert=None
        gen = make_genesis_block()
        for w_msg in (
            Message(HELLO, "N0", {"peer": "N0"}),
            Message(PING, "N0", b"ping-bytes"),
            Message(PONG, "N0", None),
            make_vote_message("N0", v_nil),
            make_blocks_message("N0", [(gen, None), (gen, None)]),
        ):
            encoded = w_msg.encode()
            decoded, end_off = Message.decode(encoded, 0)
            self.assertEqual(end_off, len(encoded))
            self.assertEqual(w_msg.msg_id, decoded.msg_id)


def run_tests() -> bool:
    """Chạy toàn bộ test trong file này và trả về True nếu tất cả đều PASS."""
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestCrypto)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    return result.wasSuccessful()


run = run_tests

if __name__ == "__main__":
    unittest.main()
