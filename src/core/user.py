"""
Định nghĩa lớp User (người dùng gửi tin nhắn chat) và các hàm khởi tạo
sổ tài khoản (account -> khóa công khai) xác định từ seed.
"""

from __future__ import annotations

from collections.abc import Sequence

from src.core.transaction import DEFAULT_CHAIN_ID, Transaction
from src.crypto.domain import ROLE_USER
from src.crypto.signing import (
    PrivateKeyBytes,
    PublicKeyBytes,
    derive_keypair,
)

# Danh sách 5 tài khoản người dùng mặc định theo config/workload.json
DEFAULT_ACCOUNTS: tuple[str, ...] = ("alice", "bob", "carol", "dave", "erin")


class User:
    """
    Lớp biểu diễn người dùng cuối trong ứng dụng Chat Chain:
    - Lưu tên tài khoản (account), cặp khóa Ed25519 (private_key, public_key),
      và bộ đếm số thứ tự tin nhắn (nonce, bắt đầu từ 0 và tăng lên 1 ở tin đầu tiên).
    - Cung cấp hàm make_message(text) để tạo và ký giao dịch chat hợp lệ.
    """

    def __init__(
        self,
        account: str,
        private_key: bytes | str | None = None,
        public_key: bytes | str | None = None,
        nonce: int = 0,
        chain_id: str = DEFAULT_CHAIN_ID,
        seed: int | str | bytes | None = None,
    ) -> None:
        self.account: str = account
        self.chain_id: str = chain_id
        self.nonce: int = nonce

        if private_key is None and seed is not None:
            sk, pk = derive_keypair(seed, ROLE_USER, account)
            self.private_key: PrivateKeyBytes = sk
            self.public_key: PublicKeyBytes = pk
        elif private_key is not None:
            raw_sk = bytes.fromhex(private_key) if isinstance(private_key, str) else bytes(private_key)
            self.private_key = PrivateKeyBytes(raw_sk)
            if public_key is not None:
                raw_pk = bytes.fromhex(public_key) if isinstance(public_key, str) else bytes(public_key)
                self.public_key = PublicKeyBytes(raw_pk)
            else:
                self.public_key = self.private_key.public_key()
        else:
            raise ValueError("Cần cung cấp private_key hoặc seed khi khởi tạo User")

    @property
    def name(self) -> str:
        """Bí danh cho thuộc tính account."""
        return self.account

    @property
    def sk(self) -> PrivateKeyBytes:
        """Bí danh cho khóa bí mật private_key."""
        return self.private_key

    @property
    def pk(self) -> PublicKeyBytes:
        """Bí danh cho khóa công khai public_key."""
        return self.public_key

    @classmethod
    def from_seed(
        cls,
        seed: int | str | bytes,
        account: str,
        chain_id: str = DEFAULT_CHAIN_ID,
        nonce: int = 0,
    ) -> User:
        """Khởi tạo đối tượng User trực tiếp từ seed và tên tài khoản."""
        sk, pk = derive_keypair(seed, ROLE_USER, account)
        return cls(
            account=account,
            private_key=sk,
            public_key=pk,
            nonce=nonce,
            chain_id=chain_id,
        )

    def make_message(
        self,
        text: str,
        nonce: int | None = None,
        chain_id: str | None = None,
        key: str | None = None,
    ) -> Transaction:
        """
        Tạo và ký một tin nhắn chat (Transaction) mới:
        - Nếu không truyền nonce: tự động tăng bộ đếm self.nonce thêm 1 (bắt đầu từ 1).
        - Nếu không truyền key: tự động tạo key chuẩn '<account>/chat/<nonce>'.
        - Ký giao dịch bằng khóa bí mật của người dùng với domain TX.
        """
        if nonce is None:
            self.nonce += 1
            tx_nonce = self.nonce
        else:
            tx_nonce = nonce

        tx_key = key if key is not None else f"{self.account}/chat/{tx_nonce}"
        target_chain = chain_id if chain_id is not None else self.chain_id

        tx = Transaction(
            account=self.account,
            nonce=tx_nonce,
            key=tx_key,
            value=text,
        )
        tx.sign(self.private_key, chain_id=target_chain)
        return tx


