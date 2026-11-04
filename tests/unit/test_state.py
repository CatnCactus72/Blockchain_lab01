"""
Kiểm thử đơn vị (Unit Test) cho tầng thực thi trạng thái (src/execution/):
- Áp dụng giao dịch hợp lệ vào State.
- Từ chối các giao dịch vi phạm quy tắc với đúng mã lý do:
  UNKNOWN_ACCOUNT, BAD_SIGNATURE, WRONG_DOMAIN, NOT_OWNER, BAD_KEY,
  BAD_NONCE, REPLAYED_TX.
- Kiểm tra state_hash hoàn toàn không phụ thuộc vào thứ tự chèn key vào State.
"""

from __future__ import annotations

import unittest

from src.core.transaction import Transaction
from src.core.user import create_account_book, create_users
from src.crypto.domain import HEADER
from src.crypto.signing import sign
from src.execution.executor import (
    BAD_KEY,
    BAD_NONCE,
    BAD_SIGNATURE,
    NOT_OWNER,
    REPLAYED_TX,
    UNKNOWN_ACCOUNT,
    WRONG_DOMAIN,
    apply_block,
    apply_tx,
)
from src.execution.state import State


class TestStateExecution(unittest.TestCase):
    """Bộ kiểm thử cho lớp State và bộ thực thi giao dịch executor."""

    def setUp(self) -> None:
        self.seed = 42
        self.chain_id = "lab01-chain"
        self.account_book = create_account_book(self.seed)
        self.users = create_users(self.seed, chain_id=self.chain_id)

    def test_apply_valid_tx_and_nonce_progression(self) -> None:
        """Áp dụng giao dịch hợp lệ làm cập nhật State và tăng bộ đếm nonce."""
        state = State()
        alice = self.users["alice"]

        tx1 = alice.make_message("Chào buổi sáng!")
        ok1, reason1 = apply_tx(state, tx1, account_pubkeys=self.account_book, chain_id=self.chain_id)
        self.assertTrue(ok1)
        self.assertIsNone(reason1)
        self.assertEqual(state.get("alice/chat/1"), "Chào buổi sáng!")
        self.assertEqual(state.get_nonce("alice"), 1)

        tx2 = alice.make_message("Tin nhắn thứ hai")
        ok2, reason2 = apply_tx(state, tx2, account_pubkeys=self.account_book, chain_id=self.chain_id)
        self.assertTrue(ok2)
        self.assertIsNone(reason2)
        self.assertEqual(state.get("alice/chat/2"), "Tin nhắn thứ hai")
        self.assertEqual(state.get_nonce("alice"), 2)

    def test_reject_not_owner(self) -> None:
        """Từ chối giao dịch ghi vào không gian tên của người khác (NOT_OWNER)."""
        state = State()
        alice = self.users["alice"]
        # alice cố tình ghi vào key của bob
        bad_tx = alice.make_message("Giả mạo vùng nhớ bob", nonce=1, key="bob/chat/1")
        ok, reason = apply_tx(state, bad_tx, account_pubkeys=self.account_book, chain_id=self.chain_id)
        self.assertFalse(ok)
        self.assertEqual(reason, NOT_OWNER)

    def test_reject_bad_key(self) -> None:
        """Từ chối giao dịch có key bắt đầu bằng '<account>/' nhưng sai cấu trúc '<account>/chat/<nonce>' (BAD_KEY)."""
        state = State()
        alice = self.users["alice"]

        # Sai nhánh con ('profile' thay vì 'chat')
        tx_wrong_path = alice.make_message("Sai đường dẫn", nonce=1, key="alice/profile/1")
        ok1, reason1 = apply_tx(state, tx_wrong_path, account_pubkeys=self.account_book, chain_id=self.chain_id)
        self.assertFalse(ok1)
        self.assertEqual(reason1, BAD_KEY)

        # Số nonce trong key lệch với trường nonce của tx
        tx_mismatch_nonce = alice.make_message("Lệch nonce trong key", nonce=1, key="alice/chat/2")
        ok2, reason2 = apply_tx(state, tx_mismatch_nonce, account_pubkeys=self.account_book, chain_id=self.chain_id)
        self.assertFalse(ok2)
        self.assertEqual(reason2, BAD_KEY)

    def test_reject_bad_nonce_and_replayed_tx(self) -> None:
        """Từ chối giao dịch nhảy cóc nonce (BAD_NONCE) hoặc gửi lại nonce cũ (REPLAYED_TX)."""
        state = State()
        alice = self.users["alice"]

        # Chưa áp dụng nonce 1 mà gửi ngay nonce 2 -> BAD_NONCE
        tx_future = alice.make_message("Nhảy cóc nonce 2", nonce=2)
        ok_future, reason_future = apply_tx(
            state, tx_future, account_pubkeys=self.account_book, chain_id=self.chain_id
        )
        self.assertFalse(ok_future)
        self.assertEqual(reason_future, BAD_NONCE)

        # Áp dụng nonce 1 hợp lệ
        tx1 = alice.make_message("Tin nhắn số 1", nonce=1)
        ok1, _ = apply_tx(state, tx1, account_pubkeys=self.account_book, chain_id=self.chain_id)
        self.assertTrue(ok1)

        # Gửi lại chính tx1 (nonce 1 <= applied_nonce 1) -> REPLAYED_TX
        ok_replay, reason_replay = apply_tx(
            state, tx1, account_pubkeys=self.account_book, chain_id=self.chain_id
        )
        self.assertFalse(ok_replay)
        self.assertEqual(reason_replay, REPLAYED_TX)

    def test_reject_unknown_account_and_bad_signatures(self) -> None:
        """Từ chối tài khoản lạ (UNKNOWN_ACCOUNT), chữ ký sai (BAD_SIGNATURE) và sai domain (WRONG_DOMAIN)."""
        state = State()
        alice = self.users["alice"]

        # 1. Tài khoản không có trong sổ tài khoản
        unknown_tx = Transaction(
            account="mallory",
            nonce=1,
            key="mallory/chat/1",
            value="Tin nhắn từ tài khoản lạ",
            signature=b"\x00" * 64,
        )
        ok_unk, reason_unk = apply_tx(
            state, unknown_tx, account_pubkeys=self.account_book, chain_id=self.chain_id
        )
        self.assertFalse(ok_unk)
        self.assertEqual(reason_unk, UNKNOWN_ACCOUNT)

        # 2. Ký đúng khóa nhưng dùng sai domain (HEADER thay vì TX)
        wrong_dom_tx = Transaction(
            account="alice",
            nonce=1,
            key="alice/chat/1",
            value="Ký sai miền",
        )
        wrong_dom_tx.signature = sign(
            alice.private_key, HEADER, self.chain_id, wrong_dom_tx.signing_fields()
        )
        ok_dom, reason_dom = apply_tx(
            state, wrong_dom_tx, account_pubkeys=self.account_book, chain_id=self.chain_id
        )
        self.assertFalse(ok_dom)
        self.assertEqual(reason_dom, WRONG_DOMAIN)

        # 3. Sửa nội dung sau khi ký -> BAD_SIGNATURE
        tampered_tx = alice.make_message("Nội dung chuẩn", nonce=1)
        tampered_tx.value = "Nội dung bị can thiệp"
        ok_sig, reason_sig = apply_tx(
            state, tampered_tx, account_pubkeys=self.account_book, chain_id=self.chain_id
        )
        self.assertFalse(ok_sig)
        self.assertEqual(reason_sig, BAD_SIGNATURE)

    def test_state_hash_independent_of_insertion_order(self) -> None:
        """state_hash phải giống hệt nhau bất kể thứ tự áp dụng các giao dịch của các tài khoản khác nhau."""
        alice = self.users["alice"]
        bob = self.users["bob"]
        carol = self.users["carol"]

        tx_a1 = alice.make_message("Alice 1", nonce=1)
        tx_a2 = alice.make_message("Alice 2", nonce=2)
        tx_b1 = bob.make_message("Bob 1", nonce=1)
        tx_c1 = carol.make_message("Carol 1", nonce=1)

        # State 1: áp dụng theo thứ tự Alice -> Bob -> Carol
        s1 = State()
        for tx in (tx_a1, tx_a2, tx_b1, tx_c1):
            ok, _ = apply_tx(s1, tx, account_pubkeys=self.account_book)
            self.assertTrue(ok)

        # State 2: áp dụng theo thứ tự Carol -> Bob -> Alice
        s2 = State()
        for tx in (tx_c1, tx_b1, tx_a1, tx_a2):
            ok, _ = apply_tx(s2, tx, account_pubkeys=self.account_book)
            self.assertTrue(ok)

        self.assertEqual(s1.state_hash(), s2.state_hash())

        # Kiểm tra thực thi khối ở chế độ thực thi thử (dry_run) không làm thay đổi state gốc
        empty_state = State()
        new_state, err = apply_block(
            empty_state,
            [tx_a1, tx_b1],
            account_pubkeys=self.account_book,
            dry_run=True,
        )
        self.assertIsNotNone(new_state)
        self.assertIsNone(err)
        self.assertEqual(len(empty_state), 0)
        assert new_state is not None
        self.assertEqual(len(new_state), 2)

    def test_nonce_zero_is_replayed_tx_and_nfc_lookup(self) -> None:
        """
        - Giao dịch có nonce=0, key='alice/chat/0' khi state đang ở applied_nonce=0 phải bị từ chối với REPLAYED_TX.
        - State.get / __getitem__ / __contains__ phải tự động chuẩn hóa key NFD về NFC.
        - trial_execute_transactions phải bỏ qua tx chưa tới lượt nonce dù kích thước lớn mà không dừng sớm.
        """
        import unicodedata
        from src.execution.executor import trial_execute_transactions

        state = State()
        alice = self.users["alice"]
        bob = self.users["bob"]

        tx_zero = alice.make_message("Nonce 0", nonce=0, key="alice/chat/0")
        ok_z, reason_z = apply_tx(state, tx_zero, account_pubkeys=self.account_book, chain_id=self.chain_id)
        self.assertFalse(ok_z)
        self.assertEqual(reason_z, REPLAYED_TX)

        # Kiểm tra tra cứu NFD trên State
        k_nfd = unicodedata.normalize("NFD", "tiếng/chat/1")
        state.set(k_nfd, "Xin chào")
        self.assertIn(k_nfd, state)
        self.assertEqual(state.get(k_nfd), "Xin chào")
        self.assertEqual(state[k_nfd], "Xin chào")

        # Kiểm tra trial_execute_transactions bỏ qua tx chưa tới lượt nonce (nonce=5) và chọn tiếp tx hợp lệ của bob
        base = State()
        tx_unready = alice.make_message("Chưa tới lượt " * 10, nonce=5)
        tx_ready = bob.make_message("Tới lượt bob", nonce=1)
        after_state, included, skipped = trial_execute_transactions(
            base,
            [tx_unready, tx_ready],
            account_pubkeys=self.account_book,
            max_block_bytes=tx_ready.byte_size() + 10,
        )
        self.assertEqual(included, [tx_ready])
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0][1], BAD_NONCE)
        self.assertEqual(after_state.get_nonce("bob"), 1)


def run_tests() -> bool:
    """Chạy toàn bộ test trong file này và trả về True nếu tất cả đều PASS."""
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestStateExecution)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    return result.wasSuccessful()


run = run_tests

if __name__ == "__main__":
    unittest.main()
