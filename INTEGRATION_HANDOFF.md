# BÀN GIAO – Người 1 (môi trường mô phỏng)

## 1. Những file đã tạo/thay đổi

- `src/sim/clock.py`, `event_queue.py`, `rng.py`, `simulator.py`
- `src/net/topology.py`, `link.py`, `rate_limit.py`, `gossip.py`, `network.py`
- `src/logsys/event.py`, `logger.py`, `summary.py`
- `src/faults/base.py`, `silent.py`, `bad_signature.py`, `replay.py`, `equivocate.py`, `invalid_block.py`
- `src/main.py`
- `config/base.json`, `topology.json`, `workload.json`, `config/scenarios/*.json`
- `tests/tools/trace.py`, `tests/check_determinism.py`, `tests/helpers_env.py`, `tests/unit/test_part1_environment.py`
- `README_PART1.md`, `INTEGRATION_HANDOFF.md`; file `__init__.py` trong package mới.

- `requirements.txt` (khai báo `cryptography` như README; cần phối hợp Người 2 nếu thay đổi thư viện).
- `TEST_RESULTS_PART1.md` (kết quả kiểm thử phần môi trường).

**Không ghi đè** `src/core/`, `src/crypto/`, `src/node/`, `src/execution/`, `tests/e2e/` của các bạn còn lại.

## 2. Quy ước tên và kiểu dữ liệu

- Node id: chuỗi `N0`..`N9` (hàm `node_sort_key` sắp số tăng dần).
- `now_ms`, `at_ms`, `delay_ms`, `until_ms`: `int` mili-giây ảo (không dùng `time.time` trong simulator).
- `seed`: `int`; `SeededRNG.child(*names)` tạo RNG con từ SHA-256 của tên, không dựa vào `hash()`. `env.rng(*labels)` trả `random.Random` có trạng thái được giữ theo node và bộ nhãn; gọi lại cùng nhãn tiếp tục luồng cũ.
- `EventQueue.push(at_ms, name, callback, *args, **kwargs)`: chèn theo `(at_ms, seq)`; `pop()` lấy sớm nhất.
- `SimNodeEnv.send(peer, message, h=-1, r=None)` để gửi một peer; `gossip(message, h=-1, r=None)` để phát từ node hiện tại; `peers` là list đã sắp.
- `EventLogger.log(node, ev, h=-1, **fields)`: log theo chuẩn README, `seq` là log seq (khác event seq).
- `Network.send(source, dest, message, h=-1, r=None)` / `Network.gossip(source, message, exclude=None, h=-1, r=None)`.
- Wire message bắt buộc có: `.kind`, `.origin`, `.msg_id` (string/bytes hoặc method), hoặc dict với key tương ứng; **không được hash JSON** để lấy ID giả.

## 3. Giao diện ghép Node thuộc Người 3

`src.node.node.build_node(node_id, env, behavior, config) -> Node`.

Trong `Node` cần:

```python
node.env = env
node.behavior = behavior
node.on_start()                           # được gọi khi simulator bắt đầu
node.on_message(from_peer, message)        # nhận wire message, trả 'ACCEPT'/'REJECT'/'IGNORE'
node.on_timer(timer_name)                  # timer từ env.set_timer
node.finalized_chain() -> list            # danh sách dict height/hash, không gồm genesis
node.final_state_hash() -> str            # state hash đã finalized
```

`NodeEnv` đã cung cấp `now()`, `peers`, `rng(*name)`, `send`, `gossip`, `log`, `set_timer`, `cancel_timer`.

Với `on_message`, Node3 gọi `behavior.on_receive(node,from_peer,message)` trước validation; nếu trả `None` thì IGNORE. Khi outbound, **không cần gọi `behavior.on_send` thủ công**: `Network.send()` tự áp dụng hook, kể cả gói gossip được forward, để tránh double-count. Chỉ gọi `env.send` hoặc `env.gossip`.

Khi proposer/voter sinh message, gọi `behavior.on_make_proposal` hoặc `on_make_vote` và gửi cho các peer trong danh sách. `Behavior.on_timer` được gọi trong `Node.on_timer` nếu `name.startswith('fault:')`; phát lại các `(peer, message)` mà behavior trả về.

**Lưu ý riêng header/body:** Node3 chỉ gửi `BODY` sau khi đã có `BODY_REQUEST` cho header hợp lệ; tầng mạng chỉ cho gossip `PROPOSAL` và giao trực tiếp `BODY`, không tự suy đoán tính hợp lệ của block.

