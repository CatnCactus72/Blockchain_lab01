# Chat Chain: kênh chat chung chạy trên blockchain mô phỏng

Chat Chain là một blockchain Layer 1 tối giản mô phỏng một **kênh chat chung**. Mỗi tin nhắn là một giao dịch có chữ ký; các node gom tin nhắn thành block và dùng đồng thuận BFT (propose, prevote, precommit) để cả mạng thống nhất **một thứ tự tin nhắn duy nhất**. Khi block đã finalize, thứ tự này không thể bị đổi.

Toàn bộ mạng (10 node, độ trễ, mất gói, node lỗi) chạy trong **một process Python** với đồng hồ ảo, nên mỗi lần chạy là hữu hạn và lặp lại được từng byte.

> Tài liệu này mô tả thiết kế cần cài đặt. Mọi con số trong tài liệu là giá trị đã chốt, đặt trong `config/`.

## Mục lục

1. [Cài đặt và chạy nhanh](#1-cài-đặt-và-chạy-nhanh)
2. [Tổng quan hoạt động](#2-tổng-quan-hoạt-động)
3. [Mô hình dữ liệu](#3-mô-hình-dữ-liệu)
4. [Đồng thuận](#4-đồng-thuận)
5. [Mạng mô phỏng](#5-mạng-mô-phỏng)
6. [Mật mã và mã hóa](#6-mật-mã-và-mã-hóa)
7. [Cấu hình](#7-cấu-hình)
8. [Kịch bản và node lỗi](#8-kịch-bản-và-node-lỗi)
9. [Log](#9-log)
10. [Công cụ quan sát](#10-công-cụ-quan-sát)
11. [Kiểm thử](#11-kiểm-thử)
12. [Cấu trúc thư mục và nhiệm vụ từng file](#12-cấu-trúc-thư-mục-và-nhiệm-vụ-từng-file)
13. [Quy ước code](#13-quy-ước-code)

---

## 1. Cài đặt và chạy nhanh

**Yêu cầu:** Python 3.10 trở lên. Thư viện ngoài duy nhất là `cryptography` (Ed25519).

```bash
pip install -r requirements.txt        # nội dung: cryptography
```

**Chạy một kịch bản:**

```bash
python -m src.main --config config/scenarios/t1_normal.json
python -m src.main --config config/scenarios/t7_byzantine_equivocate.json --seed 42
python -m src.main --config config/scenarios/t7_byzantine_equivocate.json --faulty 2 5 8 --out logs
```

| Tham số | Ý nghĩa |
|---|---|
| `--config` | File kịch bản (bắt buộc), kế thừa `config/base.json` |
| `--seed` | Ghi đè seed (mặc định 42) |
| `--faulty` | Ghi đè danh sách node lỗi của kịch bản (id node, cách nhau bởi dấu cách) |
| `--out` | Thư mục ghi log (mặc định `logs`) |

Kết thúc mỗi lần chạy, chương trình in bản tóm tắt: chuỗi block đã finalize của từng node (height, hash), state hash cuối, và kết luận có hội tụ hay không. Mã thoát là 0 nếu mọi node đúng hội tụ, khác 0 nếu không.

**Chạy kiểm thử:**

```bash
python -m tests.run_all                                   # toàn bộ unit + e2e, in PASS/FAIL từng test
python -m tests.check_determinism --config config/scenarios/t8_determinism.json
```

**Xem kết quả:**

```bash
python -m tests.tools.show_chat  --log logs/<file>.log --node 3 --last 2     # 2 block mới nhất của N3
python -m tests.tools.show_chat  --log logs/<file>.log --node 3 --height 7   # block ở height 7
python -m tests.tools.show_state --log logs/<file>.log --node 3 --account alice
python -m tests.tools.trace      --log logs/<file>.log --msg a3f9c1          # đường đi của một wire message
```

---

## 2. Tổng quan hoạt động

```
 Người dùng (alice)                  Mạng 10 node (N0..N9)
        │  1. ký tin nhắn (tx)
        ▼
   [node nhận tx] ──2. gossip tx──► tx pool của mọi node
                                         │
   3. proposer (height+round) mod 10 gom tx từ pool, thực thi thử,
      dựng block, ký, gossip PROPOSAL (header)  ──► mọi node
                                         │
   4. node chấp nhận header ──xin BODY──► nhận body, kiểm tra, thực thi lại
                                         │
   5. PREVOTE ──(đủ 7)──► khóa block ──► PRECOMMIT ──(đủ 7)──► FINALIZE
                                         │
   6. block vào ledger kèm commit certificate, state cập nhật,
      tx đã vào block bị xóa khỏi pool, sang height kế tiếp
```

Điều chương trình **đảm bảo**: mọi node đúng có chuỗi block finalize giống nhau (node chậm chỉ ở phía sau, không bao giờ khác thứ tự), và thứ tự tin nhắn trong từng block là cố định.

Điều chương trình **không hứa**: tin nhắn được xếp theo thời điểm gửi thật. Các node không có đồng hồ chung; thứ tự do proposer chọn rồi cả mạng chấp nhận. Một proposer lỗi có thể trì hoãn tin của người khác, nhưng tin vẫn được đưa vào khi tới lượt một proposer đúng.

Giao diện chat chỉ nên hiển thị tin **đã finalize**. Tin chưa finalize là trạng thái "đang chờ".

---

## 3. Mô hình dữ liệu

### 3.1 Tin nhắn (transaction)

Mỗi tin nhắn là một giao dịch `SET` ghi vào không gian tên của chính người gửi:

| Trường | Mô tả |
|---|---|
| `account` | Tên tài khoản người gửi (`alice`, `bob`, `carol`, `dave`, `erin`) |
| `nonce` | Số thứ tự tin của tài khoản, bắt đầu từ 1 |
| `key` | Bắt buộc đúng dạng `<account>/chat/<nonce>` |
| `value` | Nội dung tin nhắn (văn bản) |
| `signature` | Chữ ký Ed25519, domain `TX` |

Quy tắc kiểm tra một tin nhắn (theo thứ tự):

1. `account` có trong sổ tài khoản (`UNKNOWN_ACCOUNT`).
2. Chữ ký hợp lệ bằng khóa công khai của `account` (`BAD_SIGNATURE`, `WRONG_DOMAIN`).
3. `key` bắt đầu bằng `<account>/` (`NOT_OWNER`) và đúng dạng `<account>/chat/<nonce>` (`BAD_KEY`).
4. `value` không rỗng, tối đa **200 ký tự** (đếm code point sau khi chuẩn hóa NFC) và toàn bộ tx mã hóa tối đa **1024 byte** (`TX_TOO_LONG`).
5. `nonce` đúng bằng `nonce_đã_áp_dụng + 1` của tài khoản. Nhỏ hơn hoặc bằng là `REPLAYED_TX`, lớn hơn là `BAD_NONCE`.

`tx_id = SHA256("TXID" ‖ account ‖ nonce ‖ enc(key) ‖ enc(value))`, dùng để khử trùng trong tx pool và để tính `tx_root`.

Sổ tài khoản (`account → khóa công khai`) cố định, sinh từ seed lúc khởi tạo, **nằm trong cấu hình, không nằm trong state**.

### 3.2 State

State là map key-value, ban đầu rỗng. Mỗi tin nhắn đã áp dụng thêm một mục `alice/chat/5 = "xin chào"`. State chỉ để cam kết bằng hash; **thứ tự kênh chat lấy từ ledger** (height rồi vị trí trong block), không lấy từ state.

`state_hash = SHA256("STATE" ‖ enc_map(state))`. Đây là hash phẳng trên map đã sắp key, không dùng cây Merkle.

### 3.3 Block

```
Block
├── Header
│   ├── chain_id          "lab01-chain"
│   ├── height
│   ├── parent_hash
│   ├── tx_root           SHA256("TXROOT" ‖ enc_list(tx_id...))
│   ├── state_hash        state sau khi thực thi body
│   ├── proposer_id       người tạo block
│   ├── timestamp         thời gian ảo (ms), phải lớn hơn timestamp block cha
│   └── signature         chữ ký người tạo, domain HEADER (không nằm trong block_hash)
└── Body
    └── danh sách tx có thứ tự, tổng kích thước mã hóa ≤ 4096 byte, có thể rỗng
```

`block_hash = SHA256("BLOCK" ‖ enc(header không gồm signature))`. Round không nằm trong block mà nằm trong vote và proposal, nhờ đó một block có thể được bầu ở nhiều round.

**Genesis:** height 0, `chain_id = "lab01-chain"`, `block_hash = SHA256("GENESIS" ‖ chain_id)`, state rỗng.

### 3.4 Proposal

`PROPOSAL` là lớp bọc để đề xuất block ở một round cụ thể, kể cả đề xuất lại block đã khóa từ round trước:

```
PROPOSAL
├── height, round
├── block_hash
├── pol_round        round đã thấy đủ 7 prevote cho block này, hoặc -1 nếu là block mới
├── header           kèm chữ ký người tạo (domain HEADER)
└── proposal_sig     chữ ký proposer của round hiện tại (domain PROPOSAL)
                     trên (height, round, block_hash, pol_round)
```

Người tạo block (trong header) và proposer của round (ký proposal) trùng nhau khi block mới, khác nhau khi đề xuất lại. Nhờ hai chữ ký riêng, `block_hash` không đổi qua các round nên khóa vẫn tham chiếu đúng.

### 3.5 Vote và commit certificate

`Vote = (height, round, phase PREVOTE|PRECOMMIT, block_hash hoặc NIL, validator_id, signature)`, domain `VOTE`.

`CommitCertificate` là tập 7 precommit hợp lệ cho cùng `block_hash` ở cùng height. Ledger lưu certificate kèm block. Node bị tụt lại nhận block qua đồng bộ sẽ **tự kiểm tra certificate** thay vì tin peer.

---

## 4. Đồng thuận

Quorum là 7 trên 10 validator (`n = 10`, `f = 3`).

**Nhịp một height.** Sau khi finalize height `h`, mỗi node đợi 1000 ms (ảo) rồi bắt đầu round 0 của `h + 1`. Proposer của `(height, round)` là node `(height + round) mod 10`.

**Các bước trong một round:**

1. **Propose.** Proposer dựng block mới (mục 4.1), hoặc đề xuất lại block của mình đã khóa hoặc đã thấy đủ prevote (`valid_value`), rồi gossip `PROPOSAL`.
2. **Chấp nhận header.** Kiểm tra `chain_id`, `height`, `parent_hash`, chữ ký header, proposer đúng của round, `timestamp`. Hợp lệ thì chuyển tiếp proposal và gửi `BODY_REQUEST` cho peer đã đưa proposal.
3. **Kiểm tra body.** Tính lại `tx_root`; thực thi từng tx trên state cha, mỗi tx phải hợp lệ theo mục 3.1; kiểm tra tổng kích thước ≤ 4096 byte (`BLOCK_TOO_LARGE`); tính lại `state_hash`. Sai chỗ nào thì ghi lý do (`BAD_TX_ROOT`, `BAD_STATE_HASH`, `BAD_NONCE`...) và prevote NIL.
4. **Prevote.** Prevote block hợp lệ nếu chưa khóa, hoặc đã khóa đúng block đó, hoặc `pol_round` chứng tỏ có quorum prevote cho block này ở round sau round đã khóa. Ngược lại prevote NIL. Hết timeout propose mà chưa có block hợp lệ thì prevote NIL.
5. **Precommit.** Thấy 7 prevote cùng một block: khóa block (`locked_value`, `locked_round`), ghi `valid_value`, precommit block. Thấy 7 prevote bất kỳ nhưng không cùng block, hoặc hết timeout prevote: precommit NIL.
6. **Finalize.** Thấy 7 precommit cùng một block ở một round bất kỳ của height hiện tại: thêm block kèm certificate vào ledger, áp dụng state, xóa các tx đã vào block khỏi pool, sang height kế.
7. **Đổi round.** Hết timeout precommit mà chưa finalize thì sang round kế với proposer kế.

**Timeout.** Ba timeout (propose, prevote, precommit), mỗi cái bằng `5000 + 2000 × round` ms thời gian ảo. Timer cũ (node đã sang round khác) mang theo `(height, round)` và bị bỏ qua khi nổ.

**Nhảy round.** Thấy f+1 = 4 vote hợp lệ của một round cao hơn thì nhảy sang round đó.

**Đếm vote.** Mỗi `(validator, height, round, phase)` chỉ tính vote hợp lệ đầu tiên. Cùng nội dung đến lần nữa: bỏ qua (`DUPLICATE_VOTE`). Vote khác nội dung của cùng validator: từ chối, không chuyển tiếp, ghi bằng chứng (`CONFLICTING_VOTE`).

**Message tương lai.** Message có height trong `[hiện tại, hiện tại + 5]` được đệm lại; ngoài khoảng đó bị bỏ (`FUTURE_HEIGHT`) và dựa vào đồng bộ.

### 4.1 Dựng block

Proposer duyệt tx pool theo thứ tự đến (giữ đúng thứ tự nonce trong từng tài khoản; tx chưa tới lượt nonce thì để lại), cộng dồn kích thước mã hóa. **Dừng ngay tại tx đầu tiên không còn vừa** trong ngưỡng 4096 byte; phần còn lại ở pool cho block sau. Pool trống thì tạo block rỗng. Sau đó thực thi thử để lấy `state_hash`, tính `tx_root`, đặt `timestamp`, ký header.

---

## 5. Mạng mô phỏng

### 5.1 Topology và độ trễ

10 node `N0..N9`, nối vòng tròn mở rộng: node `i` nối với `i±1` và `i±2` (mod 10), mỗi node có đúng 4 peer, mạng có đường kính 3 hop. Với 4 peer, dù 3 node im lặng thì các node đúng vẫn liên thông.

| Loại liên kết | Độ trễ cơ bản (cố định trong `topology.json`) |
|---|---|
| `i ↔ i±1` | 20 đến 60 ms (mô phỏng gần nhau) |
| `i ↔ i±2` | 60 đến 120 ms (mô phỏng xa nhau) |

Mỗi lần giao tin cộng thêm jitter: số nguyên ngẫu nhiên từ seed trong `[0, base/5]`.

### 5.2 Số phận của một gói tin

Với mỗi gói gửi qua một liên kết, RNG của liên kết quyết định theo thứ tự cố định: drop, trùng, thêm trễ (gây đảo thứ tự), rồi lên lịch giao.

| Giai đoạn | Hành vi mặc định |
|---|---|
| Trước GST | Drop 30%, trùng 15%, thêm trễ tới 4000 ms |
| Sau GST | Không drop; có thể trùng và đảo thứ tự nhưng độ trễ mỗi liên kết ≤ Delta = 500 ms |

`gst_ms` do từng kịch bản đặt.

### 5.3 Gossip

- Chỉ gossip các wire message `TX`, `PROPOSAL`, `PREVOTE`, `PRECOMMIT`. Message cần đáp lại (`BODY_REQUEST`, `BODY`, `GET_*`, `STATUS`...) gửi trực tiếp một peer.
- **Khử trùng:** mỗi node giữ tập `seen` các `msg_id`. Gặp lại thì ghi `DUP` và bỏ.
- **Chuyển tiếp:** lần nhận đầu, nếu node trả `ACCEPT` thì chuyển cho mọi peer trừ peer vừa gửi, duyệt peer theo thứ tự id. `REJECT` và `IGNORE` thì không chuyển tiếp.
- **Header trước, body sau:** `PROPOSAL` đi trước; body chỉ được gửi sau khi bên nhận chấp nhận header và yêu cầu.

### 5.4 Đồng bộ bù mất mát

Cứ 2000 ms mỗi node gửi `STATUS` (height, hash block finalize cuối) cho các peer trực tiếp.
- Peer có height cao hơn: node gửi `GET_BLOCKS(from, to)`, nhận `BLOCKS` kèm certificate và tự kiểm tra.
- Node kẹt ở `(height, round)` quá lâu: gửi `GET_VOTES(height, round)`, nhận `VOTES`.

### 5.5 Giới hạn tốc độ và chặn peer

- Gửi ra: tối đa 300 wire message mỗi giây mỗi node; phần dư bị hoãn sang cửa sổ sau (ghi `DELAY`, `reason=RATE_LIMIT`).
- Nhận vào: một peer gửi quá 200 message trong 1000 ms thì bị chặn 3000 ms (`BLOCK`, rồi `UNBLOCK` khi hết hạn); message từ peer đang bị chặn bị bỏ (`PEER_BLOCKED`).

### 5.6 Các loại wire message

Gọi là *wire message* để phân biệt với *tin nhắn chat* (transaction).

| Nhóm | Kind |
|---|---|
| Quản lý peer | `HELLO`, `PING`, `PONG` |
| Giao dịch | `TX` |
| Block | `BODY_REQUEST`, `BODY` |
| Đồng thuận | `PROPOSAL` (đồng thời là thông báo header), `PREVOTE`, `PRECOMMIT` |
| Đồng bộ | `STATUS`, `GET_BLOCKS`, `BLOCKS`, `GET_VOTES`, `VOTES` |

Mỗi wire message gồm hai lớp:

- **Message** (bất biến, được hash): `kind`, `origin` (người tạo), `payload`, chữ ký nếu có.
- **Envelope** (đổi theo hop, không hash): `from_peer`, `to_peer`, thời điểm gửi.

`msg_id = SHA256("MSG" ‖ kind ‖ origin ‖ enc(payload))`. Peer chuyển tiếp cố ý **không** nằm trong `msg_id`, nếu không cùng một tin qua các đường khác nhau sẽ có id khác nhau và khử trùng hỏng. Log hiển thị 6 ký tự hex đầu của `msg_id`.

---

## 6. Mật mã và mã hóa

- **Chữ ký:** Ed25519 (chữ ký xác định). **Hash:** SHA-256.
- **Sinh khóa:** `key_seed = SHA256("KEY" ‖ seed ‖ role ‖ id)` (32 byte) làm seed Ed25519; `role` là `validator` hoặc `user`. Cùng seed thì cùng khóa, cùng chữ ký.
- **Domain separation:** dữ liệu được ký là `enc(domain) ‖ enc(chain_id) ‖ enc(các trường)`.

| Domain | Trường được ký (thứ tự cố định) |
|---|---|
| `TX` | `account, nonce, key, value` |
| `HEADER` | `height, parent_hash, tx_root, state_hash, proposer_id, timestamp` |
| `PROPOSAL` | `height, round, block_hash, pol_round` |
| `VOTE` | `height, round, phase, block_hash (hoặc NIL), validator_id` |

Tag chỉ dùng để hash (không ký): `BLOCK`, `MSG`, `STATE`, `TXROOT`, `TXID`, `KEY`, `GENESIS`.

- **Khi xác minh thất bại**, hàm `verify` thử lại với các domain còn lại để phân biệt `WRONG_DOMAIN` (đúng khóa, sai domain) với `BAD_SIGNATURE`.
- **Mã hóa chuẩn** (dùng cho mọi thứ được hash hoặc ký; JSON chỉ dùng cho config và log):

| Kiểu | Quy tắc |
|---|---|
| Số nguyên | `u64` big-endian, độ rộng cố định, không dùng số thực |
| bytes | tiền tố độ dài `u32` + nội dung |
| string | UTF-8 sau chuẩn hóa NFC, mã hóa như bytes |
| list | `u32` số phần tử + các phần tử theo thứ tự |
| map | các cặp sắp xếp theo byte của key |
| NIL / không có | 32 byte 0 |

---

## 7. Cấu hình

### `config/base.json`

```json
{
  "chain_id": "lab01-chain",
  "n": 10,
  "f": 3,
  "seed": 42,
  "max_text_chars": 200,
  "max_tx_bytes": 1024,
  "max_block_bytes": 4096,
  "block_interval_ms": 1000,
  "delta_ms": 500,
  "timeouts": { "base_ms": 5000, "step_ms": 2000 },
  "status_interval_ms": 2000,
  "future_height_window": 5,
  "rate_limit": { "send_per_sec": 300, "recv_window_ms": 1000, "recv_max": 200, "block_ms": 3000 },
  "pre_gst": { "drop": 0.30, "dup": 0.15, "extra_delay_max_ms": 4000 },
  "stop": { "target_height": 10, "max_virtual_time_ms": 120000 }
}
```

### `config/topology.json`

Danh sách 10 node và 20 liên kết `{a, b, base_ms}` đã cố định theo quy tắc ở mục 5.1.

### `config/workload.json`

- Sổ tài khoản: `alice`, `bob`, `carol`, `dave`, `erin`.
- Danh sách câu mẫu (tiếng Việt, có dấu, có emoji) để sinh nội dung.
- Chế độ thường: cứ 500 ms một tin nhắn, người gửi, nội dung và node nhận đều lấy từ seed; node nhận gossip tin cho cả mạng.
- Chế độ bùng nổ (tùy chọn): `{ "at_ms": 5000, "count": 100, "within_ms": 1000 }`.

### Mỗi file trong `config/scenarios/`

Kế thừa `base.json` và ghi đè: `gst_ms`, xác suất lỗi, danh sách node lỗi kèm loại hành vi và tham số, chế độ workload, `stop`, `seed`.

---

## 8. Kịch bản và node lỗi

Lỗi được **chèn theo lịch cố định** từ file kịch bản, không chờ lỗi tự xảy ra.

| Kịch bản | Cấu hình |
|---|---|
| `t1_normal` | GST = 0, không lỗi |
| `t2_dup_reorder` | GST = 0, trùng 20%, bật đảo thứ tự; N4 gửi mỗi gói 3 lần |
| `t3_bad_signature` | N3 luân phiên ba kiểu gửi sai: chữ ký bằng khóa khác, đúng khóa nhưng sai domain, sửa nội dung sau khi ký |
| `t4_replay_tx` | `alice` gửi lại cùng một tx (cùng nonce) 3 lần cách nhau 1 s, rồi gửi lại sau khi tx đã vào block; N5 (proposer ở height 5) nhét tx đã áp dụng vào block của mình |
| `t5_drop_delay_pre_gst` | GST = 30000 ms, lỗi trước GST theo mặc định, `max_virtual_time_ms` = 180000 |
| `t6_silent_proposer` | N1 (proposer của height 1, round 0) im lặng từ đầu |
| `t7_byzantine_equivocate` | N2, N5, N8 equivocate: vote và proposal khác nhau gửi cho hai nửa peer |
| `t8_determinism` | Chạy T1 và T7 hai lần seed 42 (phải giống hệt), một lần seed 43 (phải khác) |
| `x1_burst_blocksize` | Chế độ bùng nổ 100 tin trong 1 s để chạm giới hạn 4096 byte; tin dồn qua nhiều block, vẫn đúng thứ tự nonce |
| `x2_beyond_f` | 4 node im lặng (N6, N7, N8, N9), vượt quá f: mất tiến triển nhưng không có finalize sai |

Node lỗi dùng `Behavior` gắn vào node (xem `src/faults/`). Node trung thực dùng `Honest` (đi thẳng).

```python
class Behavior:
    def on_receive(self, node, from_peer, msg): return msg                  # sửa, hoặc None để nuốt
    def on_send(self, node, to, msg): return [(to, msg)]                    # bỏ, nhân bản, đổi nội dung
    def on_make_proposal(self, node, proposal): return [(node.peers, proposal)]
    def on_make_vote(self, node, vote): return [(node.peers, vote)]
```

Node lỗi vẫn ký bằng khóa của chính nó, nên chữ ký của nó hợp lệ; nó không thể giả chữ ký của node khác.

---

## 9. Log

**Tên file:** `TCx_DDMMYYYY_HHMMSS.log`, ví dụ `TC1_02112026_153000.log`. Nếu hai lần chạy cùng một giây (như T8) thêm hậu tố `_run1`, `_run2`. Ngày giờ thật chỉ xuất hiện trong **tên file**; nội dung log chỉ chứa thời gian ảo.

**Mỗi sự kiện một dòng**, dạng `key=value`, thứ tự trường cố định:

```
00:01:250 seq=00123 node=N4 ev=RECV h=5 r=0 msg=a3f9c1 kind=PREVOTE origin=N2 via=N2 first=true
00:01:301 seq=00131 node=N5 ev=REJECT h=5 r=0 msg=77be02 kind=PREVOTE origin=N8 reason=WRONG_DOMAIN
00:07:410 seq=00902 node=N3 ev=FINALIZE h=5 r=1 hash=9d41.. state=c0a7..
```

- Thời gian định dạng `MM:SS:mmm` (lưu nội bộ là số nguyên mili-giây). Dòng đầu là `00:00:000` (`SIM_START`), dòng cuối mang tổng thời lượng (`SIM_END`).
- **Trường bắt buộc:** thời gian, `node`, `ev`, `h`. **Tùy chọn:** `r`, `msg`, `kind`, `origin`, `via`, `details`, `reason`. `seq` là số thứ tự sự kiện tăng nghiêm ngặt.
- Sự kiện toàn cục dùng `node=NET` hoặc `node=SIM`; không có height thì `h=-`.

**Loại sự kiện (`ev`):**

| Nhóm | Giá trị |
|---|---|
| Mạng | `SEND`, `RECV`, `DROP`, `DELAY`, `DUP`, `BLOCK`, `UNBLOCK` |
| Đồng thuận | `PROPOSE`, `PREVOTE`, `PRECOMMIT`, `LOCK`, `TIMEOUT`, `NEW_ROUND`, `FINALIZE` |
| Kiểm tra, thực thi | `REJECT`, `TX_APPLIED`, `TX_SKIPPED` |
| Hệ thống | `SIM_START`, `SIM_END` |

**Mã lý do (`reason`, danh sách cố định):**
`BAD_SIGNATURE`, `WRONG_DOMAIN`, `WRONG_CHAIN`, `UNKNOWN_ACCOUNT`, `NOT_OWNER`, `BAD_KEY`, `TX_TOO_LONG`, `BAD_NONCE`, `REPLAYED_TX`, `BAD_PARENT`, `BAD_TX_ROOT`, `BAD_STATE_HASH`, `BAD_TIMESTAMP`, `BLOCK_TOO_LARGE`, `NOT_PROPOSER`, `DUPLICATE_MSG`, `DUPLICATE_VOTE`, `CONFLICTING_VOTE`, `FUTURE_HEIGHT`, `PEER_BLOCKED`, `RATE_LIMIT`.

**Tóm tắt cuối lần chạy** (in ra terminal và ghi vào `logs/summaries/`): chuỗi finalize từng node, state hash cuối, kết luận hội tụ.

---

## 10. Công cụ quan sát

| Công cụ | Chức năng |
|---|---|
| `tests/tools/trace.py` | Đọc log, dựng đường lan truyền của một `msg_id` (cây `origin → via → ...`, thời điểm đến từng node, số lần nhận trùng) |
| `tests/tools/show_chat.py` | Giả lập app chat: in kênh chat theo thứ tự ledger của một node; `--last k` lấy k block mới nhất, `--height H` lấy block ở height H (chỉ block đã finalize) |
| `tests/tools/show_state.py` | In các mục state của một tài khoản hoặc toàn bộ state của một node |

`show_chat` dùng giao diện đọc của node (`get_latest(k)`, `get_block(height)`), mô phỏng cách app tải vài block mới nhất rồi xin thêm block cũ khi người dùng lướt lên.

---

## 11. Kiểm thử

`python -m tests.run_all` chạy tuần tự: unit test, e2e T1 đến T8, rồi hai kịch bản phụ X1, X2 (báo riêng). Mỗi test in `PASS` hoặc `FAIL` kèm lý do.

Mỗi test e2e chạy kịch bản tương ứng rồi gọi các hàm kiểm tra bất biến trong `tests/invariants.py`:

- Không có hai block khác nhau cùng height được finalize bởi các node đúng.
- Hai node đúng bất kỳ: chuỗi finalize của node này là tiền tố của node kia; cùng height thì cùng `state_hash`.
- Mỗi tx được áp dụng đúng một lần; tx của cùng tài khoản theo đúng thứ tự nonce.
- Không vote nào bị đếm hai lần.
- Mọi sự kiện `REJECT` có `reason` thuộc danh sách cố định; log đúng định dạng, thời gian không giảm.

`tests/check_determinism.py` chạy cùng kịch bản hai lần với cùng seed, so sánh **nội dung** log (từng byte) và state hash cuối, rồi chạy một lần seed khác để xác nhận log khác.

---

## 12. Cấu trúc thư mục và nhiệm vụ từng file

```
.
├── README.md
├── requirements.txt
├── config/
├── src/
│   ├── sim/   net/   crypto/   core/   execution/   node/   faults/   logsys/
├── tests/
│   ├── unit/   e2e/   tools/
└── logs/
```

Hướng phụ thuộc (không có vòng): `crypto ← core ← execution ← node ← sim/net`, và `faults` cắm vào `node` qua `Behavior`. `node` **không** import `net` hay `sim`.

### Gốc

| File | Nhiệm vụ |
|---|---|
| `README.md` | Tài liệu này |
| `requirements.txt` | Một dòng: `cryptography` |
| `src/__init__.py` (và `__init__.py` ở mọi thư mục con của `src/` và `tests/`) | File rỗng để import và `python -m` hoạt động |

### `config/`

| File | Nhiệm vụ |
|---|---|
| `base.json` | Tham số chung như mục 7 |
| `topology.json` | 10 node, 20 liên kết `{a, b, base_ms}` cố định |
| `workload.json` | Sổ tài khoản, câu mẫu, nhịp sinh tin, chế độ bùng nổ |
| `scenarios/t1_normal.json` ... `t8_determinism.json` | Mỗi file một kịch bản như bảng mục 8 (GST, xác suất lỗi, node lỗi, seed, điều kiện dừng) |
| `scenarios/x1_burst_blocksize.json`, `x2_beyond_f.json` | Hai kịch bản phụ |

### `src/main.py` và `src/sim/`

| File | Nhiệm vụ |
|---|---|
| `main.py` | Phân tích tham số CLI; nạp `base.json` và kịch bản, trộn cấu hình; dựng simulator, mạng, node, hành vi lỗi, workload; chạy; ghi log và tóm tắt; trả mã thoát |
| `sim/clock.py` | Đồng hồ ảo (số nguyên ms): `now()`, `advance_to(t)`; cấm đọc giờ thật |
| `sim/event_queue.py` | Hàng đợi ưu tiên theo `(time, seq)`; `seq` tăng đơn điệu để phá thế hòa |
| `sim/rng.py` | Một RNG gốc từ seed; hàm `child(*tên)` sinh RNG con xác định theo node, liên kết, workload, node lỗi |
| `sim/simulator.py` | Vòng lặp: lấy sự kiện sớm nhất, đặt đồng hồ, gọi `on_start` / `on_message` / `on_timer` của node; phát sự kiện workload; kiểm tra điều kiện dừng (`target_height` hoặc `max_virtual_time_ms`); dựng `NodeEnv` cho từng node |

### `src/net/`

| File | Nhiệm vụ |
|---|---|
| `topology.py` | Đọc `topology.json`, dựng đồ thị, kiểm tra liên thông, trả danh sách peer (sắp theo id) |
| `link.py` | Một liên kết: độ trễ cơ bản, jitter, quyết định drop/trùng/thêm trễ theo giai đoạn (trước/sau GST) bằng RNG của liên kết |
| `network.py` | Nhận `send` từ node, hỏi `link` rồi lên lịch giao vào hàng đợi, ghi log `SEND`, `RECV`, `DROP`, `DELAY`, `DUP`; gọi `on_message` và nhận `Verdict` |
| `gossip.py` | Tập `seen` theo `msg_id`; khử trùng; chuyển tiếp khi `ACCEPT` tới mọi peer trừ nguồn theo thứ tự id; ghi `first=true/false` và `via` |
| `rate_limit.py` | Giới hạn gửi (hoãn phần dư) và nhận (chặn peer vượt ngưỡng, hết hạn thì mở); ghi `BLOCK`, `UNBLOCK`, `RATE_LIMIT`, `PEER_BLOCKED` |

### `src/crypto/`

| File | Nhiệm vụ |
|---|---|
| `domain.py` | Hằng domain ký (`TX`, `HEADER`, `PROPOSAL`, `VOTE`) và tag hash (`BLOCK`, `MSG`, `STATE`, `TXROOT`, `TXID`, `KEY`, `GENESIS`) |
| `encoding.py` | Mã hóa chuẩn theo bảng mục 6: `enc_uint`, `enc_bytes`, `enc_str` (NFC), `enc_list`, `enc_map`; kèm hàm giải mã tương ứng nếu cần |
| `hashing.py` | `sha256(*phần)` trên dữ liệu đã mã hóa chuẩn; các hàm tiện ích `block_hash`, `tx_id`, `msg_id`, `state_hash`, `tx_root` |
| `signing.py` | `derive_keypair(seed, role, id)`; `sign(sk, domain, chain_id, fields)`; `verify(...)` trả `(ok, reason)` với `WRONG_DOMAIN` và `BAD_SIGNATURE` phân biệt |

### `src/core/`

| File | Nhiệm vụ |
|---|---|
| `user.py` | Lớp `User`: tên tài khoản, cặp khóa, bộ đếm nonce; hàm `make_message(text)` tạo và ký tx; hàm tạo sổ tài khoản (`account → pubkey`) từ seed |
| `transaction.py` | Lớp `Transaction` (một tin nhắn chat): các trường mục 3.1, `signing_fields()`, `tx_id()`, mã hóa/giải mã, kiểm tra độ dài ký tự và byte |
| `header.py` | Lớp `Header`: các trường mục 3.3, `signing_fields()` (không gồm chữ ký), `block_hash()` |
| `block.py` | Lớp `Block = Header + Body`; `body_size()`; hàm dựng block genesis |
| `vote.py` | Lớp `Vote` (prevote/precommit, NIL) và `CommitCertificate`; hàm kiểm tra certificate đủ 7 precommit hợp lệ |
| `proposal.py` | Lớp `Proposal` như mục 3.4; hàm kiểm tra `proposal_sig` và proposer đúng của round |
| `wire.py` | Các `kind` wire message, lớp `Message` và `Envelope`, tính `msg_id`, mã hóa payload cho từng kind |

### `src/execution/`

| File | Nhiệm vụ |
|---|---|
| `state.py` | Lớp `State` (map key-value, nhân bản được), bộ đếm nonce đã áp dụng theo tài khoản, `state_hash()` độc lập thứ tự chèn |
| `executor.py` | `apply_tx(state, tx)` kiểm tra quyền sở hữu key, dạng key, nonce rồi ghi; `apply_block(state, block)` trả state mới hoặc lý do lỗi; có chế độ "thực thi thử" cho proposer |

### `src/node/`

| File | Nhiệm vụ |
|---|---|
| `interfaces.py` | `NodeEnv` (`now`, `send`, `gossip`, `set_timer`, `cancel_timer`, `log`, `rng`, `peers`), `NodeCallbacks` (`on_start`, `on_message`, `on_timer`) và `Verdict` (`ACCEPT`, `REJECT(reason)`, `IGNORE`) |
| `node.py` | Ghép các thành phần; điều phối wire message theo `kind` và đưa qua `Behavior`; giữ ledger, view, pool, state, thông tin khóa |
| `consensus.py` | Máy trạng thái mục 4: round, ba timeout, propose/prevote/precommit/finalize, khóa (`locked_*`, `valid_*`), nhảy round, xử lý `pol_round` |
| `proposer.py` | Hàm chọn proposer `(height + round) mod n` và kiểm tra một node có phải proposer của `(height, round)` |
| `block_builder.py` | Dựng block theo mục 4.1: duyệt pool, giữ thứ tự nonce, dừng khi vượt 4096 byte, thực thi thử, tính `tx_root`, `state_hash`, ký header |
| `tx_pool.py` | Pool theo thứ tự đến; nhận tx sau khi kiểm tra ở mục 3.1; khử trùng theo `tx_id`; xóa tx khi đã vào block finalize |
| `validation.py` | Kiểm tra tx, header, proposal, body, block (mọi lý do ở danh sách mã `reason`); mỗi hàm trả `(ok, reason)` |
| `vote_counter.py` | Đếm vote theo `(validator, height, round, phase)`; phân biệt trùng và mâu thuẫn; trả quorum 7 cho một block, cho NIL hoặc cho "bất kỳ" |
| `view.py` | Lưu proposal, body, vote đang chờ của height hiện tại; đệm message tương lai trong cửa sổ 5 height |
| `ledger.py` | Chuỗi block đã finalize kèm certificate; `append`, `get(height)`, `latest()`; thêm khối chỉ khi certificate hợp lệ |
| `sync.py` | Gửi `STATUS` định kỳ; xử lý `STATUS`, `GET_BLOCKS`/`BLOCKS` (kiểm tra certificate), `GET_VOTES`/`VOTES` |
| `query.py` | Giao diện đọc cho app và công cụ: `get_latest(k)`, `get_block(height)`, chỉ trả block đã finalize |

### `src/faults/`

| File | Nhiệm vụ |
|---|---|
| `base.py` | Lớp `Behavior` (bốn hook mục 8) và `Honest`; hàm tạo behavior từ cấu hình kịch bản |
| `silent.py` | Nuốt mọi message vào và ra, từ đầu hoặc từ thời điểm chỉ định |
| `bad_signature.py` | Làm sai chữ ký theo ba kiểu: khóa khác, đúng khóa sai domain, sửa nội dung sau khi ký |
| `replay.py` | Nhân bản mỗi gói gửi ra k lần; gửi lại wire message cũ sau một độ trễ |
| `equivocate.py` | Tạo hai vote (hoặc hai proposal) khác nhau cho cùng `(height, round, phase)`, mỗi bản gửi một nửa peer |
| `invalid_block.py` | Proposer lỗi đề xuất block sai: quá khổ, sai `state_hash`, chứa tx đã áp dụng (chọn bằng tham số) |

### `src/logsys/`

| File | Nhiệm vụ |
|---|---|
| `event.py` | Danh sách `ev`, danh sách `reason` cố định, thứ tự trường và hàm định dạng một dòng log |
| `logger.py` | Ghi log: tự điền thời gian ảo `MM:SS:mmm`, `seq`, `node`; đặt tên file theo mục 9; ghi vào bộ nhớ và ra file |
| `summary.py` | Dựng bản tóm tắt cuối lần chạy: chuỗi finalize từng node, state hash, kết luận hội tụ; in ra terminal và ghi vào `logs/summaries/` |

### `tests/`

| File | Nhiệm vụ |
|---|---|
| `run_all.py` | Chạy lần lượt unit, e2e T1 đến T8, X1, X2; in `PASS`/`FAIL`; mã thoát khác 0 nếu có test hỏng |
| `check_determinism.py` | Chạy một kịch bản hai lần cùng seed, so nội dung log và state hash cuối; chạy một seed khác để xác nhận log khác |
| `invariants.py` | Các hàm kiểm tra bất biến ở mục 11, dùng chung cho mọi test e2e |
| `helpers.py` | Dựng kịch bản từ file, chạy simulator trong test, đọc và lọc log |

**`tests/unit/`**

| File | Nhiệm vụ |
|---|---|
| `test_crypto.py` | Ký và xác minh đúng; sai domain trả `WRONG_DOMAIN`; sửa dữ liệu trả `BAD_SIGNATURE`; mã hóa chuẩn xác định; khóa sinh từ seed lặp lại được |
| `test_state.py` | Áp dụng tx; từ chối `NOT_OWNER`, `BAD_KEY`, `BAD_NONCE`, `REPLAYED_TX`; `state_hash` không phụ thuộc thứ tự chèn |
| `test_vote_counter.py` | Vote trùng không đếm hai lần; vote mâu thuẫn bị từ chối; đủ 7 mới thành quorum; NIL và "bất kỳ" |
| `test_block_validation.py` | Từng lý do từ chối block: cha sai, `tx_root` sai, `state_hash` sai, proposer sai, timestamp sai, chữ ký sai |
| `test_limits.py` | Đếm ký tự với tiếng Việt (NFC), emoji; giới hạn 200 ký tự, 1024 byte mỗi tx, 4096 byte mỗi block |

**`tests/e2e/`**

| File | Nhiệm vụ |
|---|---|
| `test_t1_normal.py` ... `test_t8_determinism.py` | Chạy kịch bản tương ứng ở mục 8, gọi các hàm kiểm tra bất biến, và kiểm tra thêm điều riêng của kịch bản (ví dụ T3 có `REJECT` với đúng `reason`, T6 có `NEW_ROUND` rồi `FINALIZE`) |
| `test_x1_burst.py` | Tin bùng nổ dồn qua nhiều block, không block nào vượt 4096 byte, mọi tin cuối cùng đều vào chuỗi |
| `test_x2_beyond_f.py` | Với 4 node im lặng: không có `FINALIZE` nào sai; đạt `max_virtual_time_ms` mà không finalize được là kết quả đúng |

**`tests/tools/`**: `trace.py`, `show_chat.py`, `show_state.py` như mục 10.

### `logs/`

| Mục | Nhiệm vụ |
|---|---|
| `*.log` | Log của từng lần chạy, tên theo mục 9 |
| `summaries/` | Bản tóm tắt cuối mỗi lần chạy; giữ thư mục bằng file `.gitkeep` |

---

## 13. Quy ước code

1. **Tính xác định:** không dùng thời gian thật, `random` toàn cục, `uuid`, `os.urandom`, hàm `hash()` của Python, hay duyệt `set` không sắp xếp trong bất cứ thứ gì ảnh hưởng đến log, id, hash hoặc thứ tự sự kiện. Mọi ngẫu nhiên đến từ `sim/rng.py`.
2. **Tách tầng:** `node` chỉ giao tiếp qua `NodeEnv`; không import `net` hay `sim`. Mạng không biết luật đồng thuận.
3. **Lỗi không nằm trong node:** hành vi lỗi cài trong `src/faults/`, không viết `if byzantine` trong code node.
4. **Ký và hash:** mọi thao tác đi qua `src/crypto/` với domain và tag đã định nghĩa; không bao giờ ký hay hash JSON.
5. **Từ chối phải có lý do:** mọi `REJECT` ghi một `reason` thuộc danh sách cố định ở mục 9; thêm lý do mới thì cập nhật `logsys/event.py` và README.
6. **Cấu hình ngoài code:** tham số nằm trong `config/`, không hard-code trong `src/`.
7. **Tên gói:** dùng `execution` và `logsys`, không dùng `exec` và `logging` để khỏi trùng tên của Python.
8. **Tên gọi:** *tin nhắn chat* hoặc *transaction* là nội dung người dùng; *wire message* là gói tin mạng.
