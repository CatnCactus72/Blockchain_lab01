"""
Kiểm thử đơn vị cho src/node/vote_counter.py (Mục 12 README):
- Vote trùng (cùng nội dung đến lần nữa) không được đếm hai lần.
- Vote mâu thuẫn (cùng validator, khác nội dung) bị từ chối và lưu bằng chứng.
- Đủ 7 phiếu mới đạt quorum; 6 phiếu không đủ.
- Đếm cho NIL và cho "bất kỳ" (count_any) đúng.
"""

from __future__ import annotations

import unittest

from src.core.vote import PRECOMMIT, PREVOTE
from src.node.vote_counter import ADDED, CONFLICT, DUPLICATE, VoteCounter

BLOCK = "a" * 64
BLOCK_B = "b" * 64


def make_vote(validator: str, height: int = 5, round_num: int = 0,
              phase: str = PREVOTE, block_hash: str | None = BLOCK):
    from src.core.vote import Vote

    # VoteCounter không kiểm chứng chữ ký; định danh phiếu là (validator, height, round, phase).
    return Vote(height, round_num, phase, block_hash, validator, signature=bytes(64))


class TestVoteCounterBasics(unittest.TestCase):
    def setUp(self) -> None:
        self.counter = VoteCounter(quorum=7, f_plus_one=4)

    def test_add_counts_each_validator_once(self) -> None:
        result = self.counter.add(make_vote("N0"))
        self.assertTrue(result.added)
        result = self.counter.add(make_vote("N1"))
        self.assertTrue(result.added)
        self.assertEqual(self.counter.count_for(5, 0, PREVOTE, BLOCK), 2)

    def test_duplicate_vote_not_counted_twice(self) -> None:
        self.counter.add(make_vote("N2"))
        duplicate = self.counter.add(make_vote("N2"))
        self.assertTrue(duplicate.is_duplicate)
        self.assertEqual(duplicate.reason, "DUPLICATE_VOTE")
        self.assertEqual(self.counter.count_for(5, 0, PREVOTE, BLOCK), 1)
        # Vote trùng chiếm slot cũ, không mở đếm mới.
        self.assertEqual(self.counter.count_any(5, 0, PREVOTE), 1)

    def test_conflicting_vote_rejected_with_evidence(self) -> None:
        self.counter.add(make_vote("N2"))
        conflicting = self.counter.add(make_vote("N2", block_hash=BLOCK_B))
        self.assertTrue(conflicting.is_conflict)
        self.assertEqual(conflicting.reason, "CONFLICTING_VOTE")
        self.assertEqual(self.counter.count_any(5, 0, PREVOTE), 1)
        self.assertEqual(self.counter.conflicting_validators(), ["N2"])
        self.assertEqual(len(self.counter.evidence), 1)
        # Phiếu mâu thuẫn không được tính cho cả hai block.
        self.assertEqual(self.counter.count_for(5, 0, PREVOTE, BLOCK_B), 0)

    def test_quorum_at_exactly_seven(self) -> None:
        for index in range(6):
            self.counter.add(make_vote(f"N{index}"))
        self.assertFalse(self.counter.has_quorum_for(5, 0, PREVOTE, BLOCK))
        self.assertIsNone(self.counter.quorum_block(5, 0, PREVOTE))
        self.counter.add(make_vote("N6"))
        self.assertTrue(self.counter.has_quorum_for(5, 0, PREVOTE, BLOCK))
        self.assertEqual(self.counter.quorum_block(5, 0, PREVOTE), BLOCK)

    def test_nil_votes_counted_separately(self) -> None:
        for index in range(7):
            self.counter.add(make_vote(f"N{index}", block_hash=None))
        self.assertEqual(self.counter.count_nil(5, 0, PREVOTE), 7)
        self.assertTrue(self.counter.has_quorum_nil(5, 0, PREVOTE))
        self.assertIsNone(self.counter.quorum_block(5, 0, PREVOTE))

    def test_count_any_not_required_same_value(self) -> None:
        self.counter.add(make_vote("N0", block_hash=BLOCK))
        self.counter.add(make_vote("N1", block_hash=BLOCK_B))
        self.counter.add(make_vote("N2", block_hash=None))
        for index in (3, 4, 5, 6):
            self.counter.add(make_vote(f"N{index}", block_hash=BLOCK if index % 2 else BLOCK_B))
        self.assertEqual(self.counter.count_any(5, 0, PREVOTE), 7)
        self.assertTrue(self.counter.has_quorum_any(5, 0, PREVOTE))
        # 4/4 chia hai: không block nào đủ quorum riêng lẻ.
        self.assertIsNone(self.counter.quorum_block(5, 0, PREVOTE))
        self.assertFalse(self.counter.has_quorum_for(5, 0, PREVOTE, BLOCK))

    def test_phases_and_rounds_are_separate_slots(self) -> None:
        self.counter.add(make_vote("N0", phase=PREVOTE, round_num=0))
        self.counter.add(make_vote("N0", phase=PRECOMMIT, round_num=0))
        self.counter.add(make_vote("N0", phase=PREVOTE, round_num=1))
        self.assertEqual(self.counter.count_for(5, 0, PREVOTE, BLOCK), 1)
        self.assertEqual(self.counter.count_for(5, 0, PRECOMMIT, BLOCK), 1)
        self.assertEqual(self.counter.count_for(5, 1, PREVOTE, BLOCK), 1)

    def test_precommit_quorum_any_round_prefers_lowest_round(self) -> None:
        self.counter.add(make_vote("N0", phase=PREVOTE, round_num=3))  # không phải PRECOMMIT
        for index in range(7):
            self.counter.add(make_vote(f"N{index}", phase=PRECOMMIT, round_num=1))
        # Round 0: 6 phiếu chia hai block ⇒ không có quorum.
        for index in range(3):
            self.counter.add(make_vote(f"N{index}", phase=PRECOMMIT, round_num=0, block_hash=BLOCK))
        for index in range(3, 6):
            self.counter.add(
                make_vote(f"N{index}", phase=PRECOMMIT, round_num=0, block_hash=BLOCK_B)
            )
        found = self.counter.precommit_quorum_any_round(5)
        self.assertIsNotNone(found)
        round_num, block_hash = found
        self.assertEqual((round_num, block_hash), (1, BLOCK))

    def test_build_certificate_needs_quorum_and_returns_first_seven(self) -> None:
        self.assertIsNone(self.counter.build_certificate(5, 0, BLOCK))
        for index in range(8):
            self.counter.add(make_vote(f"N{index}", phase=PRECOMMIT))
        certificate = self.counter.build_certificate(5, 0, BLOCK)
        self.assertIsNotNone(certificate)
        self.assertEqual([vote.validator_id for vote in certificate.votes],
                         [f"N{i}" for i in range(7)])
        self.assertEqual(certificate.height, 5)

    def test_round_to_skip_to_requires_f_plus_one(self) -> None:
        # 3 validator bỏ phiếu round 2: chưa đủ f+1 = 4.
        for index in range(3):
            self.counter.add(make_vote(f"N{index}", round_num=2))
        self.assertIsNone(self.counter.round_to_skip_to(5, 0))
        self.counter.add(make_vote("N3", round_num=2))
        self.assertEqual(self.counter.round_to_skip_to(5, 0), 2)
        # Không lùi về sau nếu round hiện tại đã cao hơn.
        self.assertIsNone(self.counter.round_to_skip_to(5, 2))
        self.assertIsNone(self.counter.round_to_skip_to(5, 5))

    def test_prune_and_clear(self) -> None:
        self.counter.add(make_vote("N0", height=4))
        self.counter.add(make_vote("N0", height=5))
        self.counter.prune_below(5)
        self.assertEqual(self.counter.heights(), [5])
        self.counter.clear()
        self.assertEqual(self.counter.heights(), [])

    def test_bad_counter_config_rejected(self) -> None:
        with self.assertRaises(ValueError):
            VoteCounter(quorum=0)
        with self.assertRaises(ValueError):
            VoteCounter(f_plus_one=0)


if __name__ == "__main__":
    unittest.main()
