"""
Node hoàn chỉnh của Chat Chain: ghép tx pool, state, ledger, sync, view, consensus
và hành vi lỗi (Behavior) thành một đối tượng tuân thủ `NodeCallbacks`
(src/node/interfaces.py). Node chỉ nói chuyện với bên ngoài qua `env` (NodeEnv),
tuyệt đối không import src.net hay src.sim.

Hợp đồng với main.py / Simulator:
    build_node(node_id=..., env=..., behavior=..., config=...) -> Node
    node.on_start(), node.on_message(from_peer, message) -> Verdict,
    node.on_timer(name), node.finalized_chain(), node.final_state_hash(),
    node.behavior (Network đọc để áp on_send), node.env.

Hợp đồng với faults/ (hook mà Behavior gọi lên node):
    make_conflicting_vote, make_conflicting_proposal, resign_wrong_domain,
    tamper_signed_message, rebuild_wire_message, make_invalid_proposal.

Quy ước timer: 'cs:*' và 'body:*' thuộc consensus, 'sync:status' thuộc node,
'fault:*' thuộc Behavior (ví dụ replay).
"""

from __future__ import annotations

import json
from typing import Any

from src.core.block import Block
from src.core.proposal import Proposal
from src.core.transaction import Transaction
from src.core.user import create_account_book
from src.core.vote import Vote
from src.core.wire import (
    BLOCKS,
    BODY,
    BODY_REQUEST,
    GET_BLOCKS,
    GET_VOTES,
    PRECOMMIT,
    PREVOTE,
    PROPOSAL,
    STATUS,
    TX,
    VOTES,
    Message,
    make_body_message,
    make_proposal_message,
    make_vote_message,
)
from src.crypto.signing import derive_validator_keypairs
from src.execution.state import State
from src.faults.signed import SignedFaultAdapter
from src.node.block_builder import build_invalid_block, make_proposal
from src.node.consensus import Consensus, ConsensusParams, reject_verdict
from src.node.interfaces import Verdict
from src.node.ledger import Ledger
from src.node.sync import SyncManager
from src.node.tx_pool import TxPool
from src.node.validation import BAD_SIGNATURE, validate_body
from src.node.view import View

SYNC_TIMER: str = "sync:status"
CONSENSUS_KINDS: tuple[str, ...] = (PROPOSAL, PREVOTE, PRECOMMIT)


def _peer_key(peer_id: str) -> tuple[int, int, str]:
    text = str(peer_id)
    if text.startswith("N") and text[1:].isdigit():
        return (0, int(text[1:]), "")
    return (1, 0, text)