**Lưu ý:** gói consensus ký số phải có `msg_id` chính xác theo `src/core/wire.py` của Người 2. Nếu behavior thay đổi nội dung/chữ ký, phải tạo wire message mới với ID tương ứng, hoặc Network sẽ dedup nhầm. `Network` chỉ làm transport/gossip, không xác minh chữ ký.

## 4. Các callback thuộc Người 2/3 để tiêm lỗi thật

- `node.resign_wrong_domain(message)` -> bản sao message có chữ ký hợp lệ nhưng dưới domain sai.
- `node.tamper_signed_message(message)` -> bản sao có nội dung đổi sau khi ký.
- `node.make_conflicting_vote(vote)` -> **phiếu khác cùng height/round/phase nhưng ký hợp lệ** với khóa của Byzantine.
- `node.make_conflicting_proposal(proposal)` -> đề xuất mâu thuẫn, có chữ ký hợp lệ.
- `node.make_invalid_proposal(proposal, mode)` -> block invalid theo mode `bad_state_hash`, `oversized`, `replayed_tx`.
- `node.rebuild_wire_message(message)` -> wire message bất biến mới, tính lại `msg_id` bằng canonical encoding của `src/core/wire.py`. Nếu wire tự tính ID từ payload mới thì không cần callback này. Hook từ chối ID cũ sau khi sửa nội dung thay vì tự hash JSON.

`BadSignatureBehavior(mode='bad_key')` sửa byte chữ ký trên object có trường `.signature`, kể cả chữ ký nằm trong `.payload`. Đây là chữ ký hỏng để tạo BAD_SIGNATURE, chưa chứng minh việc ký bằng khóa khác. Việc sửa chỉ diễn ra trong `on_send`; `on_make_vote/proposal` giữ nguyên để tránh sửa hai lần làm phục hồi chữ ký. Mỗi ID đầu vào dùng một bản sửa ổn định trên mọi peer; bản sửa quay lại node không bị sửa tiếp vô hạn. Sai domain, equivocation và invalid block vẫn cần callback thực của Người 2/3; smoke không xác minh chữ ký.

## 5. Workload / transaction injection

Người 2/3 cần hiện thực `src.core.user.schedule_workload(sim, config, root_path)`. Nó tạo user, ký transaction, bọc wire kind=`TX` và dùng `sim.schedule(at_ms,'client-tx', callback)` để gửi tới node nhận. Giao diện ứng dụng client không được đụng vào state của node khác.

## 6. Những điểm CHƯA xác nhận được cho đến khi ghép

1. Chưa kiểm chứng Safety/Liveness và T1–T7: thiếu code consensus, chữ ký và state thực.
2. T3 có `mode=cycle`, tự luân phiên ba lỗi; `bad_key` sửa một byte chữ ký, còn `wrong_domain` và `tamper` gọi callback của Người 2/3.
3. T4 replay ở mức transaction đòi phối hợp `schedule_workload` và `invalid_block` callback.
4. T7 cần node Byzantine tạo phiếu/đề xuất xung đột **được ký hợp lệ**; callback chưa có thì phát sinh `NotImplementedError`, tuyệt đối không báo test PASS giả.
5. Script `tests/check_determinism.py` hiện so sánh same-seed/different-seed cho một scenario; để đúng README T8, cần chạy lần lượt T1 và T7 (trong `tests/run_all.py` của Người 3).
6. `t2` có node N4 duplicate outbound và `t7` có equivocation, nhưng hiệu lực đầy đủ phụ thuộc Node3 gọi hook.
7. Post-GST guarantee chỉ áp dụng cho delay mô phỏng **liên kết**, không thể tự khẳng định node consensus tiến triển khi peer block/rate limit.

## 7. Kiểm thử đã thực hiện

Kết quả sau tích hợp: **27/27 unit tests PASS** trên Python 3.11.8; cú pháp 76 file Python hợp lệ theo grammar Python 3.10. Chưa chạy runtime Python 3.10 vì máy hiện dùng 3.11.8. Chi tiết lệnh, bằng chứng và phần PENDING nằm trong `TEST_RESULTS_PART1.md` và `PART1_CODEX_REPORT.md`.

Chạy từ thư mục project:

```bash
python -m unittest discover -s tests/unit -p 'test_part1_environment.py' -v
python -m src.main --config config/scenarios/t1_normal.json --smoke-env
python -m tests.check_determinism --config config/scenarios/t1_normal.json --smoke-env
```

**Không đánh đồng kiểm thử smoke với test lab bắt buộc.**
