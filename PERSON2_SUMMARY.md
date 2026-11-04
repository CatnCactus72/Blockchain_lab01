# Tài liệu Tổng hợp Công việc của Người 2 — Luật của Chuỗi (Chain Rules)

Tài liệu này tổng hợp toàn bộ kết quả cài đặt cho nhiệm vụ của **Người 2** trong `mission.txt`, bao gồm:
1. Danh sách các file đã thực hiện thay đổi / cài đặt.
2. Cấu trúc dữ liệu, lớp (class), tên hàm (function/method), tên biến/thuộc tính và hằng số trong từng file.
3. Thứ tự kiểm tra hợp lệ và mã lý do từ chối (`reason`) để Người 1 và Người 3 tích hợp.

---

## 1. Danh sách các file đã thực hiện thay đổi

| Nhóm | Đường dẫn file | Mô tả nhiệm vụ đã thực hiện |
|---|---|---|
| Phụ thuộc | `requirements.txt` | Khai báo thư viện `cryptography` (Ed25519). |
| Mật mã (`src/crypto/`) | `src/crypto/domain.py` | Định nghĩa các hằng miền chữ ký (`TX`, `HEADER`, `PROPOSAL`, `VOTE`), nhãn băm (`BLOCK`, `MSG`, `STATE`, `TXROOT`, `TXID`, `KEY`, `GENESIS`), vai trò sinh khóa (`ROLE_VALIDATOR`, `ROLE_USER`) và mã lỗi mật mã. |
| Mật mã (`src/crypto/`) | `src/crypto/encoding.py` | Cài đặt mã hóa chuẩn xác định (`enc_uint`, `enc_u32`, `enc_bytes`, `enc_str` NFC, `enc_list`, `enc_map`, `enc_nil`) và bộ hàm giải mã tương ứng (`dec_uint`, `dec_int`, `dec_bytes`, `dec_str`, `dec_list`, `dec_map`). |
| Mật mã (`src/crypto/`) | `src/crypto/hashing.py` | Cài đặt lớp `HashHex`, hàm băm `sha256`, `sha256_hex`, và các hàm tính định danh: `tx_id`, `state_hash`, `tx_root`, `block_hash`, `genesis_hash`, `msg_id`. |
| Mật mã (`src/crypto/`) | `src/crypto/signing.py` | Cài đặt sinh khóa xác định từ seed `derive_keypair`, ký tách miền `sign`, xác minh chữ ký `verify` (phân biệt `WRONG_DOMAIN` và `BAD_SIGNATURE`), cùng hàm tạo sổ khóa validator. |
| Dữ liệu lõi (`src/core/`) | `src/core/user.py` | Cài đặt lớp `User` (`make_message`), tạo sổ tài khoản `create_account_book` và `create_users` từ seed. |
| Dữ liệu lõi (`src/core/`) | `src/core/transaction.py` | Cài đặt lớp `Transaction`: `signing_fields()`, `tx_id()`, `sign()`, `verify_signature()`, `encode()`/`decode()`, `check_key_format()`, `check_limits()`. |
| Dữ liệu lõi (`src/core/`) | `src/core/header.py` | Cài đặt lớp `Header`: `signing_fields()`, `encode_without_signature()`, `block_hash()`, `sign()`, `verify_signature()`, `encode()`/`decode()`. |
| Dữ liệu lõi (`src/core/`) | `src/core/block.py` | Cài đặt lớp `Block` (`Header` + `Body`), `body_size()`, `compute_tx_root()`, `Block.genesis()` / `make_genesis_block()`. |
| Dữ liệu lõi (`src/core/`) | `src/core/vote.py` | Cài đặt lớp `Vote` (`PREVOTE`/`PRECOMMIT`, hỗ trợ bầu `NIL`) và `CommitCertificate` (`verify()` kiểm tra đủ quorum 7 precommit hợp lệ, phát hiện `CONFLICTING_VOTE` từ cùng một validator trước khi lọc theo `block_hash`/`round`, và đối chiếu `vote.round == self.round` khi `self.round != 0`). |
| Dữ liệu lõi (`src/core/`) | `src/core/proposal.py` | Cài đặt lớp `Proposal` (hỗ trợ cả khối mới `pol_round = -1` và đề xuất lại khối đã khóa `pol_round >= 0`), kết nối với `src/node/proposer.py`, phân biệt chính xác `BAD_SIGNATURE` (proposal của đúng proposer bị hỏng chữ ký nhưng đi qua hop trung gian) với `NOT_PROPOSER` (khi `proposer_id != exp_proposer` hoặc `sender_id` tự ký `proposal_sig` bằng khóa riêng). |
| Dữ liệu lõi (`src/core/`) | `src/core/wire.py` | Định nghĩa 14 loại `kind` gói tin mạng, lớp `Message` (bất biến, tính `msg_id`), lớp `Envelope` (thay đổi theo hop), mã hóa/giải mã payload cho từng `kind`. |
| Thực thi (`src/execution/`) | `src/execution/state.py` | Cài đặt lớp `State`: lưu map key-value, bộ đếm nonce đã áp dụng theo tài khoản, nhân bản `clone()`, và tính `state_hash()` độc lập thứ tự chèn. |
| Thực thi (`src/execution/`) | `src/execution/executor.py` | Cài đặt `apply_tx`, `apply_block` và `trial_execute_transactions` (chế độ thực thi thử cho proposer). |
| Thành phần Node (`src/node/`) | `src/node/proposer.py` | Cài đặt các hàm chọn proposer `(height + round) mod n` (`proposer_index`, `get_proposer`, `expected_proposer_id`, `select_proposer`), kiểm tra proposer (`is_proposer`, `is_expected_proposer`), chuẩn hóa định danh (`normalize_validator_id`) và lớp `ProposerSelector`. |
| Thành phần Node (`src/node/`) | `src/node/validation.py` | Cài đặt đầy đủ 21 hằng mã lý do `reason` và các hàm kiểm tra `validate_tx`, `validate_header`, `validate_proposal`, `validate_body`, `validate_block`, `validate_vote`, `validate_commit_certificate`. |
| Thành phần Node (`src/node/`) | `src/node/tx_pool.py` | Cài đặt lớp `TxPool`: nhận giao dịch sau kiểm tra hợp lệ, khử trùng theo `tx_id` và `(account, nonce)`, chọn giao dịch dựng khối `select_for_block()`, xóa giao dịch khi finalize `remove_finalized()`. |
| Thành phần Node (`src/node/`) | `src/node/ledger.py` | Cài đặt lớp `Ledger` và `LedgerEntry`: lưu chuỗi khối đã finalize kèm `CommitCertificate`; `append()`, `get()`, `latest()`, `get_range()`. |
| Thành phần Node (`src/node/`) | `src/node/sync.py` | Cài đặt lớp `SyncManager`: gửi `STATUS`, xử lý `STATUS`, `GET_BLOCKS`/`BLOCKS` (tự kiểm tra certificate và thực thi khối), `GET_VOTES`/`VOTES`. |
| Thành phần Node (`src/node/`) | `src/node/query.py` | Cài đặt lớp `ChatQuery`: giao diện đọc `get_latest(k)`, `get_block(height)`, `get_chat_messages()`, `get_state_entries()` (chỉ trả dữ liệu đã finalize). |
| Công cụ (`tests/tools/`) | `tests/tools/show_chat.py` | Công cụ CLI hiển thị kênh chat đã finalize của một node từ file log (`--log`, `--node`, `--last`, `--height`). |
| Công cụ (`tests/tools/`) | `tests/tools/show_state.py` | Công cụ CLI hiển thị state đã finalize của một tài khoản hoặc toàn bộ node (`--log`, `--node`, `--account`). |
| Kiểm thử đơn vị (`tests/unit/`) | `tests/unit/test_crypto.py` | Unit test cho mã hóa chuẩn, hàm băm, sinh khóa xác định, ký và xác minh chữ ký (`WRONG_DOMAIN`, `BAD_SIGNATURE`). |
| Kiểm thử đơn vị (`tests/unit/`) | `tests/unit/test_state.py` | Unit test cho `State` và `executor` (`NOT_OWNER`, `BAD_KEY`, `BAD_NONCE`, `REPLAYED_TX`, `UNKNOWN_ACCOUNT`, tính độc lập thứ tự chèn của `state_hash`). |
| Kiểm thử đơn vị (`tests/unit/`) | `tests/unit/test_block_validation.py` | Unit test cho kiểm tra block, header, proposal, commit certificate, proposer selector, ledger, sync và query (`BAD_PARENT`, `BAD_TX_ROOT`, `BAD_STATE_HASH`, `NOT_PROPOSER`, `BAD_TIMESTAMP`, `BAD_SIGNATURE`, `WRONG_DOMAIN`, `WRONG_CHAIN`, `FUTURE_HEIGHT`, `CONFLICTING_VOTE`). |
| Kiểm thử đơn vị (`tests/unit/`) | `tests/unit/test_limits.py` | Unit test cho giới hạn 200 ký tự NFC (tiếng Việt, emoji), 1024 byte mỗi tx (`TX_TOO_LONG`), 4096 byte mỗi block (`BLOCK_TOO_LARGE`). |