class Node:
    """Một validator trong mạng Chat Chain."""

    def __init__(self, node_id: str, env: Any, behavior: Any, config: dict[str, Any]) -> None:
        self.node_id: str = node_id
        self.env: Any = env
        self.behavior: Any = behavior
        self.config: dict[str, Any] = config

        self.params = ConsensusParams.from_config(config)
        seed = config["seed"]
        chain_id = self.params.chain_id

        # Khóa: chỉ giữ khóa bí mật của chính mình, các node khác chỉ có khóa công khai.
        keypairs = derive_validator_keypairs(seed, self.params.n)
        if node_id not in keypairs:
            raise ValueError(f"Node {node_id} không thuộc tập validator")
        self.validator_pubkeys = {name: pair[1] for name, pair in keypairs.items()}
        self.private_key = keypairs[node_id][0]
        self.keys = {node_id: keypairs[node_id]}
        self.account_pubkeys = create_account_book(seed)

        # Các thành phần dùng chung; SyncManager giữ CÙNG object state/ledger/pool.
        self.state: State = State()
        self.ledger: Ledger = Ledger(chain_id, self.validator_pubkeys, self.params.quorum)
        self.pool: TxPool = TxPool(
            self.account_pubkeys,
            chain_id,
            self.params.max_text_chars,
            self.params.max_tx_bytes,
        )
        self.sync: SyncManager = SyncManager(
            node_id,
            self.ledger,
            self.state,
            tx_pool=self.pool,
            validator_pubkeys=self.validator_pubkeys,
            account_pubkeys=self.account_pubkeys,
            chain_id=chain_id,
            quorum=self.params.quorum,
            status_interval_ms=self.params.status_interval_ms,
            max_text_chars=self.params.max_text_chars,
            max_tx_bytes=self.params.max_tx_bytes,
            max_block_bytes=self.params.max_block_bytes,
        )
        self.view: View = View(
            height=1,
            quorum=self.params.quorum,
            f_plus_one=self.params.f + 1,
            future_height_window=self.params.future_height_window,
        )
        self.consensus: Consensus = Consensus(self, self.params)

        self._fault = SignedFaultAdapter(node_id, self.private_key, chain_id)
        self._chain: list[dict[str, Any]] = []
        self._pending_body_requests: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # NodeCallbacks
    # ------------------------------------------------------------------
    def on_start(self) -> None:
        self.consensus.on_start()
        self.env.set_timer(SYNC_TIMER, self.params.status_interval_ms)

    def on_timer(self, name: str) -> None:
        if name.startswith("fault:"):
            for peer, message in self.behavior.on_timer(self, name):
                self.env.send(peer, message)
        elif name.startswith("cs:") or name.startswith("body:"):
            self.consensus.on_timer(name)
        elif name == SYNC_TIMER:
            self._on_sync_timer()

    def on_message(self, from_peer: str, message: Message) -> Verdict:
        message = self.behavior.on_receive(self, from_peer, message)
        if message is None:
            return Verdict.ignore()
        return self._dispatch(from_peer, message)

    def finalized_chain(self) -> list[dict[str, Any]]:
        """Chuỗi đã finalize (không gồm genesis): [{'height','hash','state_hash'}, ...]."""
        return list(self._chain)

    def final_state_hash(self) -> str:
        return str(self.state.state_hash())

    # ------------------------------------------------------------------
    # Điều phối message theo kind
    # ------------------------------------------------------------------
    def _dispatch(self, from_peer: str, message: Message) -> Verdict:
        kind = message.kind
        # Tin do chính mình tạo quay lại (gửi trực tiếp không được đánh dấu seen): bỏ qua.
        if kind in CONSENSUS_KINDS and message.origin == self.node_id:
            return Verdict.ignore()

        if kind == TX:
            return self._on_tx(message.payload)
        if kind == PROPOSAL:
            return self.consensus.handle_proposal(from_peer, message)
        if kind in (PREVOTE, PRECOMMIT):
            return self.consensus.handle_vote(from_peer, message)
        if kind == BODY_REQUEST:
            return self._on_body_request(from_peer, message.payload)
        if kind == BODY:
            return self.consensus.handle_body(from_peer, message.payload)
        if kind == STATUS:
            self.sync.handle_status(from_peer, message.payload, self.env)
            return Verdict.accept()
        if kind == GET_BLOCKS:
            self.sync.handle_get_blocks(from_peer, message.payload, self.env)
            return Verdict.accept()
        if kind == BLOCKS:
            return self._on_blocks(from_peer, message.payload)
        if kind == GET_VOTES:
            self.sync.handle_get_votes(
                from_peer, message.payload, self._votes_provider, self.env
            )
            return Verdict.accept()
        if kind == VOTES:
            return self._on_votes(from_peer, message.payload)
        return Verdict.ignore()  # HELLO / PING / PONG / kind lạ

    def process_buffered(self, from_peer: str, message: Message) -> None:
        """Xử lý lại message đã đệm khi sang height mới (kết quả Verdict bị bỏ)."""
        self._dispatch(from_peer, message)

    # ------------------------------------------------------------------
    # Từng loại message
    # ------------------------------------------------------------------
    def _on_tx(self, tx: Any) -> Verdict:
        if not isinstance(tx, Transaction):
            return reject_verdict(BAD_SIGNATURE)
        ok, reason = self.pool.add(tx, self.state)
        return Verdict.accept() if ok else reject_verdict(reason)

    def _on_body_request(self, from_peer: str, payload: Any) -> Verdict:
        try:
            height = int(payload["height"])
            block_hash = str(payload["block_hash"])
        except (KeyError, TypeError, ValueError):
            return Verdict.ignore()
        if height != self.view.height:
            return Verdict.ignore()  # block cũ hơn: peer dùng đồng bộ GET_BLOCKS
        body = self.view.get_body(block_hash)
        if body is None:
            # Chỉ mới có header (đã chuyển tiếp proposal): nhớ lại, trả lời khi body về.
            waiting = self._pending_body_requests.setdefault(block_hash, [])
            if from_peer not in waiting:
                waiting.append(from_peer)
            return Verdict.accept()
        self._send_body(from_peer, height, block_hash, body)
        return Verdict.accept()

    def _send_body(self, peer: str, height: int, block_hash: str, body: list[Transaction]) -> None:
        self.env.send(
            peer,
            make_body_message(self.node_id, height, block_hash, body),
            h=height,
        )

    def serve_pending_body_requests(self, block_hash: str) -> None:
        """Consensus gọi khi body của block_hash vừa về: trả lời các peer đã hỏi trước đó."""
        body = self.view.get_body(block_hash)
        peers = self._pending_body_requests.pop(block_hash, [])
        if body is None:
            return
        for peer in peers:
            self._send_body(peer, self.view.height, block_hash, body)

    def reset_height_state(self) -> None:
        """Consensus gọi khi sang height mới."""
        self._pending_body_requests.clear()

    def _on_blocks(self, from_peer: str, payload: Any) -> Verdict:
        ok, reason, applied = self.sync.handle_blocks(from_peer, payload, self._on_synced_block)
        if applied:
            self.consensus.on_chain_advanced()
        return Verdict.accept() if ok else reject_verdict(reason)

    def _on_synced_block(self, block: Block, certificate: Any, state: State) -> None:
        self.record_finalized(block, certificate.round, "sync")

    def _votes_provider(self, height: int, round_num: int) -> list[Vote]:
        if height != self.view.height:
            return []
        return self.view.votes.votes_in_round(height, round_num)

    def _on_votes(self, from_peer: str, payload: Any) -> Verdict:
        ok, reason, _ = self.sync.handle_votes(
            from_peer,
            payload,
            on_valid_vote=self.consensus.ingest_external_vote,
            current_height=self.view.height,
            future_height_window=self.params.future_height_window,
        )
        return Verdict.accept() if ok else reject_verdict(reason)

    # ------------------------------------------------------------------
    # Đồng bộ định kỳ
    # ------------------------------------------------------------------
    def _on_sync_timer(self) -> None:
        self.sync.broadcast_status(self.env)
        if self.consensus.stuck_for_ms() >= self.params.stuck_ms:
            self.sync.request_votes(
                self.view.height, self.consensus.round_for_votes_request(), self.env
            )
        self.env.set_timer(SYNC_TIMER, self.params.status_interval_ms)

    # ------------------------------------------------------------------
    # Ghi nhận block đã finalize (từ consensus hoặc từ đồng bộ)
    # ------------------------------------------------------------------
    def record_finalized(self, block: Block, round_num: int, details: str | None = None) -> None:
        """Ghi log TX_APPLIED cho từng tx, FINALIZE cho block, và cập nhật chuỗi đã finalize."""
        for tx in block.transactions:
            tx_details = {k: v for k, v in tx.to_dict().items() if k != "signature"}
            self.env.log(
                "TX_APPLIED",
                h=block.height,
                r=round_num,
                details=json.dumps(tx_details, ensure_ascii=False, sort_keys=True),
            )
        block_hash = str(block.block_hash())
        self.env.log(
            "FINALIZE",
            h=block.height,
            r=round_num,
            origin=block.proposer_id,
            hash=block_hash,
            state=str(block.header.state_hash),
            details=details,
        )
        self._chain.append(
            {
                "height": block.height,
                "hash": block_hash,
                "state_hash": str(block.header.state_hash),
            }
        )

    # ------------------------------------------------------------------
    # Phát đi proposal / vote qua Behavior
    # ------------------------------------------------------------------
    def broadcast_proposal(self, proposal: Proposal) -> None:
        outputs = self.behavior.on_make_proposal(self, proposal)
        self._emit(proposal, outputs, make_proposal_message, proposal.height, proposal.round)

    def broadcast_vote(self, vote: Vote) -> None:
        outputs = self.behavior.on_make_vote(self, vote)
        self._emit(vote, outputs, make_vote_message, vote.height, vote.round)

    def send_direct(self, peer: str, message: Message, height: int = -1, round_num: int | None = None) -> None:
        self.env.send(peer, message, h=height, r=round_num)

    def _emit(self, original: Any, outputs: list, factory: Any, height: int, round_num: int) -> None:
        """
        Honest: output là [(mọi peer, chính đối tượng gốc)] -> gossip để mạng khử trùng đúng.
        Lỗi (equivocate, invalid_block...): gửi trực tiếp từng peer theo output của Behavior.
        """
        all_peers = sorted(self.env.peers, key=_peer_key)
        if (
            len(outputs) == 1
            and outputs[0][1] is original
            and sorted(outputs[0][0], key=_peer_key) == all_peers
        ):
            self.env.gossip(factory(self.node_id, original), h=height, r=round_num)
            return
        for peers, payload in outputs:
            message = factory(self.node_id, payload)
            for peer in sorted(peers, key=_peer_key):
                self.env.send(peer, message, h=height, r=round_num)

    # ------------------------------------------------------------------
    # Hook cho node lỗi (faults/ gọi lên)
    # ------------------------------------------------------------------
    def make_conflicting_vote(self, vote: Vote) -> Vote:
        return self._fault.make_conflicting_vote(vote)

    def make_conflicting_proposal(self, proposal: Proposal) -> Proposal:
        other = self._fault.make_conflicting_proposal(proposal)
        body = self.view.get_body(proposal.block_hash)
        if body is not None:
            # Phục vụ BODY cho cả hai block mâu thuẫn.
            self.view.register_header(other.header)
            self.view.add_body(other.block_hash, body)
            self.view.set_body_validity(other.block_hash, True, None)
        return other

    def resign_wrong_domain(self, message: Any) -> Any:
        return self._fault.resign_wrong_domain(message)

    def tamper_signed_message(self, message: Any) -> Any:
        return self._fault.tamper_signed_message(message)

    def rebuild_wire_message(self, message: Any) -> Any:
        """msg_id được tính từ nội dung (Message.msg_id) nên không cần dựng lại gì thêm."""
        return message

    def make_invalid_proposal(self, proposal: Proposal, mode: str) -> Proposal:
        """Dựng proposal chứa block sai theo mode; nếu thiếu nguyên liệu thì giữ proposal đúng."""
        applied_txs = [
            tx
            for blk in self.ledger.all_blocks(include_genesis=False)
            for tx in blk.transactions
        ]
        block = build_invalid_block(
            mode=mode,
            height=proposal.height,
            parent=self.ledger.latest(),
            parent_state=self.state,
            pool=self.pool,
            proposer_id=self.node_id,
            private_key=self.private_key,
            now_ms=self.env.now(),
            account_pubkeys=self.account_pubkeys,
            chain_id=self.params.chain_id,
            max_text_chars=self.params.max_text_chars,
            max_tx_bytes=self.params.max_tx_bytes,
            max_block_bytes=self.params.max_block_bytes,
            applied_txs=applied_txs,
        )
        if block is None:
            return proposal
        block_hash = str(block.block_hash())
        ok, reason = validate_body(
            block.header,
            block.transactions,
            self.state,
            account_pubkeys=self.account_pubkeys,
            chain_id=self.params.chain_id,
            max_text_chars=self.params.max_text_chars,
            max_tx_bytes=self.params.max_tx_bytes,
            max_block_bytes=self.params.max_block_bytes,
        )
        self.view.register_header(block.header)
        self.view.add_body(block_hash, block.transactions)
        self.view.set_body_validity(block_hash, ok, reason)
        return make_proposal(
            block,
            round_num=proposal.round,
            pol_round=-1,
            proposer_id=self.node_id,
            private_key=self.private_key,
            chain_id=self.params.chain_id,
        )


def build_node(node_id: str, env: Any, behavior: Any, config: dict[str, Any]) -> Node:
    """Factory được main.py gọi cho từng node."""
    return Node(node_id=node_id, env=env, behavior=behavior, config=config)