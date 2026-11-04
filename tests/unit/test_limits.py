"""
Kiểm thử đơn vị (Unit Test) cho các giới hạn kích thước và bảng mã (tests/unit/test_limits.py):
- Đếm ký tự với tiếng Việt có dấu (chuẩn hóa NFC) và biểu tượng cảm xúc (emoji).
- Giới hạn tối đa 200 ký tự mỗi tin nhắn (TX_TOO_LONG), không cho phép tin nhắn rỗng.
- Giới hạn tối đa 1024 byte cho toàn bộ giao dịch mã hóa (TX_TOO_LONG).
- Giới hạn tối đa 4096 byte cho phần thân của mỗi khối (BLOCK_TOO_LARGE) và
  hành vi dừng đúng tại giao dịch đầu tiên vượt ngưỡng 4096 byte trong TxPool.
"""

from __future__ import annotations

import unicodedata
import unittest

from src.core.block import MAX_BLOCK_BYTES, Block, make_genesis_block
from src.core.header import Header
from src.core.transaction import MAX_TEXT_CHARS, MAX_TX_BYTES, Transaction
from src.core.user import create_account_book, create_users
from src.crypto.hashing import tx_root as compute_tx_root
from src.crypto.signing import derive_validator_keybook, derive_validator_keypairs
from src.execution.executor import apply_block
from src.execution.state import State
from src.node.tx_pool import TxPool
from src.node.validation import (
    BLOCK_TOO_LARGE,
    TX_TOO_LONG,
    validate_block,
    validate_tx,
)