---

## 2. Chi tiết cấu trúc, cách đặt tên biến và hàm theo từng module

### 2.1 Tầng Mật mã (`src/crypto/`)

#### `src/crypto/domain.py`
- **Hằng miền ký (`SIGNING_DOMAINS`)**:
  - `TX = DOMAIN_TX = "TX"`
  - `HEADER = DOMAIN_HEADER = "HEADER"`
  - `PROPOSAL = DOMAIN_PROPOSAL = "PROPOSAL"`
  - `VOTE = DOMAIN_VOTE = "VOTE"`
- **Hằng nhãn băm (`HASH_TAGS`)**:
  - `BLOCK = TAG_BLOCK = "BLOCK"`
  - `MSG = TAG_MSG = "MSG"`
  - `STATE = TAG_STATE = "STATE"`
  - `TXROOT = TAG_TXROOT = "TXROOT"`
  - `TXID = TAG_TXID = "TXID"`
  - `KEY = TAG_KEY = "KEY"`
  - `GENESIS = TAG_GENESIS = "GENESIS"`
- **Hằng vai trò sinh khóa**:
  - `ROLE_VALIDATOR = "validator"`, `ROLE_USER = "user"`
- **Hằng mã lỗi**:
  - `BAD_SIGNATURE = "BAD_SIGNATURE"`, `WRONG_DOMAIN = "WRONG_DOMAIN"`, `WRONG_CHAIN = "WRONG_CHAIN"`