def create_account_book(
    seed: int | str | bytes,
    accounts: Sequence[str] = DEFAULT_ACCOUNTS,
) -> dict[str, PublicKeyBytes]:
    """
    Tạo sổ tài khoản cố định (account -> khóa công khai Ed25519) từ seed.
    Sổ tài khoản này thuộc cấu hình khởi tạo của mạng, không nằm trong State.
    """
    return {acc: derive_keypair(seed, ROLE_USER, acc)[1] for acc in accounts}


def create_users(
    seed: int | str | bytes,
    accounts: Sequence[str] = DEFAULT_ACCOUNTS,
    chain_id: str = DEFAULT_CHAIN_ID,
) -> dict[str, User]:
    """Tạo từ điển các đối tượng User (account -> User) từ seed."""
    return {acc: User.from_seed(seed, acc, chain_id=chain_id) for acc in accounts}


# Các bí danh hàm để tương thích với nhiều cách gọi khác nhau
build_account_book = create_account_book
derive_account_book = create_account_book
make_account_book = create_account_book


def schedule_workload(sim, config: dict, root_path) -> None:
    """Lên lịch TX ký thật; client đi qua inject_message, không can thiệp state node."""
    import json
    from pathlib import Path
    from src.core.wire import make_tx_message

    workload = json.loads((Path(root_path) / config['workload_file']).read_text(encoding='utf-8'))
    accounts = workload['accounts']
    texts = workload['messages']
    every_ms = workload['every_ms']
    if not accounts or len(set(accounts)) != len(accounts) or not texts:
        raise ValueError('Workload cần tài khoản không trùng và câu mẫu không rỗng')
    if type(every_ms) is not int or every_ms <= 0:
        raise ValueError('every_ms phải là số nguyên dương')
    mode = config.get('workload_mode', workload.get('mode', 'normal'))
    if mode not in {'normal', 'burst', 'replay_alice'}:
        raise ValueError('Chế độ workload không được hỗ trợ')
    if mode == 'replay_alice' and 'alice' not in accounts:
        raise ValueError('Workload replay_alice cần tài khoản alice')
    users = create_users(config['seed'], accounts, config['chain_id'])
    rng = sim.rng.child('workload')
    node_ids = list(sim.nodes)
    if not node_ids:
        raise ValueError('Đăng ký node trước khi lập lịch workload')
    node_ids.sort(key=lambda name: (0, int(name[1:])) if name.startswith('N') and name[1:].isdigit() else (1, name))
    stop_ms = config['stop']['max_virtual_time_ms']
    replayed = False

    def emit():
        nonlocal replayed
        account = 'alice' if mode == 'replay_alice' and not replayed else rng.choice(accounts)
        tx = users[account].make_message(rng.choice(texts))
        receiver = rng.choice(node_ids)
        sim.inject_message(receiver, make_tx_message(receiver, tx))
        if mode == 'replay_alice' and not replayed:
            replayed = True
            # Đổi origin để node kiểm tra lại cùng TX, không bị dedup wire che lỗi replay.
            replay_to = node_ids[(node_ids.index(receiver) + 1) % len(node_ids)]
            at_ms = sim.clock.now() + every_ms
            if at_ms <= stop_ms:
                sim.schedule(at_ms, 'client-replay', sim.inject_message,
                             replay_to, make_tx_message(replay_to, tx))

    for at_ms in range(every_ms, stop_ms + 1, every_ms):
        sim.schedule(at_ms, 'client-tx', emit)
    if mode == 'burst':
        burst = workload['burst']
        for key in ('at_ms', 'count', 'within_ms'):
            if type(burst[key]) is not int or burst[key] < 0:
                raise ValueError('Tham số burst phải là số nguyên không âm')
        for _ in range(burst['count']):
            at_ms = burst['at_ms'] + rng.randint(0, burst['within_ms'])
            if at_ms <= stop_ms:
                sim.schedule(at_ms, 'client-burst', emit)
