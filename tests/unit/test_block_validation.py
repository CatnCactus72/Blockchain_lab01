"""
Kiểm thử đơn vị (Unit Test) cho bộ kiểm tra khối, đề xuất, sổ cái và đồng bộ (src/node/validation.py, ledger.py, sync.py):
- Từng lý do từ chối block:
  * Khối cha sai (BAD_PARENT)
  * tx_root sai (BAD_TX_ROOT)
  * state_hash sai (BAD_STATE_HASH)
  * Proposer sai (NOT_PROPOSER)
  * Timestamp không lớn hơn khối cha (BAD_TIMESTAMP)
  * Chữ ký sai / sai domain / sai chain_id (BAD_SIGNATURE, WRONG_DOMAIN, WRONG_CHAIN)
- Kiểm tra Proposal, CommitCertificate, Ledger, SyncManager và ChatQuery.
"""

from __future__ import annotations

import copy
import unittest

from src.core.block import Block, make_genesis_block
from src.core.header import Header
from src.core.proposal import Proposal, expected_proposer_id
from src.core.transaction import Transaction
from src.core.user import create_account_book, create_users
from src.core.vote import PRECOMMIT, CommitCertificate, Vote
from src.crypto.domain import VOTE
from src.crypto.hashing import tx_root as compute_tx_root
from src.crypto.signing import derive_validator_keybook, derive_validator_keypairs, sign
from src.execution.executor import apply_block
from src.execution.state import State
from src.node.ledger import Ledger
from src.node.proposer import (
    ProposerSelector,
    get_proposer,
    is_proposer,
    normalize_validator_id,
    proposer_index,
)
from src.node.query import ChatQuery
from src.node.sync import SyncManager
from src.node.tx_pool import TxPool
from src.node.validation import (
    BAD_PARENT,
    BAD_SIGNATURE,
    BAD_STATE_HASH,
    BAD_TIMESTAMP,
    BAD_TX_ROOT,
    CONFLICTING_VOTE,
    FUTURE_HEIGHT,
    NOT_PROPOSER,
    WRONG_CHAIN,
    WRONG_DOMAIN,
    validate_block,
    validate_commit_certificate,
    validate_proposal,
)