#### `src/crypto/encoding.py`
- **Hằng số**:
  - `NIL_BYTES = b"\x00" * 32` (32 byte 0 đại diện cho `NIL`).
- **Các hàm chuẩn hóa & mã hóa**:
  - `normalize_nfc(text: str) -> str`: chuẩn hóa chuỗi Unicode về NFC.
  - `count_nfc_chars(text: str) -> int`: đếm số code point sau chuẩn hóa NFC.
  - `enc_uint(value: int) -> bytes` (bí danh `enc_u64`, `enc_int`): mã hóa số nguyên 64-bit big-endian (8 byte cố định; hỗ trợ `pol_round = -1` qua bù 2 64-bit; từ chối `float` và `bool`).
  - `enc_u32(value: int) -> bytes`: mã hóa số nguyên không dấu 32-bit big-endian (4 byte).
  - `enc_bytes(data: bytes | None) -> bytes`: tiền tố độ dài `u32` + nội dung (hoặc `NIL_BYTES` nếu `None`).
  - `enc_str(text: str) -> bytes`: chuẩn hóa NFC -> UTF-8 -> `enc_bytes`.
  - `enc_list(items: Sequence[Any], item_encoder=None) -> bytes`: `u32` số phần tử + các phần tử nối tiếp theo thứ tự.
  - `enc_map(mapping: Mapping[Any, Any], value_encoder=None) -> bytes`: sắp xếp các cặp theo mảng byte của key rồi mã hóa.
  - `enc_nil() -> bytes`: trả về `NIL_BYTES`.
- **Các hàm giải mã tương ứng**:
  - `dec_u32(data, offset=0) -> tuple[int, int]`
  - `dec_uint(data, offset=0) -> tuple[int, int]`
  - `dec_int(data, offset=0) -> tuple[int, int]`
  - `dec_bytes(data, offset=0) -> tuple[bytes, int]`
  - `dec_str(data, offset=0) -> tuple[str, int]`
  - `dec_list(data, item_decoder=dec_str, offset=0) -> tuple[list, int]`
  - `dec_map(data, offset=0, key_decoder=dec_str, value_decoder=dec_str) -> tuple[dict, int]`

#### `src/crypto/hashing.py`
- **Lớp `HashHex(str)`**:
  - Kế thừa trực tiếp từ `str` (chuỗi hex chữ thường 64 ký tự), đồng thời hỗ trợ `.hex() -> str`, `.digest() -> bytes`, `bytes(h)` và `h()` (cho phép truy cập như thuộc tính hoặc gọi như phương thức).
