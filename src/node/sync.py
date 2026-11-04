"""
Bộ quản lý đồng bộ bù mất mát (SyncManager) cho các Node bị tụt lại phía sau
hoặc bị kẹt ở một vòng đồng thuận trong Chat Chain.

Quy tắc hoạt động của Sync (Mục 5.4 & 12 README):
- Cứ mỗi status_interval_ms (2000 ms), mỗi node gửi gói STATUS (height, last_hash)
  trực tiếp cho các peer lân cận.
- Khi nhận STATUS từ một peer có height cao hơn: node gửi GET_BLOCKS(from, to)
  cho peer đó; khi nhận lại BLOCKS kèm CommitCertificate thì tự kiểm tra đầy đủ
  chứng nhận và thực thi khối thay vì tin tưởng peer.
- Khi node bị kẹt ở (height, round) quá lâu: gửi GET_VOTES(height, round) để xin
  các phiếu bầu còn thiếu và xử lý gói VOTES trả về.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from src.core.block import MAX_BLOCK_BYTES, Block
from src.core.header import DEFAULT_CHAIN_ID
from src.core.transaction import MAX_TEXT_CHARS, MAX_TX_BYTES
from src.core.vote import DEFAULT_QUORUM, CommitCertificate, Vote
from src.core.wire import (
    Message,
    make_blocks_message,
    make_get_blocks_message,
    make_get_votes_message,
    make_status_message,
    make_votes_message,
)
from src.execution.executor import apply_block
from src.execution.state import State
from src.node.ledger import Ledger
from src.node.tx_pool import TxPool
from src.node.validation import (
    BAD_PARENT,
    BAD_SIGNATURE,
    validate_block,
    validate_vote,
)

DEFAULT_STATUS_INTERVAL_MS: int = 2000
SYNC_TIMER_KIND: str = "STATUS"


class SyncManager:
    """
    Thành phần phụ trách đồng bộ chuỗi khối (STATUS, GET_BLOCKS, BLOCKS)
    và đồng bộ phiếu bầu (GET_VOTES, VOTES) của một Node.
    Không phụ thuộc cứng vào lớp mạng bên dưới mà giao tiếp qua đối tượng env
    (nếu được cung cấp) hoặc trả về danh sách gói tin cần gửi.
    """

    def __init__(
        self,
        node_id: str,
        ledger: Ledger,
        state: State,
        tx_pool: TxPool | None = None,
        validator_pubkeys: Mapping[str, bytes | str] | None = None,
        account_pubkeys: Mapping[str, bytes | str] | None = None,
        chain_id: str = DEFAULT_CHAIN_ID,
        quorum: int = DEFAULT_QUORUM,
        status_interval_ms: int = DEFAULT_STATUS_INTERVAL_MS,
        max_text_chars: int = MAX_TEXT_CHARS,
        max_tx_bytes: int = MAX_TX_BYTES,
        max_block_bytes: int = MAX_BLOCK_BYTES,
    ) -> None:
        self.node_id: str = node_id
        self.ledger: Ledger = ledger
        self.state: State = state
        self.tx_pool: TxPool | None = tx_pool
        self.validator_pubkeys: dict[str, bytes | str] | None = (
            dict(validator_pubkeys) if validator_pubkeys is not None else ledger.validator_pubkeys
        )
        self.account_pubkeys: dict[str, bytes | str] | None = (
            dict(account_pubkeys)
            if account_pubkeys is not None
            else (
                dict(tx_pool.account_pubkeys)
                if tx_pool is not None and tx_pool.account_pubkeys is not None
                else None
            )
        )
        self.chain_id: str = chain_id
        self.quorum: int = quorum
        self.status_interval_ms: int = status_interval_ms
        self.max_text_chars: int = max_text_chars
        self.max_tx_bytes: int = max_tx_bytes
        self.max_block_bytes: int = max_block_bytes

        # Ghi nhận trạng thái chiều cao đã biết của từng peer
        self.peer_status: dict[str, dict[str, Any]] = {}

    def build_status_message(self) -> Message:
        """Tạo gói tin STATUS chứa chiều cao và mã băm khối finalize cuối cùng của node."""
        return make_status_message(
            origin=self.node_id,
            height=self.ledger.latest_height,
            last_hash=str(self.ledger.latest_hash()),
        )

    def broadcast_status(self, env: Any = None, peers: Sequence[str] | None = None) -> Message:
        """
        Gửi gói tin STATUS trực tiếp tới mọi peer kết nối trực tiếp.
        Nếu truyền env có phương thức send(to_peer, msg), tự động gửi qua env.
        """
        status_msg = self.build_status_message()
        target_peers = list(peers) if peers is not None else list(getattr(env, "peers", []))
        if env is not None and hasattr(env, "send") and callable(env.send):
            for peer_id in sorted(target_peers):
                env.send(peer_id, status_msg)
        return status_msg

    def handle_status(
        self,
        from_peer: str,
        payload: Mapping[str, Any] | Any,
        env: Any = None,
    ) -> Message | None:
        """
        Xử lý gói tin STATUS nhận từ from_peer:
        - Lưu thông tin (height, last_hash) của peer.
        - Nếu peer có height lớn hơn chiều cao finalize hiện tại của node:
          tạo và gửi gói GET_BLOCKS(from_height = local_height + 1, to_height = peer_height)
          trực tiếp cho from_peer.
        """
        if isinstance(payload, Mapping):
            peer_height = int(payload.get("height", 0))
            peer_hash = str(payload.get("last_hash", payload.get("block_hash", "")))
        else:
            peer_height = int(getattr(payload, "height", 0))
            peer_hash = str(getattr(payload, "last_hash", ""))

        self.peer_status[from_peer] = {
            "height": peer_height,
            "last_hash": peer_hash,
        }

        local_height = self.ledger.latest_height
        if peer_height > local_height:
            req_msg = make_get_blocks_message(
                origin=self.node_id,
                from_height=local_height + 1,
                to_height=peer_height,
            )
            if env is not None and hasattr(env, "send") and callable(env.send):
                env.send(from_peer, req_msg)
            return req_msg

        return None

    def handle_get_blocks(
        self,
        from_peer: str,
        payload: Mapping[str, Any] | Any,
        env: Any = None,
    ) -> Message | None:
        """
        Xử lý gói tin GET_BLOCKS nhận từ một peer bị tụt lại:
        - Trích xuất đoạn chiều cao [from_height, to_height].
        - Lấy các cặp (Block, CommitCertificate) đã finalize trong Ledger.
        - Đóng gói vào gói tin BLOCKS và gửi trực tiếp lại cho from_peer.
        """
        if isinstance(payload, Mapping):
            from_h = int(payload.get("from_height", payload.get("from", 1)))
            to_h = int(payload.get("to_height", payload.get("to", self.ledger.latest_height)))
        else:
            from_h = int(getattr(payload, "from_height", 1))
            to_h = int(getattr(payload, "to_height", self.ledger.latest_height))

        from_h = max(1, from_h)
        to_h = min(self.ledger.latest_height, to_h)
        if from_h > to_h:
            return None

        ledger_entries = self.ledger.get_range(from_h, to_h)
        valid_pairs: list[tuple[Block, CommitCertificate]] = [
            (entry.block, entry.certificate)
            for entry in ledger_entries
            if entry.certificate is not None
        ]
        if not valid_pairs:
            return None

        resp_msg = make_blocks_message(origin=self.node_id, entries=valid_pairs)
        if env is not None and hasattr(env, "send") and callable(env.send):
            env.send(from_peer, resp_msg)
        return resp_msg

    def handle_blocks(
        self,
        from_peer: str,
        payload: Mapping[str, Any] | Sequence[Any],
        on_block_finalized: Callable[[Block, CommitCertificate, State], None] | None = None,
    ) -> tuple[bool, str | None, list[Block]]:
        """
        Xử lý gói tin BLOCKS nhận từ peer khi đồng bộ:
        - Duyệt các cặp (Block, CommitCertificate) theo thứ tự chiều cao tăng dần.
        - Bỏ qua các khối có height <= latest_height (đã finalize từ trước).
        - Tự kiểm tra toàn diện từng khối:
          1) Kiểm tra Header, Body, tx_root, state_hash bằng validate_block().
          2) Kiểm tra CommitCertificate đủ 7 precommit hợp lệ và nối vào Ledger qua ledger.append().
          3) Áp dụng các giao dịch vào self.state và xóa giao dịch khỏi self.tx_pool.
        - Trả về (ok, reason, danh_sách_khối_mới_đã_áp_dụng).
        """
        if not self.validator_pubkeys or self.account_pubkeys is None:
            return False, BAD_SIGNATURE, []
        try:
            pairs = self._extract_block_cert_pairs(payload)
        except (KeyError, TypeError, ValueError, AttributeError):
            return False, BAD_SIGNATURE, []
        # Sắp xếp các khối theo chiều cao tăng dần để áp dụng tuần tự
        pairs.sort(key=lambda item: item[0].height)

        applied_blocks: list[Block] = []

        for block, cert in pairs:
            # Bỏ qua khối mà node đã có trong sổ cái
            if block.height <= self.ledger.latest_height:
                continue

            # Khối đồng bộ phải nối tiếp ngay sau khối mới nhất trong sổ cái
            if block.height != self.ledger.latest_height + 1:
                return False, BAD_PARENT, applied_blocks

            # Bước 1: Kiểm tra tính hợp lệ của Block (Header + thực thi Body trên state hiện tại)
            ok_blk, blk_reason = validate_block(
                block=block,
                parent_block_or_header=self.ledger.latest(),
                parent_state=self.state,
                validator_pubkeys=self.validator_pubkeys,
                account_pubkeys=self.account_pubkeys,
                chain_id=self.chain_id,
                expected_round=None,
                max_text_chars=self.max_text_chars,
                max_tx_bytes=self.max_tx_bytes,
                max_block_bytes=self.max_block_bytes,
            )
            if not ok_blk:
                return False, blk_reason, applied_blocks

            # Bước 2: Kiểm tra chứng nhận CommitCertificate và ghi vào Ledger
            ok_ledger, ledger_reason = self.ledger.append(
                block=block,
                certificate=cert,
                validator_pubkeys=self.validator_pubkeys,
                quorum=self.quorum,
            )
            if not ok_ledger:
                return False, ledger_reason, applied_blocks

            # Bước 3: Cập nhật State chính thức của node
            new_state, exec_reason = apply_block(
                state=self.state,
                block_or_txs=block,
                account_pubkeys=self.account_pubkeys,
                chain_id=self.chain_id,
                max_text_chars=self.max_text_chars,
                max_tx_bytes=self.max_tx_bytes,
                max_block_bytes=self.max_block_bytes,
                dry_run=False,
                verify_commitments=True,
                mutate_in_place=True,
            )
            if new_state is None:
                return False, exec_reason, applied_blocks

            # Bước 4: Dọn các giao dịch đã vào khối khỏi TxPool
            if self.tx_pool is not None:
                self.tx_pool.remove_finalized(block.transactions, state=self.state)

            applied_blocks.append(block)

            if on_block_finalized is not None:
                on_block_finalized(block, cert, self.state)

        return True, None, applied_blocks

    def request_votes(
        self,
        height: int,
        round_num: int,
        env: Any = None,
        peers: Sequence[str] | None = None,
    ) -> Message:
        """
        Gửi gói tin GET_VOTES(height, round) tới các peer khi node bị kẹt ở một round quá lâu.
        """
        msg = make_get_votes_message(origin=self.node_id, height=height, round_num=round_num)
        target_peers = list(peers) if peers is not None else list(getattr(env, "peers", []))
        if env is not None and hasattr(env, "send") and callable(env.send):
            for peer_id in sorted(target_peers):
                env.send(peer_id, msg)
        return msg

    def handle_get_votes(
        self,
        from_peer: str,
        payload: Mapping[str, Any] | Any,
        votes_provider: Callable[[int, int], Sequence[Vote]] | Sequence[Vote] | None = None,
        env: Any = None,
    ) -> Message | None:
        """
        Xử lý gói tin GET_VOTES(height, round):
        Lấy danh sách các phiếu bầu hợp lệ đã biết của (height, round) từ votes_provider
        và gửi gói VOTES trả lại cho from_peer.
        """
        if isinstance(payload, Mapping):
            height = int(payload.get("height", 0))
            round_num = int(payload.get("round", 0))
        else:
            height = int(getattr(payload, "height", 0))
            round_num = int(getattr(payload, "round", 0))

        votes: list[Vote] = []
        if callable(votes_provider):
            votes = list(votes_provider(height, round_num))
        elif isinstance(votes_provider, Sequence):
            votes = [v for v in votes_provider if v.height == height and v.round == round_num]

        if not votes:
            return None

        resp_msg = make_votes_message(
            origin=self.node_id,
            height=height,
            round_num=round_num,
            votes=votes,
        )
        if env is not None and hasattr(env, "send") and callable(env.send):
            env.send(from_peer, resp_msg)
        return resp_msg

    def handle_votes(
        self,
        from_peer: str,
        payload: Mapping[str, Any] | Sequence[Vote],
        on_valid_vote: Callable[[Vote], None] | None = None,
        current_height: int | None = None,
        future_height_window: int = 5,
    ) -> tuple[bool, str | None, list[Vote]]:
        """
        Xử lý gói tin VOTES nhận từ peer:
        Kiểm tra chữ ký và tính hợp lệ của từng phiếu bầu qua validate_vote().
        Trả về (True, None, valid_votes) hoặc (False, reason, valid_votes) nếu gặp phiếu sai.
        """
        if not self.validator_pubkeys:
            return False, BAD_SIGNATURE, []
        if isinstance(payload, Mapping):
            raw_votes = payload.get("votes", [])
        elif isinstance(payload, Sequence):
            raw_votes = payload
        else:
            return False, BAD_SIGNATURE, []

        valid_votes: list[Vote] = []
        for item in raw_votes:
            try:
                vote = item if isinstance(item, Vote) else Vote.from_dict(item)
            except (KeyError, TypeError, ValueError, AttributeError):
                return False, BAD_SIGNATURE, valid_votes
            ok, reason = validate_vote(
                vote=vote,
                validator_pubkeys=self.validator_pubkeys,
                chain_id=self.chain_id,
                current_height=current_height,
                future_height_window=future_height_window,
            )
            if not ok:
                return False, reason, valid_votes
            valid_votes.append(vote)
            if on_valid_vote is not None:
                on_valid_vote(vote)

        return True, None, valid_votes

    @staticmethod
    def _extract_block_cert_pairs(
        payload: Mapping[str, Any] | Sequence[Any],
    ) -> list[tuple[Block, CommitCertificate]]:
        """Chuẩn hóa dữ liệu đầu vào của gói BLOCKS về danh sách tuple (Block, CommitCertificate)."""
        pairs: list[tuple[Block, CommitCertificate]] = []
        if isinstance(payload, Mapping):
            if "entries" in payload:
                for entry in payload["entries"]:
                    if isinstance(entry, tuple) and len(entry) == 2:
                        pairs.append((entry[0], entry[1]))
                    elif isinstance(entry, Mapping):
                        blk = entry["block"] if isinstance(entry["block"], Block) else Block.from_dict(entry["block"])
                        cert = (
                            entry["certificate"]
                            if isinstance(entry["certificate"], CommitCertificate)
                            else CommitCertificate.from_dict(entry["certificate"])
                        )
                        pairs.append((blk, cert))
            elif "blocks" in payload and "certificates" in payload:
                for b_raw, c_raw in zip(payload["blocks"], payload["certificates"]):
                    blk = b_raw if isinstance(b_raw, Block) else Block.from_dict(b_raw)
                    cert = c_raw if isinstance(c_raw, CommitCertificate) else CommitCertificate.from_dict(c_raw)
                    pairs.append((blk, cert))
        elif isinstance(payload, Sequence):
            for item in payload:
                if isinstance(item, tuple) and len(item) == 2:
                    pairs.append((item[0], item[1]))
                elif hasattr(item, "block") and hasattr(item, "certificate") and item.certificate is not None:
                    pairs.append((item.block, item.certificate))
                elif isinstance(item, Mapping):
                    blk = item["block"] if isinstance(item["block"], Block) else Block.from_dict(item["block"])
                    cert = (
                        item["certificate"]
                        if isinstance(item["certificate"], CommitCertificate)
                        else CommitCertificate.from_dict(item["certificate"])
                    )
                    pairs.append((blk, cert))
        else:
            raise ValueError('Payload BLOCKS phải là danh sách hoặc object')
        if isinstance(payload, Mapping) and 'blocks' in payload and 'certificates' in payload:
            if len(payload['blocks']) != len(payload['certificates']):
                raise ValueError('Số block và certificate không khớp')
        if any(not isinstance(block, Block) or not isinstance(cert, CommitCertificate) for block, cert in pairs):
            raise ValueError('BLOCKS cần block và certificate đầy đủ')
        return pairs