class TestLimits(unittest.TestCase):
    """Bộ kiểm thử cho giới hạn ký tự NFC, kích thước byte của Transaction và Block."""

    def setUp(self) -> None:
        self.seed = 42
        self.chain_id = "lab01-chain"
        self.account_pubkeys = create_account_book(self.seed)
        self.users = create_users(self.seed, chain_id=self.chain_id)
        self.validator_kps = derive_validator_keypairs(self.seed, n=10)
        self.validator_pubkeys = derive_validator_keybook(self.seed, n=10)

    def test_vietnamese_nfc_and_emoji_char_limit(self) -> None:
        """
        Chuỗi tiếng Việt có dấu ở dạng NFD (tổ hợp dấu rời) dài hơn 200 code point NFD
        nhưng sau khi chuẩn hóa NFC có đúng 200 ký tự thì phải được chấp nhận.
        Vượt quá 200 ký tự NFC hoặc rỗng phải bị từ chối với TX_TOO_LONG.
        """
        alice = self.users["alice"]
        state = State()

        # 200 ký tự 'ắ' ở dạng NFD gồm 600 code point, nhưng sau chuẩn hóa NFC đúng bằng 200 ký tự
        text_200_nfd = unicodedata.normalize("NFD", "ắ" * MAX_TEXT_CHARS)
        self.assertGreater(len(text_200_nfd), MAX_TEXT_CHARS)
        tx_200 = alice.make_message(text_200_nfd, nonce=1)
        self.assertEqual(tx_200.char_count(), MAX_TEXT_CHARS)
        self.assertEqual(tx_200, Transaction.from_bytes(tx_200.encode()))

        ok_200, reason_200 = validate_tx(tx_200, state=state, account_pubkeys=self.account_pubkeys)
        self.assertTrue(ok_200)
        self.assertIsNone(reason_200)

        # 201 ký tự NFC (bao gồm cả emoji và tiếng Việt) -> từ chối TX_TOO_LONG
        text_201 = "Chào 🚀 " + ("ệ" * 194)  # 7 + 194 = 201 code point NFC
        self.assertEqual(len(unicodedata.normalize("NFC", text_201)), 201)
        tx_201 = alice.make_message(text_201, nonce=1)
        ok_201, reason_201 = validate_tx(tx_201, state=state, account_pubkeys=self.account_pubkeys)
        self.assertFalse(ok_201)
        self.assertEqual(reason_201, TX_TOO_LONG)

        # Tin nhắn rỗng -> từ chối TX_TOO_LONG
        tx_empty = alice.make_message("", nonce=1)
        ok_empty, reason_empty = validate_tx(tx_empty, state=state, account_pubkeys=self.account_pubkeys)
        self.assertFalse(ok_empty)
        self.assertEqual(reason_empty, TX_TOO_LONG)

    def test_tx_byte_size_limit_1024(self) -> None:
        """Giao dịch có tổng kích thước mã hóa vượt quá 1024 byte phải bị từ chối với TX_TOO_LONG."""
        alice = self.users["alice"]
        state = State()

        tx = alice.make_message("Tin nhắn thử giới hạn byte", nonce=1)
        self.assertLessEqual(tx.byte_size(), MAX_TX_BYTES)

        # Kiểm tra với ngưỡng max_tx_bytes nhỏ hơn kích thước thật của tx
        ok, reason = validate_tx(
            tx,
            state=state,
            account_pubkeys=self.account_pubkeys,
            max_tx_bytes=tx.byte_size() - 1,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, TX_TOO_LONG)

    def test_block_body_size_limit_4096_and_pool_selection(self) -> None:
        """
        - TxPool.select_for_block phải dừng ngay tại giao dịch đầu tiên vượt ngưỡng 4096 byte,
          và giữ nguyên các giao dịch còn lại trong pool cho khối sau.
        - Block có tổng kích thước mã hóa của các tx > 4096 byte phải bị từ chối với BLOCK_TOO_LARGE.
        """
        state = State()
        pool = TxPool(account_pubkeys=self.account_pubkeys)
        alice = self.users["alice"]

        # Tạo 30 giao dịch liên tiếp của alice, mỗi giao dịch dài ~200 ký tự UTF-8 (~450-550 byte)
        all_txs: list[Transaction] = []
        for i in range(1, 31):
            msg_text = f"Tin nhắn số {i:02d}: " + ("việt " * 35)
            tx = alice.make_message(msg_text[:195], nonce=i)
            ok, reason = pool.add(tx, state=state)
            self.assertTrue(ok, f"Lỗi khi thêm tx thứ {i}: {reason}")
            all_txs.append(tx)

        # Tổng kích thước của 30 tx chắc chắn vượt xa 4096 byte
        total_all_bytes = sum(t.byte_size() for t in all_txs)
        self.assertGreater(total_all_bytes, MAX_BLOCK_BYTES)

        # Chọn các giao dịch vừa cho Block 1 (<= 4096 byte)
        selected_batch = pool.select_for_block(state, max_block_bytes=MAX_BLOCK_BYTES)
        self.assertGreater(len(selected_batch), 0)
        self.assertLess(len(selected_batch), len(all_txs))
        batch_bytes = sum(t.byte_size() for t in selected_batch)
        self.assertLessEqual(batch_bytes, MAX_BLOCK_BYTES)

        # Giao dịch kế tiếp ngay sau batch phải làm tổng vượt quá 4096 byte
        next_tx = all_txs[len(selected_batch)]
        self.assertGreater(batch_bytes + next_tx.byte_size(), MAX_BLOCK_BYTES)

        # Giờ cố tình dựng một Block nhét toàn bộ 30 tx (> 4096 byte) -> phải bị từ chối BLOCK_TOO_LARGE
        genesis = make_genesis_block(self.chain_id)
        temp_state = state.clone()
        for t in all_txs:
            temp_state.set(t.key, t.value, account=t.account, nonce=t.nonce)

        oversized_header = Header(
            chain_id=self.chain_id,
            height=1,
            parent_hash=str(genesis.block_hash()),
            tx_root=str(compute_tx_root(all_txs)),
            state_hash=str(temp_state.state_hash()),
            proposer_id="N1",
            timestamp=1000,
        )
        oversized_header.sign(self.validator_kps["N1"][0])
        oversized_block = Block(header=oversized_header, transactions=all_txs)

        ok_blk, blk_reason = validate_block(
            block=oversized_block,
            parent_block_or_header=genesis,
            parent_state=state,
            validator_pubkeys=self.validator_pubkeys,
            account_pubkeys=self.account_pubkeys,
            expected_round=0,
        )
        self.assertFalse(ok_blk)
        self.assertEqual(blk_reason, BLOCK_TOO_LARGE)

        # Cũng kiểm tra apply_block từ chối BLOCK_TOO_LARGE
        res_state, exec_reason = apply_block(
            state,
            oversized_block,
            account_pubkeys=self.account_pubkeys,
        )
        self.assertIsNone(res_state)
        self.assertEqual(exec_reason, BLOCK_TOO_LARGE)


def run_tests() -> bool:
    """Chạy toàn bộ test trong file này và trả về True nếu tất cả đều PASS."""
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestLimits)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    return result.wasSuccessful()


run = run_tests

if __name__ == "__main__":
    unittest.main()