- **Các hàm băm**:
  - `sha256(*parts) -> bytes`: trả về 32 byte digest SHA-256.
  - `sha256_hex(*parts) -> HashHex`: trả về chuỗi hex 64 ký tự.
  - `tx_id(account_or_tx, nonce=None, key=None, value=None) -> HashHex`: tính `SHA256("TXID" ‖ account ‖ nonce ‖ enc(key) ‖ enc(value))`. Nhận cả đối tượng `Transaction` hoặc 4 tham số rời.
  - `state_hash(state) -> HashHex`: tính `SHA256("STATE" ‖ enc_map(state))`. Nhận cả `State` hoặc `dict`.
  - `tx_root(tx_items) -> HashHex`: tính `SHA256("TXROOT" ‖ enc_list(tx_id...))`. Nhận danh sách `tx_id` hoặc danh sách `Transaction`.
  - `genesis_hash(chain_id="lab01-chain") -> HashHex`: tính `SHA256("GENESIS" ‖ chain_id)`.
  - `block_hash(header_or_block) -> HashHex`: tính `SHA256("BLOCK" ‖ enc(header không gồm signature))` (hoặc `genesis_hash` cho khối Genesis ở height 0).
  - `msg_id(kind_or_msg, origin=None, payload=None) -> HashHex`: tính `SHA256("MSG" ‖ kind ‖ origin ‖ enc(payload))`.

#### `src/crypto/signing.py`
- **Lớp khóa `PrivateKeyBytes(bytes)` và `PublicKeyBytes(bytes)`**:
  - Kế thừa từ `bytes` (dài 32 byte) nên so sánh `==` xác định, hỗ trợ `.hex()`, `.sign()`, `.verify()`, `.public_key()`.
- **Các hàm**:
  - `derive_keypair(seed, role, entity_id) -> tuple[PrivateKeyBytes, PublicKeyBytes]`: tính `key_seed = SHA256("KEY" ‖ seed ‖ role ‖ id)`.
  - `build_sign_bytes(domain, chain_id, fields) -> bytes`: tạo `enc(domain) ‖ enc(chain_id) ‖ enc(fields)`.
  - `sign(sk, domain, chain_id, fields) -> bytes`: ký Ed25519 trả về 64 byte.
  - `verify(pk, domain, chain_id, fields, signature) -> tuple[bool, str | None]`: xác minh chữ ký; nếu thất bại sẽ thử lại với các domain còn lại trong `SIGNING_DOMAINS` để trả về `(False, "WRONG_DOMAIN")` hoặc `(False, "BAD_SIGNATURE")`.
  - `derive_validator_keybook(seed, n=10) -> dict[str, PublicKeyBytes]`: tạo sổ khóa công khai cho `N0..N9`.
  - `derive_validator_keypairs(seed, n=10) -> dict[str, tuple[PrivateKeyBytes, PublicKeyBytes]]`: tạo cặp khóa cho `N0..N9`.

---

### 2.2 Tầng Đối tượng Dữ liệu (`src/core/`)

#### `src/core/user.py`
- **Hằng số**: `DEFAULT_ACCOUNTS = ("alice", "bob", "carol", "dave", "erin")`.
- **Lớp `User`**:
  - Thuộc tính: `account: str` (bí danh `.name`), `private_key: PrivateKeyBytes` (bí danh `.sk`), `public_key: PublicKeyBytes` (bí danh `.pk`), `nonce: int`, `chain_id: str`.
  - Phương thức:
    - `User.from_seed(seed, account, chain_id="lab01-chain", nonce=0) -> User`
    - `make_message(text, nonce=None, chain_id=None, key=None) -> Transaction`: tăng `self.nonce` thêm 1 (nếu không truyền `nonce`), đặt `key = f"{account}/chat/{nonce}"`, ký trên domain `TX` và trả về `Transaction`.
- **Hàm**:
  - `create_account_book(seed, accounts=DEFAULT_ACCOUNTS) -> dict[str, PublicKeyBytes]` (bí danh `build_account_book`, `derive_account_book`).
  - `create_users(seed, accounts=DEFAULT_ACCOUNTS, chain_id="lab01-chain") -> dict[str, User]`.

#### `src/core/transaction.py`
- **Hằng số**: `MAX_TEXT_CHARS = 200`, `MAX_TX_BYTES = 1024`, `DEFAULT_CHAIN_ID = "lab01-chain"`.
- **Lớp `Transaction`**:
  - Trường dữ liệu: `account: str`, `nonce: int`, `key: str`, `value: str`, `signature: bytes = b""`.
  - Phương thức:
    - `signing_fields() -> tuple[str, int, str, str]`: trả về `(account, nonce, key, value)`.
    - `tx_id() -> HashHex`
    - `sign(private_key, chain_id="lab01-chain") -> bytes`
    - `verify_signature(public_key, chain_id="lab01-chain") -> tuple[bool, str | None]`
    - `encode() -> bytes` / `Transaction.decode(data, offset=0)` / `Transaction.from_bytes(data)`
    - `char_count() -> int`: số ký tự NFC của `value`.
    - `byte_size() -> int` (bí danh `encoded_size()`): tổng số byte của `encode()`.
    - `check_key_format() -> tuple[bool, str | None]`: kiểm tra `NOT_OWNER` và `BAD_KEY`.
    - `check_limits(max_text_chars=200, max_tx_bytes=1024) -> tuple[bool, str | None]`: kiểm tra `TX_TOO_LONG`.

