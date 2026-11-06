"""
Máy trạng thái đồng thuận BFT (propose -> prevote -> precommit -> finalize) của một Node
trong Chat Chain (Mục 4 README). Quorum 7/10 (n = 10, f = 3).

Thiết kế
--------
- Mỗi height có nhiều round; proposer của (height, round) là node (height + round) mod n.
- Trạng thái chính: height, round, step (WAIT/PROPOSE/PREVOTE/PRECOMMIT),
  locked_value/locked_round (đã khóa), valid_value/valid_round (đã thấy đủ prevote).
- Các "luật" được cài dưới dạng hàm idempotent `_rule_*`; sau mỗi sự kiện (message đến,
  body đến, timer nổ) `_evaluate()` chạy lặp các luật cho tới khi trạng thái ổn định.
  Nhờ vậy thứ tự đến của proposal / body / vote không làm sai logic.
- Ba timeout (propose, prevote, precommit) đều bằng `base_ms + step_ms * round`.
  Tên timer mang theo (height, round) nên timer cũ bị bỏ qua khi nổ.
- Lớp này KHÔNG import net/sim. Mọi I/O đi qua `node` (duck-typing):
    node.node_id, node.env, node.view, node.ledger, node.state, node.pool,
    node.validator_pubkeys, node.account_pubkeys, node.private_key,
    node.broadcast_proposal(p), node.broadcast_vote(v), node.send_direct(peer, msg, h, r),
    node.serve_pending_body_requests(block_hash), node.reset_height_state(),
    node.record_finalized(block, round_num, details), node.process_buffered(peer, msg)

Chi tiết lưu ý so với README
----------------------------
- "Thấy 7 prevote bất kỳ nhưng không cùng block thì precommit NIL" được cài như sau:
  precommit NIL NGAY khi có 7 prevote NIL hoặc khi không còn block nào có thể đạt 7
  (đếm cả phiếu chưa về); nếu chưa chắc chắn thì đặt timeout prevote rồi precommit NIL.
  Precommit NIL luôn an toàn nên không ảnh hưởng safety.
- Node chỉ precommit/khóa một block khi đã có body và body đã được kiểm tra hợp lệ.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.core.block import MAX_BLOCK_BYTES, Block
from src.core.proposal import Proposal
from src.core.transaction import MAX_TEXT_CHARS, MAX_TX_BYTES, Transaction
from src.core.vote import PRECOMMIT, PREVOTE, CommitCertificate, Vote
from src.execution.executor import apply_block
from src.logsys.event import REASONS
from src.node.block_builder import build_block, make_proposal
from src.node.interfaces import Verdict
from src.node.proposer import expected_proposer_id
from src.node.validation import (
    BAD_SIGNATURE,
    BAD_TX_ROOT,
    CONFLICTING_VOTE,
    DUPLICATE_VOTE,
    FUTURE_HEIGHT,
    validate_body,
    validate_proposal,
    validate_vote,
)
from src.node.view import BUFFER, PAST

# Các bước của một round
STEP_WAIT: str = "WAIT"  # giữa hai height (đợi block_interval) hoặc trước khi bắt đầu
STEP_PROPOSE: str = "PROPOSE"
STEP_PREVOTE: str = "PREVOTE"
STEP_PRECOMMIT: str = "PRECOMMIT"

NIL_LOG: str = "NIL"


def reject_verdict(reason: str | None) -> Verdict:
    """Verdict REJECT với reason bảo đảm thuộc danh sách cố định (tránh ném ValueError)."""
    return Verdict.reject(reason if reason in REASONS else BAD_SIGNATURE)


def _peer_key(peer_id: str) -> tuple[int, int, str]:
    text = str(peer_id)
    if text.startswith("N") and text[1:].isdigit():
        return (0, int(text[1:]), "")
    return (1, 0, text)


@dataclass(frozen=True)
class ConsensusParams:
    """Tham số đồng thuận lấy từ cấu hình (config/base.json + kịch bản)."""

    chain_id: str
    n: int
    f: int
    quorum: int
    timeout_base_ms: int
    timeout_step_ms: int
    block_interval_ms: int
    status_interval_ms: int
    future_height_window: int
    max_text_chars: int
    max_tx_bytes: int
    max_block_bytes: int
    body_retry_ms: int
    stuck_ms: int
    validators: tuple[str, ...]

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> ConsensusParams:
        n = int(cfg["n"])
        f = int(cfg["f"])
        status_interval = int(cfg.get("status_interval_ms", 2000))
        timeouts = cfg.get("timeouts", {})
        return cls(
            chain_id=str(cfg["chain_id"]),
            n=n,
            f=f,
            quorum=2 * f + 1,
            timeout_base_ms=int(timeouts.get("base_ms", 5000)),
            timeout_step_ms=int(timeouts.get("step_ms", 2000)),
            block_interval_ms=int(cfg.get("block_interval_ms", 1000)),
            status_interval_ms=status_interval,
            future_height_window=int(cfg.get("future_height_window", 5)),
            max_text_chars=int(cfg.get("max_text_chars", MAX_TEXT_CHARS)),
            max_tx_bytes=int(cfg.get("max_tx_bytes", MAX_TX_BYTES)),
            max_block_bytes=int(cfg.get("max_block_bytes", MAX_BLOCK_BYTES)),
            body_retry_ms=int(cfg.get("body_retry_ms", 1000)),
            stuck_ms=int(cfg.get("stuck_ms", 2 * status_interval)),
            validators=tuple(f"N{i}" for i in range(n)),
        )

    def timeout_ms(self, round_num: int) -> int:
        """Timeout của một round: base + step * round."""
        return self.timeout_base_ms + self.timeout_step_ms * max(round_num, 0)


class Consensus:
    """Máy trạng thái đồng thuận của một node."""

    def __init__(self, node: Any, params: ConsensusParams) -> None:
        self.node = node
        self.p = params

        self.height: int = 1
        self.round: int = -1
        self.step: str = STEP_WAIT

        self.locked_value: str | None = None
        self.locked_round: int = -1
        self.valid_value: str | None = None
        self.valid_round: int = -1

        self._armed_prevote: set[int] = set()
        self._armed_precommit: set[int] = set()
        self._body_armed: set[str] = set()
        self._body_attempts: dict[str, int] = {}
        self._replay: list[tuple[str, Any]] = []
        self._last_progress_ms: int = 0
        self._evaluating: bool = False
        self._dirty: bool = False

    # ------------------------------------------------------------------
    # Truy cập nhanh
    # ------------------------------------------------------------------
    @property
    def env(self) -> Any:
        return self.node.env

    @property
    def view(self) -> Any:
        return self.node.view

    @property
    def node_id(self) -> str:
        return self.node.node_id

    def stuck_for_ms(self) -> int:
        """Thời gian (ảo) kể từ lần tiến triển gần nhất (bắt đầu round / finalize)."""
        return self.env.now() - self._last_progress_ms

    def round_for_votes_request(self) -> int:
        """Round dùng cho GET_VOTES khi bị kẹt."""
        return max(self.round, 0)

    # ------------------------------------------------------------------
    # Khởi động và timer
    # ------------------------------------------------------------------
    def on_start(self) -> None:
        """Gọi từ Node.on_start: đợi block_interval rồi bắt đầu round 0 của height 1."""
        self._last_progress_ms = self.env.now()
        self.env.set_timer(f"cs:start:{self.height}", self.p.block_interval_ms)

    def on_timer(self, name: str) -> None:
        """Xử lý timer có tên bắt đầu bằng 'cs:' hoặc 'body:'. Timer cũ (sai height/round) bị bỏ."""
        parts = name.split(":")
        if parts[0] == "body":
            self._on_body_timer(int(parts[1]), parts[2])
            return
        kind = parts[1]
        height = int(parts[2])
        if height != self.height:
            return
        if kind == "start":
            if self.round < 0:
                self._start_round(0, "start")
                self._evaluate()
        elif kind == "replay":
            ready, self._replay = self._replay, []
            for from_peer, message in ready:
                self.node.process_buffered(from_peer, message)
        elif kind in ("propose", "prevote", "precommit"):
            round_num = int(parts[3])
            if round_num != self.round:
                return
            if kind == "propose" and self.step == STEP_PROPOSE:
                self.env.log("TIMEOUT", h=height, r=round_num, details="propose")
                self._cast_prevote(None)
            elif kind == "prevote" and self.step == STEP_PREVOTE:
                self.env.log("TIMEOUT", h=height, r=round_num, details="prevote")
                self._cast_precommit(None)
            elif kind == "precommit":
                self.env.log("TIMEOUT", h=height, r=round_num, details="precommit")
                self._start_round(round_num + 1, "precommit-timeout")
            self._evaluate()

    # ------------------------------------------------------------------
    # Bắt đầu round, đề xuất
    # ------------------------------------------------------------------
    def _start_round(self, round_num: int, reason: str | None = None) -> None:
        self.round = round_num
        self.step = STEP_PROPOSE
        self._last_progress_ms = self.env.now()
        self.env.log("NEW_ROUND", h=self.height, r=round_num, details=reason)
        self.env.set_timer(
            f"cs:propose:{self.height}:{round_num}", self.p.timeout_ms(round_num)
        )
        proposer = expected_proposer_id(
            self.height, round_num, n=self.p.n, validators=self.p.validators
        )
        if proposer == self.node_id:
            self._propose()

    def _propose(self) -> None:
        """Proposer của round: đề xuất lại valid_value nếu có, ngược lại dựng block mới."""
        node = self.node
        height, round_num = self.height, self.round
        proposal: Proposal | None = None

        if self.valid_value is not None:
            known = self.view.get_block(self.valid_value)
            if known is not None:
                proposal = make_proposal(
                    known,
                    round_num=round_num,
                    pol_round=self.valid_round,
                    proposer_id=self.node_id,
                    private_key=node.private_key,
                    chain_id=self.p.chain_id,
                )

        if proposal is None:
            result = build_block(
                height=height,
                parent=node.ledger.latest(),
                parent_state=node.state,
                pool=node.pool,
                proposer_id=self.node_id,
                private_key=node.private_key,
                now_ms=self.env.now(),
                account_pubkeys=node.account_pubkeys,
                chain_id=self.p.chain_id,
                max_text_chars=self.p.max_text_chars,
                max_tx_bytes=self.p.max_tx_bytes,
                max_block_bytes=self.p.max_block_bytes,
            )
            for tx, reason in result.skipped:
                self.env.log(
                    "TX_SKIPPED", h=height, r=round_num, reason=reason, details=tx.key
                )
            block = result.block
            block_hash = str(block.block_hash())
            self.view.register_header(block.header)
            self.view.add_body(block_hash, block.transactions)
            self.view.set_body_validity(block_hash, True, None)
            proposal = make_proposal(
                block,
                round_num=round_num,
                pol_round=-1,
                proposer_id=self.node_id,
                private_key=node.private_key,
                chain_id=self.p.chain_id,
            )

        body = self.view.get_body(proposal.block_hash)
        self.env.log(
            "PROPOSE",
            h=height,
            r=round_num,
            hash=proposal.block_hash,
            details=f"txs:{len(body) if body is not None else '?'};pol:{proposal.pol_round}",
        )
        self.view.add_proposal(proposal)
        node.broadcast_proposal(proposal)

    # ------------------------------------------------------------------
    # Xử lý message (Node gọi, trả Verdict)
    # ------------------------------------------------------------------
    def handle_proposal(self, from_peer: str, message: Any) -> Verdict:
        proposal = message.payload
        if not isinstance(proposal, Proposal):
            return reject_verdict(BAD_SIGNATURE)
        cls = self.view.classify_height(proposal.height)
        if cls == PAST:
            return Verdict.ignore()

        parent = self.node.ledger.latest() if proposal.height == self.view.height else None
        ok, reason = validate_proposal(
            proposal,
            parent_header_or_block=parent,
            validator_pubkeys=self.node.validator_pubkeys,
            chain_id=self.p.chain_id,
            sender_id=message.origin,
            current_height=self.view.height,
            future_height_window=self.p.future_height_window,
            n=self.p.n,
            validators=self.p.validators,
        )
        if not ok:
            return reject_verdict(reason)

        if cls == BUFFER:
            if not self.view.buffer_future(proposal.height, from_peer, message):
                return reject_verdict(FUTURE_HEIGHT)
            return Verdict.accept()

        if not self.view.add_proposal(proposal):
            return Verdict.ignore()
        if not self.view.has_body(proposal.block_hash):
            self._request_body(proposal.block_hash, prefer=from_peer)
        self._evaluate()
        return Verdict.accept()

    def handle_vote(self, from_peer: str, message: Any) -> Verdict:
        vote = message.payload
        if not isinstance(vote, Vote):
            return reject_verdict(BAD_SIGNATURE)
        cls = self.view.classify_height(vote.height)
        if cls == PAST:
            return Verdict.ignore()
        ok, reason = validate_vote(
            vote,
            validator_pubkeys=self.node.validator_pubkeys,
            chain_id=self.p.chain_id,
            current_height=self.view.height,
            future_height_window=self.p.future_height_window,
        )
        if not ok:
            return reject_verdict(reason)
        if cls == BUFFER:
            if not self.view.buffer_future(vote.height, from_peer, message):
                return reject_verdict(FUTURE_HEIGHT)
            return Verdict.accept()

        result = self.view.votes.add(vote)
        if result.is_duplicate:
            return reject_verdict(DUPLICATE_VOTE)
        if result.is_conflict:
            return reject_verdict(CONFLICTING_VOTE)
        self._evaluate()
        return Verdict.accept()

    def ingest_external_vote(self, vote: Vote) -> None:
        """Vote đã được kiểm tra (nhận qua VOTES khi đồng bộ): chỉ đếm, không chuyển tiếp."""
        if vote.height != self.view.height:
            return
        result = self.view.votes.add(vote)
        if result.added:
            self._evaluate()

    def handle_body(self, from_peer: str, payload: Any) -> Verdict:
        """BODY trả lời BODY_REQUEST: kiểm tra body đối chiếu header đã nhận qua PROPOSAL."""
        try:
            height = int(payload["height"])
            block_hash = str(payload["block_hash"])
            transactions = list(payload["transactions"])
        except (KeyError, TypeError, ValueError):
            return reject_verdict(BAD_TX_ROOT)
        if height != self.view.height:
            return Verdict.ignore()
        if self.view.has_body(block_hash):
            return Verdict.ignore()
        header = self.view.get_header(block_hash)
        if header is None:
            return Verdict.ignore()  # không có header tương ứng: body không được yêu cầu
        if not all(isinstance(tx, Transaction) for tx in transactions):
            return reject_verdict(BAD_TX_ROOT)

        ok, reason = validate_body(
            header,
            transactions,
            self.node.state,
            account_pubkeys=self.node.account_pubkeys,
            chain_id=self.p.chain_id,
            max_text_chars=self.p.max_text_chars,
            max_tx_bytes=self.p.max_tx_bytes,
            max_block_bytes=self.p.max_block_bytes,
        )
        self.view.add_body(block_hash, transactions)
        self.view.set_body_validity(block_hash, ok, reason)
        self._body_armed.discard(block_hash)
        self.node.serve_pending_body_requests(block_hash)
        self._evaluate()
        return Verdict.accept() if ok else reject_verdict(reason)

    # ------------------------------------------------------------------
    # Yêu cầu body
    # ------------------------------------------------------------------
    def _request_body(self, block_hash: str, prefer: str | None = None) -> None:
        """Gửi BODY_REQUEST cho một peer và đặt timer thử lại sang peer khác."""
        if block_hash in self._body_armed or self.view.has_body(block_hash):
            return
        header = self.view.get_header(block_hash)
        peers = sorted(self.env.peers, key=_peer_key)
        if header is None or not peers:
            return
        asked = self.view.body_requested_from(block_hash)
        fresh = [peer for peer in peers if peer not in asked]
        attempt = self._body_attempts.get(block_hash, 0)
        if prefer is not None and prefer in fresh:
            peer = prefer
        elif fresh:
            peer = fresh[0]
        else:
            peer = peers[attempt % len(peers)]
        self._body_attempts[block_hash] = attempt + 1
        self.view.mark_body_requested(block_hash, peer)
        self._body_armed.add(block_hash)
        # Import muộn để consensus không phụ thuộc cứng vào wire ở mức module.
        from src.core.wire import make_body_request_message

        self.node.send_direct(
            peer,
            make_body_request_message(self.node_id, header.height, block_hash),
            header.height,
            None,
        )
        self.env.set_timer(f"body:{self.height}:{block_hash}", self.p.body_retry_ms)

    def _ensure_body(self, block_hash: str) -> None:
        self._request_body(block_hash)

    def _on_body_timer(self, height: int, block_hash: str) -> None:
        if height != self.height:
            return
        self._body_armed.discard(block_hash)
        if not self.view.has_body(block_hash):
            self._request_body(block_hash)

    # ------------------------------------------------------------------
    # Kiểm tra body / block đã biết
    # ------------------------------------------------------------------
    def _validity(self, block_hash: str) -> tuple[bool, str | None] | None:
        cached = self.view.get_body_validity(block_hash)
        if cached is not None:
            return cached
        header = self.view.get_header(block_hash)
        body = self.view.get_body(block_hash)
        if header is None or body is None:
            return None
        ok, reason = validate_body(
            header,
            body,
            self.node.state,
            account_pubkeys=self.node.account_pubkeys,
            chain_id=self.p.chain_id,
            max_text_chars=self.p.max_text_chars,
            max_tx_bytes=self.p.max_tx_bytes,
            max_block_bytes=self.p.max_block_bytes,
        )
        self.view.set_body_validity(block_hash, ok, reason)
        return ok, reason

    def _known_valid_block(self, block_hash: str) -> Block | None:
        validity = self._validity(block_hash)
        if validity is None or not validity[0]:
            return None
        return self.view.get_block(block_hash)

    # ------------------------------------------------------------------
    # Vòng lặp luật
    # ------------------------------------------------------------------
    def _evaluate(self) -> None:
        """Chạy lặp các luật cho tới khi trạng thái ổn định (có chống đệ quy)."""
        if self._evaluating:
            self._dirty = True
            return
        self._evaluating = True
        try:
            for _ in range(64):
                self._dirty = False
                if self._rule_finalize():
                    continue
                if self.round < 0:
                    if not self._dirty:
                        break
                    continue
                changed = False
                changed |= self._rule_round_skip()
                changed |= self._rule_prevote()
                changed |= self._rule_lock_and_precommit_block()
                changed |= self._rule_precommit_nil()
                self._rule_arm_timeouts()
                if not (changed or self._dirty):
                    break
        finally:
            self._evaluating = False

    def _rule_finalize(self) -> bool:
        """Thấy 7 precommit cùng một block ở một round bất kỳ của height hiện tại -> finalize."""
        found = self.view.votes.precommit_quorum_any_round(self.height)
        if found is None:
            return False
        round_num, block_hash = found
        block = self._known_valid_block(block_hash)
        if block is None:
            self._ensure_body(block_hash)
            return False
        certificate = self.view.votes.build_certificate(self.height, round_num, block_hash)
        if certificate is None:
            return False
        return self._finalize(block, certificate, round_num)

    def _rule_round_skip(self) -> bool:
        """Thấy f+1 validator đã bỏ phiếu ở round cao hơn -> nhảy sang round đó."""
        target = self.view.votes.round_to_skip_to(self.height, self.round)
        if target is not None and target > self.round:
            self._start_round(target, "skip")
            return True
        return False

    def _current_round_proposal(self) -> Proposal | None:
        proposals = self.view.proposals_for_round(self.round)
        return proposals[0] if proposals else None

    def _rule_prevote(self) -> bool:
        """Ở bước PROPOSE, khi đã có proposal + body của round hiện tại -> prevote."""
        if self.step != STEP_PROPOSE:
            return False
        proposal = self._current_round_proposal()
        if proposal is None:
            return False
        block_hash = proposal.block_hash
        if not self.view.has_body(block_hash):
            self._ensure_body(block_hash)
            return False
        validity = self._validity(block_hash)
        if validity is None:
            return False
        if not validity[0]:
            self._cast_prevote(None, details=f"invalid:{validity[1]}")
            return True

        if proposal.pol_round == -1:
            acceptable = self.locked_round == -1 or self.locked_value == block_hash
        else:
            pol = proposal.pol_round
            enough = self.view.votes.count_for(self.height, pol, PREVOTE, block_hash)
            if enough < self.p.quorum:
                return False  # chưa chứng minh được POL; đợi vote hoặc timeout propose
            acceptable = self.locked_round <= pol or self.locked_value == block_hash
        self._cast_prevote(block_hash if acceptable else None)
        return True

    def _rule_lock_and_precommit_block(self) -> bool:
        """7 prevote cùng một block ở round hiện tại -> ghi valid_value; nếu đang PREVOTE thì khóa và precommit."""
        block_hash = self.view.votes.quorum_block(self.height, self.round, PREVOTE)
        if block_hash is None:
            return False
        if self._known_valid_block(block_hash) is None:
            self._ensure_body(block_hash)
            return False
        changed = False
        if self.step in (STEP_PREVOTE, STEP_PRECOMMIT):
            if self.valid_round < self.round or self.valid_value != block_hash:
                self.valid_value = block_hash
                self.valid_round = self.round
                changed = True
        if self.step == STEP_PREVOTE:
            self.locked_value = block_hash
            self.locked_round = self.round
            self.env.log("LOCK", h=self.height, r=self.round, hash=block_hash)
            self._cast_precommit(block_hash)
            changed = True
        return changed

    def _rule_precommit_nil(self) -> bool:
        """Precommit NIL khi chắc chắn không block nào đạt quorum prevote ở round này."""
        if self.step != STEP_PREVOTE:
            return False
        votes = self.view.votes
        total = votes.count_any(self.height, self.round, PREVOTE)
        if total < self.p.quorum:
            return False
        remaining = self.p.n - total
        for block_hash, count in votes.tally(self.height, self.round, PREVOTE).items():
            if block_hash is not None and count + remaining >= self.p.quorum:
                return False
        self._cast_precommit(None, details="no-block-quorum")
        return True

    def _rule_arm_timeouts(self) -> None:
        """Đặt timeout prevote/precommit khi thấy 7 phiếu bất kỳ ở round hiện tại."""
        votes = self.view.votes
        height, round_num = self.height, self.round
        if (
            self.step == STEP_PREVOTE
            and round_num not in self._armed_prevote
            and votes.has_quorum_any(height, round_num, PREVOTE)
        ):
            self._armed_prevote.add(round_num)
            self.env.set_timer(f"cs:prevote:{height}:{round_num}", self.p.timeout_ms(round_num))
        if round_num not in self._armed_precommit and votes.has_quorum_any(
            height, round_num, PRECOMMIT
        ):
            self._armed_precommit.add(round_num)
            self.env.set_timer(f"cs:precommit:{height}:{round_num}", self.p.timeout_ms(round_num))

    # ------------------------------------------------------------------
    # Bỏ phiếu
    # ------------------------------------------------------------------
    def _cast_prevote(self, block_hash: str | None, details: str | None = None) -> None:
        vote = Vote(
            height=self.height,
            round=self.round,
            phase=PREVOTE,
            block_hash=block_hash,
            validator_id=self.node_id,
        )
        vote.sign(self.node.private_key, self.p.chain_id)
        self.step = STEP_PREVOTE
        self.env.log(
            "PREVOTE",
            h=self.height,
            r=self.round,
            hash=block_hash if block_hash is not None else NIL_LOG,
            details=details,
        )
        self.view.votes.add(vote)
        self.node.broadcast_vote(vote)

    def _cast_precommit(self, block_hash: str | None, details: str | None = None) -> None:
        vote = Vote(
            height=self.height,
            round=self.round,
            phase=PRECOMMIT,
            block_hash=block_hash,
            validator_id=self.node_id,
        )
        vote.sign(self.node.private_key, self.p.chain_id)
        self.step = STEP_PRECOMMIT
        self.env.log(
            "PRECOMMIT",
            h=self.height,
            r=self.round,
            hash=block_hash if block_hash is not None else NIL_LOG,
            details=details,
        )
        self.view.votes.add(vote)
        self.node.broadcast_vote(vote)

    # ------------------------------------------------------------------
    # Finalize và sang height mới
    # ------------------------------------------------------------------
    def _finalize(self, block: Block, certificate: CommitCertificate, round_num: int) -> bool:
        node = self.node
        new_state, exec_reason = apply_block(
            node.state,
            block,
            account_pubkeys=node.account_pubkeys,
            chain_id=self.p.chain_id,
            max_text_chars=self.p.max_text_chars,
            max_tx_bytes=self.p.max_tx_bytes,
            max_block_bytes=self.p.max_block_bytes,
            dry_run=False,
            verify_commitments=True,
            mutate_in_place=False,
        )
        if new_state is None:
            self.env.log(
                "REJECT",
                h=self.height,
                r=round_num,
                reason=exec_reason if exec_reason in REASONS else BAD_SIGNATURE,
                details="finalize-apply",
            )
            return False
        ok, reason = node.ledger.append(
            block, certificate, node.validator_pubkeys, self.p.quorum
        )
        if not ok:
            self.env.log(
                "REJECT",
                h=self.height,
                r=round_num,
                reason=reason if reason in REASONS else BAD_SIGNATURE,
                details="finalize-ledger",
            )
            return False
        node.state.replace_from(new_state)  # giữ nguyên object để SyncManager dùng chung
        node.pool.remove_finalized(block.transactions, state=node.state)
        node.record_finalized(block, round_num, None)
        self._advance_height(block.height + 1, self.p.block_interval_ms)
        return True

    def _advance_height(self, new_height: int, delay_ms: int) -> None:
        """Sang height mới: dọn view, đặt lại khóa, hẹn bắt đầu round 0 sau delay_ms."""
        self._replay = self.view.advance(new_height)
        self.height = new_height
        self.round = -1
        self.step = STEP_WAIT
        self.locked_value = None
        self.locked_round = -1
        self.valid_value = None
        self.valid_round = -1
        self._armed_prevote.clear()
        self._armed_precommit.clear()
        self._body_armed.clear()
        self._body_attempts.clear()
        self._last_progress_ms = self.env.now()
        self.node.reset_height_state()
        self.env.set_timer(f"cs:start:{new_height}", delay_ms)
        if self._replay:
            self.env.set_timer(f"cs:replay:{new_height}", 0)

    def on_chain_advanced(self) -> None:
        """Gọi sau khi SyncManager áp thêm block: nhảy tới height kế tiếp của sổ cái."""
        target = self.node.ledger.latest_height + 1
        if target <= self.view.height:
            return
        self._advance_height(target, 0)