class TestBlockValidation(unittest.TestCase):
    """Bộ kiểm thử cho các quy tắc kiểm tra hợp lệ của Block, Header, Proposal và Ledger."""

    def setUp(self) -> None:
        self.seed = 42
        self.chain_id = "lab01-chain"
        self.validator_kps = derive_validator_keypairs(self.seed, n=10)
        self.validator_pubkeys = derive_validator_keybook(self.seed, n=10)
        self.account_pubkeys = create_account_book(self.seed)
        self.users = create_users(self.seed, chain_id=self.chain_id)
        self.genesis = make_genesis_block(self.chain_id)
        self.base_state = State()

    def _build_valid_block_1(self) -> tuple[Block, State]:
        """Dựng một khối hợp lệ ở height=1, round=0 (proposer hợp lệ là N1)."""
        tx1 = self.users["alice"].make_message("Tin nhắn hợp lệ 1", nonce=1)
        tx2 = self.users["bob"].make_message("Tin nhắn hợp lệ 2", nonce=1)
        txs = [tx1, tx2]

        new_state, err = apply_block(
            self.base_state,
            txs,
            account_pubkeys=self.account_pubkeys,
            dry_run=True,
            verify_commitments=False,
        )
        self.assertIsNotNone(new_state)
        self.assertIsNone(err)
        assert new_state is not None

        proposer_id = expected_proposer_id(height=1, round_num=0, n=10)  # "N1"
        header = Header(
            chain_id=self.chain_id,
            height=1,
            parent_hash=str(self.genesis.block_hash()),
            tx_root=str(compute_tx_root(txs)),
            state_hash=str(new_state.state_hash()),
            proposer_id=proposer_id,
            timestamp=1000,
        )
        header.sign(self.validator_kps[proposer_id][0])
        return Block(header=header, transactions=txs), new_state

    def _make_certificate(self, height: int, round_num: int, block_hash: str, count: int = 7) -> CommitCertificate:
        """Tạo chứng nhận CommitCertificate gồm `count` phiếu PRECOMMIT hợp lệ."""
        votes: list[Vote] = []
        for i in range(count):
            vid = f"N{i}"
            v = Vote(
                height=height,
                round=round_num,
                phase=PRECOMMIT,
                block_hash=block_hash,
                validator_id=vid,
            )
            v.sign(self.validator_kps[vid][0], chain_id=self.chain_id)
            votes.append(v)
        return CommitCertificate(height=height, block_hash=block_hash, votes=votes, round=round_num)

    def test_valid_block_passes(self) -> None:
        """Khối hợp lệ phải vượt qua validate_block với (True, None)."""
        blk, _ = self._build_valid_block_1()
        ok, reason = validate_block(
            block=blk,
            parent_block_or_header=self.genesis,
            parent_state=self.base_state,
            validator_pubkeys=self.validator_pubkeys,
            account_pubkeys=self.account_pubkeys,
            chain_id=self.chain_id,
            expected_round=0,
        )
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_reject_bad_parent(self) -> None:
        """Từ chối block có parent_hash sai hoặc height không nối tiếp khối cha (BAD_PARENT)."""
        blk, _ = self._build_valid_block_1()
        blk.header.parent_hash = "ff" * 32
        blk.header.sign(self.validator_kps[blk.proposer_id][0])

        ok, reason = validate_block(
            block=blk,
            parent_block_or_header=self.genesis,
            parent_state=self.base_state,
            validator_pubkeys=self.validator_pubkeys,
            account_pubkeys=self.account_pubkeys,
            expected_round=0,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, BAD_PARENT)

        # Sai height (height=2 khi cha là height=0)
        blk2, _ = self._build_valid_block_1()
        blk2.header.height = 2
        blk2.header.sign(self.validator_kps[blk2.proposer_id][0])
        ok2, reason2 = validate_block(
            block=blk2,
            parent_block_or_header=self.genesis,
            parent_state=self.base_state,
            validator_pubkeys=self.validator_pubkeys,
            account_pubkeys=self.account_pubkeys,
        )
        self.assertFalse(ok2)
        self.assertEqual(reason2, BAD_PARENT)

    def test_reject_bad_tx_root(self) -> None:
        """Từ chối block có tx_root trong Header không khớp với danh sách giao dịch trong Body (BAD_TX_ROOT)."""
        blk, _ = self._build_valid_block_1()
        blk.header.tx_root = "11" * 32
        blk.header.sign(self.validator_kps[blk.proposer_id][0])

        ok, reason = validate_block(
            block=blk,
            parent_block_or_header=self.genesis,
            parent_state=self.base_state,
            validator_pubkeys=self.validator_pubkeys,
            account_pubkeys=self.account_pubkeys,
            expected_round=0,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, BAD_TX_ROOT)

    def test_reject_bad_state_hash(self) -> None:
        """Từ chối block có state_hash sai lệch với kết quả thực thi thực tế của Body (BAD_STATE_HASH)."""
        blk, _ = self._build_valid_block_1()
        blk.header.state_hash = "22" * 32
        blk.header.sign(self.validator_kps[blk.proposer_id][0])

        ok, reason = validate_block(
            block=blk,
            parent_block_or_header=self.genesis,
            parent_state=self.base_state,
            validator_pubkeys=self.validator_pubkeys,
            account_pubkeys=self.account_pubkeys,
            expected_round=0,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, BAD_STATE_HASH)

    def test_reject_not_proposer(self) -> None:
        """Từ chối block do node không phải proposer của (height, round) tạo ra (NOT_PROPOSER)."""
        blk, _ = self._build_valid_block_1()
        # Ở height=1, round=0, proposer đúng là N1; giả sử N3 tự tạo block
        blk.header.proposer_id = "N3"
        blk.header.sign(self.validator_kps["N3"][0])

        ok, reason = validate_block(
            block=blk,
            parent_block_or_header=self.genesis,
            parent_state=self.base_state,
            validator_pubkeys=self.validator_pubkeys,
            account_pubkeys=self.account_pubkeys,
            expected_round=0,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, NOT_PROPOSER)

    def test_reject_bad_timestamp(self) -> None:
        """Từ chối block có timestamp <= timestamp của khối cha (BAD_TIMESTAMP)."""
        blk, _ = self._build_valid_block_1()
        # Genesis có timestamp = 0, nên đặt timestamp = 0 là không lớn hơn cha
        blk.header.timestamp = 0
        blk.header.sign(self.validator_kps[blk.proposer_id][0])

        ok, reason = validate_block(
            block=blk,
            parent_block_or_header=self.genesis,
            parent_state=self.base_state,
            validator_pubkeys=self.validator_pubkeys,
            account_pubkeys=self.account_pubkeys,
            expected_round=0,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, BAD_TIMESTAMP)

    def test_reject_bad_signature_wrong_domain_wrong_chain(self) -> None:
        """Từ chối block ký bằng khóa sai (BAD_SIGNATURE), sai domain (WRONG_DOMAIN) hoặc sai chain_id (WRONG_CHAIN)."""
        # 1. Ký bằng khóa của validator khác (N2 ký cho header của N1) -> BAD_SIGNATURE
        blk1, _ = self._build_valid_block_1()
        blk1.header.sign(self.validator_kps["N2"][0])
        ok1, reason1 = validate_block(
            block=blk1,
            parent_block_or_header=self.genesis,
            parent_state=self.base_state,
            validator_pubkeys=self.validator_pubkeys,
            account_pubkeys=self.account_pubkeys,
            expected_round=0,
        )
        self.assertFalse(ok1)
        self.assertEqual(reason1, BAD_SIGNATURE)

        # 2. Ký đúng khóa N1 nhưng dùng domain VOTE thay vì HEADER -> WRONG_DOMAIN
        blk2, _ = self._build_valid_block_1()
        blk2.header.signature = sign(
            self.validator_kps["N1"][0],
            VOTE,
            self.chain_id,
            blk2.header.signing_fields(),
        )
        ok2, reason2 = validate_block(
            block=blk2,
            parent_block_or_header=self.genesis,
            parent_state=self.base_state,
            validator_pubkeys=self.validator_pubkeys,
            account_pubkeys=self.account_pubkeys,
            expected_round=0,
        )
        self.assertFalse(ok2)
        self.assertEqual(reason2, WRONG_DOMAIN)

        # 3. Sai chain_id -> WRONG_CHAIN
        blk3, _ = self._build_valid_block_1()
        blk3.header.chain_id = "wrong-chain"
        blk3.header.sign(self.validator_kps["N1"][0])
        ok3, reason3 = validate_block(
            block=blk3,
            parent_block_or_header=self.genesis,
            parent_state=self.base_state,
            validator_pubkeys=self.validator_pubkeys,
            account_pubkeys=self.account_pubkeys,
            chain_id=self.chain_id,
            expected_round=0,
        )
        self.assertFalse(ok3)
        self.assertEqual(reason3, WRONG_CHAIN)

    def test_proposal_and_reproposal_validation(self) -> None:
        """Kiểm tra Proposal cho cả khối mới (pol_round=-1) và đề xuất lại khối đã khóa (pol_round>=0)."""
        blk, _ = self._build_valid_block_1()
        # Đề xuất khối mới ở height=1, round=0 bởi N1
        prop0 = Proposal(
            height=1,
            round=0,
            block_hash=str(blk.block_hash()),
            pol_round=-1,
            header=blk.header,
            proposer_id="N1",
        )
        prop0.sign(self.validator_kps["N1"][0])
        ok0, r0 = validate_proposal(
            proposal=prop0,
            parent_header_or_block=self.genesis,
            validator_pubkeys=self.validator_pubkeys,
            current_height=1,
        )
        self.assertTrue(ok0)
        self.assertIsNone(r0)

        # Đề xuất lại cùng block đó ở height=1, round=1 bởi N2 với pol_round=0
        # (header vẫn do N1 ký, nhưng proposal_sig do N2 ký)
        prop1 = Proposal(
            height=1,
            round=1,
            block_hash=str(blk.block_hash()),
            pol_round=0,
            header=copy.deepcopy(blk.header),
            proposer_id="N2",
        )
        prop1.sign(self.validator_kps["N2"][0])
        ok1, r1 = validate_proposal(
            proposal=prop1,
            parent_header_or_block=self.genesis,
            validator_pubkeys=self.validator_pubkeys,
            current_height=1,
        )
        self.assertTrue(ok1)
        self.assertIsNone(r1)

        # Chấp nhận Proposal hợp lệ của N2 kể cả khi được chuyển tiếp qua hop trung gian (sender_id="N4")
        ok_gossip, r_gossip = validate_proposal(
            proposal=prop1,
            parent_header_or_block=self.genesis,
            validator_pubkeys=self.validator_pubkeys,
            sender_id="N4",
            current_height=1,
        )
        self.assertTrue(ok_gossip)
        self.assertIsNone(r_gossip)

        # Chiều cao vượt quá cửa sổ tương lai (current_height=1, window=5, proposal.height=7)
        prop_future = copy.deepcopy(prop0)
        prop_future.height = 7
        ok_fut, r_fut = validate_proposal(
            proposal=prop_future,
            parent_header_or_block=None,
            validator_pubkeys=self.validator_pubkeys,
            current_height=1,
            future_height_window=5,
        )
        self.assertFalse(ok_fut)
        self.assertEqual(r_fut, FUTURE_HEIGHT)

    def test_ledger_sync_and_query(self) -> None:
        """Kiểm tra tích hợp Ledger (kèm CommitCertificate), SyncManager và ChatQuery."""
        blk1, _ = self._build_valid_block_1()
        cert_valid = self._make_certificate(1, 0, str(blk1.block_hash()), count=7)
        cert_insufficient = self._make_certificate(1, 0, str(blk1.block_hash()), count=6)

        ledger1 = Ledger(chain_id=self.chain_id, validator_pubkeys=self.validator_pubkeys)
        # Chứng nhận chỉ có 6 phiếu (< 7) phải bị từ chối
        ok_bad_cert, reason_bad_cert = ledger1.append(blk1, cert_insufficient)
        self.assertFalse(ok_bad_cert)
        self.assertEqual(reason_bad_cert, BAD_SIGNATURE)
        self.assertEqual(ledger1.latest_height, 0)

        # Chứng nhận đủ 7 phiếu hợp lệ được thêm vào Ledger
        ok_good, reason_good = ledger1.append(blk1, cert_valid)
        self.assertTrue(ok_good)
        self.assertIsNone(reason_good)
        self.assertEqual(ledger1.latest_height, 1)

        # Node 2 đang ở height 0 đồng bộ khối từ Node 1 qua SyncManager
        ledger2 = Ledger(chain_id=self.chain_id, validator_pubkeys=self.validator_pubkeys)
        state2 = State()
        pool2 = TxPool(account_pubkeys=self.account_pubkeys)
        for tx in blk1.transactions:
            pool2.add(tx, state=state2)
        self.assertEqual(len(pool2), 2)

        sync1 = SyncManager("N1", ledger1, State(), validator_pubkeys=self.validator_pubkeys, account_pubkeys=self.account_pubkeys)
        sync2 = SyncManager("N2", ledger2, state2, tx_pool=pool2, validator_pubkeys=self.validator_pubkeys)

        status_msg = sync1.build_status_message()
        get_blocks_msg = sync2.handle_status("N1", status_msg.payload)
        self.assertIsNotNone(get_blocks_msg)
        assert get_blocks_msg is not None

        blocks_msg = sync1.handle_get_blocks("N2", get_blocks_msg.payload)
        self.assertIsNotNone(blocks_msg)
        assert blocks_msg is not None

        ok_sync, sync_reason, synced_blocks = sync2.handle_blocks("N1", blocks_msg.payload)
        self.assertTrue(ok_sync)
        self.assertIsNone(sync_reason)
        self.assertEqual(len(synced_blocks), 1)
        self.assertEqual(ledger2.latest_height, 1)
        self.assertEqual(len(pool2), 0)  # Các tx đã finalize phải được xóa khỏi pool2

        # Kiểm tra giao diện đọc ChatQuery và công cụ show_chat / show_state
        from tests.tools.show_chat import parse_log_line
        from tests.tools.show_state import format_state_output

        query2 = ChatQuery(ledger2)
        latest_blocks = query2.get_latest(1)
        self.assertEqual(len(latest_blocks), 1)
        self.assertEqual(latest_blocks[0].height, 1)
        self.assertIsNone(query2.get_block(99))
        msgs = query2.get_chat_messages()
        self.assertEqual(len(msgs), 2)

        # Kiểm tra show_state giữ đúng state_hash toàn cục khi lọc theo account dù ChatQuery khởi tạo state=None
        state_out_alice = format_state_output(query2, node_id="N2", account="alice")
        self.assertIn(str(state2.state_hash())[:12], state_out_alice)

        # Kiểm tra parse_log_line giữ nguyên chuỗi có khoảng trắng không bọc ngoặc kép trong details
        parsed_line = parse_log_line(
            "00:01:250 seq=00010 node=N2 ev=TX_APPLIED h=1 details=alice/chat/1=Xin chào mọi người reason=NONE"
        )
        self.assertIsNotNone(parsed_line)
        assert parsed_line is not None
        self.assertEqual(parsed_line["details"], "alice/chat/1=Xin chào mọi người")
        self.assertEqual(parsed_line["reason"], "NONE")

    def test_commit_certificate_conflicting_vote_and_round_check(self) -> None:
        """
        Kiểm tra CommitCertificate.verify:
        1. Cùng một validator gửi 2 phiếu khác block_hash hoặc khác round trong cùng certificate
           -> phải trả về CONFLICTING_VOTE thay vì BAD_SIGNATURE.
        2. Nếu self.round được truyền (kể cả round=2 hoặc round=0 tường minh) thì mọi phiếu trong
           certificate phải có vote.round == self.round.
        """
        blk1, _ = self._build_valid_block_1()
        bh1 = str(blk1.block_hash())
        other_bh = "aa" * 32

        # 1a. N0 gửi 2 phiếu khác block_hash trong cùng certificate (đặt phiếu khác block_hash ở cuối hoặc đầu)
        cert_conflict_hash = self._make_certificate(1, 0, bh1, count=7)
        conflicting_vote_hash = Vote(
            height=1,
            round=0,
            phase=PRECOMMIT,
            block_hash=other_bh,
            validator_id="N0",
        )
        conflicting_vote_hash.sign(self.validator_kps["N0"][0], chain_id=self.chain_id)
        cert_conflict_hash.votes.append(conflicting_vote_hash)

        ok_ch, reason_ch = validate_commit_certificate(
            cert_conflict_hash,
            validator_pubkeys=self.validator_pubkeys,
            chain_id=self.chain_id,
        )
        self.assertFalse(ok_ch)
        self.assertEqual(reason_ch, CONFLICTING_VOTE)

        # Đặt phiếu khác block_hash của N0 lên đầu danh sách votes
        cert_conflict_hash_first = CommitCertificate(
            height=1,
            block_hash=bh1,
            votes=[conflicting_vote_hash] + self._make_certificate(1, 0, bh1, count=7).votes,
            round=0,
        )
        ok_ch_first, reason_ch_first = cert_conflict_hash_first.verify(
            validator_pubkeys=self.validator_pubkeys,
            chain_id=self.chain_id,
        )
        self.assertFalse(ok_ch_first)
        self.assertEqual(reason_ch_first, CONFLICTING_VOTE)

        # 1b. N0 gửi 2 phiếu khác round trong cùng certificate
        cert_conflict_round = self._make_certificate(1, 0, bh1, count=7)
        conflicting_vote_round = Vote(
            height=1,
            round=1,
            phase=PRECOMMIT,
            block_hash=bh1,
            validator_id="N0",
        )
        conflicting_vote_round.sign(self.validator_kps["N0"][0], chain_id=self.chain_id)
        cert_conflict_round.votes.append(conflicting_vote_round)

        ok_cr, reason_cr = cert_conflict_round.verify(
            validator_pubkeys=self.validator_pubkeys,
            chain_id=self.chain_id,
        )
        self.assertFalse(ok_cr)
        self.assertEqual(reason_cr, CONFLICTING_VOTE)

        # 2a. self.round được truyền khác 0 (round=2) nhưng các vote bên trong có round=1 -> BAD_SIGNATURE
        cert_round_mismatch = self._make_certificate(1, 1, bh1, count=7)
        cert_round_mismatch.round = 2
        ok_rm, reason_rm = cert_round_mismatch.verify(
            validator_pubkeys=self.validator_pubkeys,
            chain_id=self.chain_id,
        )
        self.assertFalse(ok_rm)
        self.assertEqual(reason_rm, BAD_SIGNATURE)

        # 2b. self.round được truyền tường minh bằng 0 (round=0) nhưng các vote bên trong có round=1 -> BAD_SIGNATURE
        votes_r1 = self._make_certificate(1, 1, bh1, count=7).votes
        cert_explicit_r0 = CommitCertificate(height=1, block_hash=bh1, votes=votes_r1, round=0)
        self.assertEqual(cert_explicit_r0.round, 0)
        ok_r0_mismatch, reason_r0_mismatch = cert_explicit_r0.verify(
            validator_pubkeys=self.validator_pubkeys,
            chain_id=self.chain_id,
        )
        self.assertFalse(ok_r0_mismatch)
        self.assertEqual(reason_r0_mismatch, BAD_SIGNATURE)

        # 2c. Khi không truyền round (round=None), tự động suy ra round=2 từ votes và hợp lệ
        votes_r2 = self._make_certificate(1, 2, bh1, count=7).votes
        cert_inferred_r2 = CommitCertificate(height=1, block_hash=bh1, votes=votes_r2)
        self.assertEqual(cert_inferred_r2.round, 2)
        ok_r2, reason_r2 = cert_inferred_r2.verify(
            validator_pubkeys=self.validator_pubkeys,
            chain_id=self.chain_id,
        )
        self.assertTrue(ok_r2)
        self.assertIsNone(reason_r2)

    def test_proposal_bad_sig_via_relay_vs_not_proposer(self) -> None:
        """
        Kiểm tra Proposal.verify_proposer_and_sig & validate_proposal:
        1. Nếu proposer đúng (proposer_id == exp_proposer) gửi một proposal bị hỏng chữ ký
           nhưng đi qua hop trung gian (sender_id != exp_proposer) -> phải trả về BAD_SIGNATURE
           chứ không trả về nhầm NOT_PROPOSER.
        2. Nếu một node khác (sender_id != exp_proposer) thực sự ký proposal_sig bằng khóa
           của chính sender_id (hoặc proposer_id != exp_proposer) -> phải trả về NOT_PROPOSER.
        3. Khi đề xuất lại (pol_round=0, proposer_id="") được chuyển tiếp qua hop trung gian
           với validator_pubkeys=None -> vẫn hợp lệ (True, None).
        4. Khi chữ ký proposal_sig bị ký sai domain (WRONG_DOMAIN) kèm pol_round sai -> ưu tiên trả về WRONG_DOMAIN.
        5. Khi timestamp trong Header bị sửa sau khi ký (không ký lại) -> ưu tiên trả về BAD_SIGNATURE.
        """
        blk, _ = self._build_valid_block_1()
        # Ở height=1, round=0, exp_proposer là N1. N1 tạo proposal nhưng chữ ký bị hỏng
        prop_corrupted = Proposal(
            height=1,
            round=0,
            block_hash=str(blk.block_hash()),
            pol_round=-1,
            header=blk.header,
            proposer_id="N1",
        )
        prop_corrupted.sign(self.validator_kps["N1"][0])
        # Làm hỏng 1 byte trong proposal_sig
        corrupted_sig = bytearray(prop_corrupted.proposal_sig)
        corrupted_sig[0] ^= 0xFF
        prop_corrupted.proposal_sig = bytes(corrupted_sig)

        # Nhận qua hop trung gian sender_id="N4" -> vẫn phải báo BAD_SIGNATURE
        ok_relay, reason_relay = validate_proposal(
            proposal=prop_corrupted,
            parent_header_or_block=self.genesis,
            validator_pubkeys=self.validator_pubkeys,
            sender_id="N4",
            current_height=1,
        )
        self.assertFalse(ok_relay)
        self.assertEqual(reason_relay, BAD_SIGNATURE)

        # Trường hợp đề xuất lại (pol_round=0) ở height=1, round=1 (exp_proposer là N2),
        # nhưng N5 tự ký proposal_sig bằng khóa của N5 và gửi (proposer_id để trống)
        prop_impostor = Proposal(
            height=1,
            round=1,
            block_hash=str(blk.block_hash()),
            pol_round=0,
            header=copy.deepcopy(blk.header),
            proposer_id="",
        )
        prop_impostor.sign(self.validator_kps["N5"][0])
        for sid in ("N5", "n5", 5):
            ok_imp, reason_imp = validate_proposal(
                proposal=prop_impostor,
                parent_header_or_block=self.genesis,
                validator_pubkeys=self.validator_pubkeys,
                sender_id=sid,
                current_height=1,
            )
            self.assertFalse(ok_imp)
            self.assertEqual(reason_imp, NOT_PROPOSER)

        # Đề xuất lại hợp lệ của N2 (pol_round=0, proposer_id="") đi qua hop N4 khi validator_pubkeys=None
        prop_repropose_valid = Proposal(
            height=1,
            round=1,
            block_hash=str(blk.block_hash()),
            pol_round=0,
            header=copy.deepcopy(blk.header),
            proposer_id="",
        )
        prop_repropose_valid.sign(self.validator_kps["N2"][0])
        ok_no_pk, reason_no_pk = validate_proposal(
            proposal=prop_repropose_valid,
            parent_header_or_block=self.genesis,
            validator_pubkeys=None,
            sender_id="N4",
            current_height=1,
        )
        self.assertTrue(ok_no_pk)
        self.assertIsNone(reason_no_pk)

        # Proposal ký sai domain (VOTE thay vì PROPOSAL) kèm pol_round=5 ở round=0 -> WRONG_DOMAIN
        prop_wrong_dom = Proposal(
            height=1,
            round=0,
            block_hash=str(blk.block_hash()),
            pol_round=5,
            header=copy.deepcopy(blk.header),
            proposer_id="N1",
        )
        prop_wrong_dom.proposal_sig = sign(
            self.validator_kps["N1"][0],
            VOTE,
            self.chain_id,
            prop_wrong_dom.signing_fields(),
        )
        ok_wd, reason_wd = validate_proposal(
            proposal=prop_wrong_dom,
            parent_header_or_block=self.genesis,
            validator_pubkeys=self.validator_pubkeys,
            current_height=1,
        )
        self.assertFalse(ok_wd)
        self.assertEqual(reason_wd, WRONG_DOMAIN)

        # Header bị sửa timestamp=0 sau khi đã ký (không ký lại) -> BAD_SIGNATURE
        blk_tampered_ts, _ = self._build_valid_block_1()
        blk_tampered_ts.header.timestamp = 0
        ok_tts, reason_tts = validate_block(
            block=blk_tampered_ts,
            parent_block_or_header=self.genesis,
            parent_state=self.base_state,
            validator_pubkeys=self.validator_pubkeys,
            account_pubkeys=self.account_pubkeys,
            expected_round=0,
        )
        self.assertFalse(ok_tts)
        self.assertEqual(reason_tts, BAD_SIGNATURE)

    def test_proposer_selection_module(self) -> None:
        """Kiểm tra đầy đủ các hàm và lớp trong src/node/proposer.py."""
        # Công thức (height + round) mod 10
        self.assertEqual(proposer_index(1, 0, n=10), 1)
        self.assertEqual(proposer_index(height=1, round=9, n=10), 0)
        self.assertEqual(get_proposer(1, 0, n=10), "N1")
        self.assertEqual(get_proposer(height=5, round=7, n=10), "N2")

        # Kiểm tra is_proposer với nhiều cách truyền đối số
        self.assertTrue(is_proposer("N1", 1, 0, n=10))
        self.assertTrue(is_proposer(1, 1, 0, n=10))
        self.assertTrue(is_proposer(1, 0, "N1", n=10))
        self.assertFalse(is_proposer("N2", 1, 0, n=10))
        self.assertEqual(normalize_validator_id(3), "N3")
        self.assertEqual(normalize_validator_id("n07"), "N7")

        # Kiểm tra truyền danh sách validators ở vị trí tham số n hoặc từ khóa validators
        std_vals = [f"N{i}" for i in range(10)]
        self.assertEqual(proposer_index(1, 0, std_vals), 1)
        self.assertEqual(get_proposer(1, 0, std_vals), "N1")
        self.assertTrue(is_proposer(1, 1, 0, validators=std_vals))
        self.assertTrue(is_proposer("n1", 1, 0, std_vals))

        # Kiểm tra ProposerSelector với danh sách validator tùy chỉnh
        selector = ProposerSelector(validators=["V0", "V1", "V2", "V3"])
        self.assertEqual(selector.n, 4)
        self.assertEqual(selector.get_proposer(2, 3), "V1")
        self.assertTrue(selector.is_proposer("V1", 2, 3))
        self.assertFalse(selector.is_proposer("V0", 2, 3))

        selector_pos = ProposerSelector(["V0", "V1", "V2", "V3"])
        self.assertEqual(selector_pos.n, 4)
        self.assertEqual(selector_pos.get_proposer(2, 3), "V1")

        # Kiểm tra bắt lỗi đầu vào không hợp lệ (bao gồm cả bool)
        with self.assertRaises(ValueError):
            proposer_index(1, 0, n=0)
        with self.assertRaises(ValueError):
            proposer_index(-1, 0, n=10)
        with self.assertRaises(TypeError):
            normalize_validator_id(True)
        with self.assertRaises(TypeError):
            proposer_index(True, 0, n=10)


def run_tests() -> bool:
    """Chạy toàn bộ test trong file này và trả về True nếu tất cả đều PASS."""
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestBlockValidation)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    return result.wasSuccessful()


run = run_tests

if __name__ == "__main__":
    unittest.main()