#### `src/core/header.py`
- **Lớp `Header`**:
  - Trường dữ liệu: `chain_id: str`, `height: int`, `parent_hash: str`, `tx_root: str`, `state_hash: str`, `proposer_id: str`, `timestamp: int`, `signature: bytes = b""`.
  - Phương thức:
    - `signing_fields() -> tuple[int, str, str, str, str, int]`: trả về `(height, parent_hash, tx_root, state_hash, proposer_id, timestamp)`.
    - `encode_without_signature() -> bytes`
    - `block_hash() -> HashHex`
    - `sign(private_key) -> bytes`
    - `verify_signature(public_key, expected_chain_id=None) -> tuple[bool, str | None]`
    - `encode() -> bytes` / `Header.decode(data, offset=0)` / `Header.from_bytes(data)`

#### `src/core/block.py`
- **Hằng số**: `MAX_BLOCK_BYTES = 4096`.
- **Lớp `Block`**:
  - Trường dữ liệu: `header: Header`, `transactions: list[Transaction]` (bí danh `.body`, `.txs`).
  - Thuộc tính ủy quyền: `.chain_id`, `.height`, `.parent_hash`, `.tx_root`, `.state_hash`, `.proposer_id`, `.timestamp`.
  - Phương thức:
    - `block_hash() -> HashHex`
    - `body_size() -> int`: tổng `tx.byte_size()` của các giao dịch trong `transactions`.
    - `compute_tx_root() -> HashHex`
    - `encode_body() -> bytes` / `Block.decode_body(data, offset=0)`
    - `encode() -> bytes` / `Block.decode(data, offset=0)` / `Block.from_bytes(data)`
    - `Block.genesis(chain_id="lab01-chain") -> Block` (và hàm `make_genesis_block(chain_id="lab01-chain") -> Block`).

#### `src/core/vote.py`
- **Hằng số**: `PREVOTE = "PREVOTE"`, `PRECOMMIT = "PRECOMMIT"`, `NIL = None`, `DEFAULT_QUORUM = 7`.
- **Lớp `Vote`**:
  - Trường dữ liệu: `height: int`, `round: int`, `phase: str`, `block_hash: str | None`, `validator_id: str`, `signature: bytes = b""`.
  - Thuộc tính & phương thức:
    - `is_nil -> bool`
    - `signing_fields() -> tuple[int, int, str, str | None, str]`
    - `sign(private_key, chain_id="lab01-chain") -> bytes`
    - `verify_signature(public_key, chain_id="lab01-chain") -> tuple[bool, str | None]`
    - `encode() -> bytes` / `Vote.decode(data, offset=0)` / `Vote.from_bytes(data)`
- **Lớp `CommitCertificate`**:
  - Trường dữ liệu: `height: int`, `block_hash: str`, `votes: list[Vote]` (bí danh `.precommits`), `round: int = 0` (khởi tạo `round: int | None = None`: nếu không truyền `round` thì tự động suy từ `votes[0].round`, nếu truyền tường minh kể cả `round=0` hay `round!=0` thì giữ nguyên).
  - Phương thức:
    - `verify(validator_pubkeys=None, chain_id="lab01-chain", quorum=7, expected_height=None, expected_block_hash=None) -> tuple[bool, str | None]`: kiểm tra chữ ký từng phiếu và phát hiện phiếu mâu thuẫn (`CONFLICTING_VOTE`) từ cùng một validator trước khi lọc theo `block_hash` và `round`; đồng thời đối chiếu nghiêm ngặt `vote.round == self.round`.
    - `encode() -> bytes` / `CommitCertificate.decode(data, offset=0)` / `CommitCertificate.from_bytes(data)`
  - Hàm tiện ích: `verify_commit_certificate(...)`.

#### `src/core/proposal.py`
- **Hàm tiện ích** (nhập và tái xuất từ `src/node/proposer.py`):
  - `expected_proposer_id(height, round_num=None, n=10, validators=None, *, round=None) -> str`: tính `f"N{(height + round_num) % n}"`.
  - `is_expected_proposer(node_id, height, round_num=None, n=10, validators=None, *, round=None) -> bool`.
  - `normalize_validator_id(node_id: str | int) -> str`.
- **Lớp `Proposal`**:
  - Trường dữ liệu: `height: int`, `round: int`, `block_hash: str`, `pol_round: int`, `header: Header`, `proposal_sig: bytes = b""` (bí danh `.signature`), `proposer_id: str = ""`.
  - Phương thức:
    - `signing_fields() -> tuple[int, int, str, int]`: trả về `(height, round, block_hash, pol_round)`.
    - `sign(private_key, chain_id=None, proposer_id=None) -> bytes`
    - `verify_proposal_sig(public_key, chain_id=None) -> tuple[bool, str | None]`
    - `verify_proposer_and_sig(validator_pubkeys=None, chain_id="lab01-chain", sender_id=None, n=10, validators=None) -> tuple[bool, str | None]`: chỉ trả về `NOT_PROPOSER` khi `proposer_id` khác `exp_proposer`, hoặc `pol_round == -1` mà `header.proposer_id != exp_proposer`, hoặc khi `sender_id != exp_proposer` thực sự đã ký `proposal_sig` bằng khóa riêng của `sender_id`; giữ nguyên `BAD_SIGNATURE` (hoặc `WRONG_DOMAIN`) khi proposal của đúng proposer bị hỏng chữ ký nhưng đi qua hop trung gian.
    - `encode() -> bytes` / `Proposal.decode(data, offset=0)` / `Proposal.from_bytes(data)`

#### `src/core/wire.py`
- **Hằng số `kind`**:
  - Quản lý peer: `HELLO`, `PING`, `PONG`
  - Giao dịch: `TX`
  - Block: `BODY_REQUEST`, `BODY`
  - Đồng thuận: `PROPOSAL`, `PREVOTE`, `PRECOMMIT`
  - Đồng bộ: `STATUS`, `GET_BLOCKS`, `BLOCKS`, `GET_VOTES`, `VOTES`
  - Phân nhóm: `ALL_KINDS`, `GOSSIP_KINDS = (TX, PROPOSAL, PREVOTE, PRECOMMIT)`, `DIRECT_KINDS`.
- **Lớp `Message`**:
  - Trường dữ liệu: `kind: str`, `origin: str`, `payload: Any = None`, `signature: bytes = b""`.
  - Thuộc tính & phương thức:
    - `msg_id -> HashHex`: trả về `SHA256("MSG" ‖ kind ‖ origin ‖ enc(payload))` (hỗ trợ cả `msg.msg_id` và `msg.msg_id()`).
    - `short_id -> str`: 6 ký tự hex đầu của `msg_id`.
    - `height -> int | None`, `round -> int | None`: tự động trích xuất từ `payload` nếu có.
    - `encode_payload() -> bytes`, `encode() -> bytes`, `Message.decode(data, offset=0)`.
- **Lớp `Envelope`**:
  - Trường dữ liệu: `message: Message` (bí danh `.msg`), `from_peer: str`, `to_peer: str`, `sent_at_ms: int = 0`.
  - Phương thức: `forward(new_from_peer, new_to_peer, sent_at_ms=0) -> Envelope` (giữ nguyên `message` và `msg_id`).
- **Hàm tạo nhanh gói tin**:
  - `make_tx_message`, `make_proposal_message`, `make_vote_message`, `make_body_request_message`, `make_body_message`, `make_status_message`, `make_get_blocks_message`, `make_blocks_message`, `make_get_votes_message`, `make_votes_message`.

---

### 2.3 Tầng Thực thi (`src/execution/`)

#### `src/execution/state.py`
- **Lớp `State(Mapping[str, str])`**:
  - Thuộc tính: `.data` (`dict[str, str]`), `.nonces` (`dict[str, int]`).
  - Phương thức:
    - `get(key, default=None) -> Any`
    - `set(key, value, account=None, nonce=None) -> None`
    - `get_nonce(account) -> int` (bí danh `applied_nonce(account)`): trả về nonce đã áp dụng gần nhất (mặc định `0`).
    - `next_nonce(account) -> int`: trả về `get_nonce(account) + 1`.
    - `set_nonce(account, nonce) -> None`
    - `state_hash() -> HashHex`: tính `SHA256("STATE" ‖ enc_map(state))` độc lập thứ tự chèn.
    - `clone() -> State` (bí danh `copy()`): tạo bản sao độc lập phục vụ thực thi thử.
    - `replace_from(other_state) -> None`
    - `get_account_entries(account) -> dict[str, str]`
    - `to_dict() -> dict[str, str]`

#### `src/execution/executor.py`
- **Các hàm**:
  - `apply_tx(state, tx, account_pubkeys=None, chain_id="lab01-chain", max_text_chars=200, max_tx_bytes=1024, check_limits=True, dry_run=False) -> tuple[bool, str | None]`:
    Kiểm tra theo đúng thứ tự: `UNKNOWN_ACCOUNT` -> `BAD_SIGNATURE`/`WRONG_DOMAIN` -> `NOT_OWNER` -> `BAD_KEY` -> `TX_TOO_LONG` -> `REPLAYED_TX`/`BAD_NONCE`, sau đó ghi vào `state`.
  - `apply_block(state, block_or_txs, account_pubkeys=None, chain_id="lab01-chain", max_text_chars=200, max_tx_bytes=1024, max_block_bytes=4096, dry_run=False, verify_commitments=True, mutate_in_place=False) -> tuple[State | None, str | None]`:
    Thực thi nguyên tử danh sách giao dịch trong khối trên bản sao của `state`, kiểm tra `BLOCK_TOO_LARGE`, `BAD_TX_ROOT`, `BAD_STATE_HASH`; trả về `(new_state, None)` hoặc `(None, reason)`.
  - `trial_execute_transactions(base_state, candidate_txs, ...) -> tuple[State, list[Transaction], list[tuple[Transaction, str]]]`:
    Hỗ trợ proposer thực thi thử các giao dịch từ pool khi dựng khối mới.

---

### 2.4 Các Thành phần Lưu trữ và Kiểm tra của Node (`src/node/`)

#### `src/node/proposer.py`
- **Hằng số**: `DEFAULT_NUM_VALIDATORS = 10`.
- **Các hàm chọn và kiểm tra proposer**:
  - `normalize_validator_id(node_id: str | int) -> str`: chuẩn hóa `3 -> "N3"`, `"n3" -> "N3"`, `"N3" -> "N3"`, từ chối `bool`.
  - `proposer_index(height, round_num=None, n=10, *, round=None) -> int`: tính `(height + round) % n` (hỗ trợ truyền `n` là số nguyên hoặc danh sách validators).
  - `expected_proposer_id(height, round_num=None, n=10, validators=None, *, round=None) -> str` (bí danh `get_proposer`, `get_proposer_id`, `select_proposer`, `proposer_for`).
  - `is_expected_proposer(node_id=None, height=0, round_num=None, n=10, validators=None, *, round=None, validator_id=None, proposer_id=None) -> bool` (bí danh `is_proposer`, `check_proposer`).
- **Lớp `ProposerSelector` (bí danh `ProposerSchedule`)**:
  - Thuộc tính: `n: int`, `validators: tuple[str, ...] | None`.
  - Phương thức: `index(height, round_num=0)`, `get_proposer(height, round_num=0)` (bí danh `proposer_for`), `is_proposer(node_id, height, round_num=0)`.

#### `src/node/validation.py`
- **21 hằng mã lý do từ chối (`VALID_REASONS`)**:
  `BAD_SIGNATURE`, `WRONG_DOMAIN`, `WRONG_CHAIN`, `UNKNOWN_ACCOUNT`, `NOT_OWNER`, `BAD_KEY`, `TX_TOO_LONG`, `BAD_NONCE`, `REPLAYED_TX`, `BAD_PARENT`, `BAD_TX_ROOT`, `BAD_STATE_HASH`, `BAD_TIMESTAMP`, `BLOCK_TOO_LARGE`, `NOT_PROPOSER`, `DUPLICATE_MSG`, `DUPLICATE_VOTE`, `CONFLICTING_VOTE`, `FUTURE_HEIGHT`, `PEER_BLOCKED`, `RATE_LIMIT`.
- **Các hàm kiểm tra (mỗi hàm đều trả về `(ok: bool, reason: str | None)`)**:
  - `validate_tx(tx, state=None, account_pubkeys=None, chain_id="lab01-chain", max_text_chars=200, max_tx_bytes=1024, check_nonce=True, expected_nonce=None)`
  - `validate_header(header, parent_header_or_block=None, validator_pubkeys=None, chain_id="lab01-chain", expected_round=None, n=10, validators=None)`
  - `validate_proposal(proposal, parent_header_or_block=None, validator_pubkeys=None, chain_id="lab01-chain", sender_id=None, current_height=None, future_height_window=5, n=10, validators=None)`
  - `validate_body(header, transactions, parent_state, account_pubkeys=None, chain_id="lab01-chain", max_text_chars=200, max_tx_bytes=1024, max_block_bytes=4096)`
  - `validate_block(block, parent_block_or_header=None, parent_state=None, validator_pubkeys=None, account_pubkeys=None, chain_id="lab01-chain", expected_round=None, max_text_chars=200, max_tx_bytes=1024, max_block_bytes=4096, n=10, validators=None)`
  - `validate_vote(vote, validator_pubkeys=None, chain_id="lab01-chain", current_height=None, future_height_window=5)`
  - `validate_commit_certificate(certificate, validator_pubkeys=None, chain_id="lab01-chain", quorum=7, expected_height=None, expected_block_hash=None)`

#### `src/node/tx_pool.py`
- **Lớp `TxPool`**:
  - `add(tx, state=None, account_pubkeys=None, strict_nonce=False) -> tuple[bool, str | None]` (bí danh `add_tx`, `submit`, `put`).
  - `has_tx(tx_or_id) -> bool`, `get_tx(tx_id) -> Transaction | None`.
  - `select_for_block(state, max_block_bytes=4096) -> list[Transaction]` (bí danh `peek_for_block`, `get_executable_txs`): duyệt theo thứ tự đến, giữ thứ tự nonce theo từng tài khoản, dừng ngay tại giao dịch đầu tiên vượt ngưỡng 4096 byte.
  - `remove_finalized(transactions_or_ids=(), state=None) -> int` (bí danh `remove_txs`, `remove_block_txs`, `prune`).
  - `pending() -> list[Transaction]` (bí danh `get_all`, `list_txs`).

#### `src/node/ledger.py`
- **Lớp `LedgerEntry`**: chứa `block: Block` và `certificate: CommitCertificate | None`.
- **Lớp `Ledger`**:
  - Khởi tạo sẵn khối Genesis ở `height = 0`.
  - Thuộc tính & phương thức:
    - `latest_height -> int`, `height() -> int`
    - `latest() -> Block`, `latest_entry() -> LedgerEntry`, `latest_hash() -> HashHex`
    - `get(height) -> Block | None`, `get_certificate(height) -> CommitCertificate | None`, `get_entry(height) -> LedgerEntry | None`
    - `get_range(from_height, to_height) -> list[LedgerEntry]`
    - `append(block, certificate, validator_pubkeys=None, quorum=None) -> tuple[bool, str | None]`: chỉ thêm khối khi nối đúng `parent_hash` và `CommitCertificate` hợp lệ.
    - `all_blocks(include_genesis=True) -> list[Block]`
    - `summary_chain() -> list[tuple[int, str]]`

#### `src/node/sync.py`
- **Lớp `SyncManager`**:
  - `build_status_message() -> Message`
  - `broadcast_status(env=None, peers=None) -> Message`
  - `handle_status(from_peer, payload, env=None) -> Message | None`: phát hiện peer có height cao hơn và gửi `GET_BLOCKS`.
  - `handle_get_blocks(from_peer, payload, env=None) -> Message | None`: lấy các cặp `(Block, CommitCertificate)` từ `Ledger` và gửi `BLOCKS`.
  - `handle_blocks(from_peer, payload, on_block_finalized=None) -> tuple[bool, str | None, list[Block]]`: tự xác minh từng khối + chứng nhận, nối vào `Ledger`, cập nhật `State` và dọn `TxPool`.
  - `request_votes(height, round_num, env=None, peers=None) -> Message`
  - `handle_get_votes(from_peer, payload, votes_provider=None, env=None) -> Message | None`
  - `handle_votes(from_peer, payload, on_valid_vote=None, current_height=None, future_height_window=5) -> tuple[bool, str | None, list[Vote]]`

#### `src/node/query.py`
- **Lớp `ChatQuery` (bí danh `NodeQuery`, `QueryInterface`)**:
  - `get_latest(k, include_genesis=False) -> list[Block]`
  - `get_block(height) -> Block | None`
  - `get_chat_messages(blocks=None, last=None, height=None) -> list[dict[str, Any]]`
  - `get_state() -> State`
  - `get_state_entries(account=None) -> dict[str, str]`
- Hàm mức module: `get_latest(ledger, k)`, `get_block(ledger, height)`.

---

### 2.5 Công cụ Quan sát (`tests/tools/`)

- **`tests/tools/show_chat.py`**:
  - Hàm: `normalize_node_id(node_arg)`, `parse_log_line(line)`, `reconstruct_node_from_log(log_path, node_id)`, `format_chat_output(query, node_id, last=None, height=None)`, `main(argv=None)`.
  - CLI: `python -m tests.tools.show_chat --log <file.log> --node 3 [--last k | --height H]`.
- **`tests/tools/show_state.py`**:
  - Hàm: `format_state_output(state_or_query, node_id, account=None)`, `main(argv=None)`.
  - CLI: `python -m tests.tools.show_state --log <file.log> --node 3 [--account alice]`.
