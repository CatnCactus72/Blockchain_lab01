# Báo cáo tích hợp Người 1 và Người 2 – Blockchain Lab 01

Ngày thực hiện: **05/11/2026**, múi giờ Asia/Bangkok.

## A. Trạng thái Git và bảo toàn công việc

| Nội dung | Giá trị thực tế |
|---|---|
| Branch ban đầu | `feature/lab01-part1-environment` |
| Commit Phần 1 đã có | `fa988a8464e6347a98c9ce133e1a80a1b7f1d587` |
| Working tree đầu phiên | Sạch; còn prompt, log và nguồn import được ignore |
| Lệnh lấy remote | `git fetch origin --prune`, thành công |
| Branch remote có Người 2 | **`origin/main`**, đã kiểm tra các remote branch; không giả định trước khi fetch |
| Commit cài đặt Người 2 | `9823f0d`, tác giả `thngoc17`, `feat(person-2): implement chain rules, wire protocol, and ledger validation` |
| Commit remote mới nhất tích hợp | `bfdfd76`, merge PR #1 từ `thngoc17/feat/chain-rules` |
| Branch tích hợp | `integration/part1-part2` |
| Merge commit local | `e1d2f20`, `merge: combine part1 environment with part2 chain rules` |
| Commit sửa điểm ghép | Thông điệp `fix(integration): connect simulation to chain rules`; xem SHA bằng `git log -1 --oneline` |
| Push / PR | **Chưa push, chưa mở PR**, theo yêu cầu chỉ thực hiện khi người dùng cho phép |

Đã tạo backup branch `backup/part1-before-part2-20261105` tại commit Phần 1. Ngoài repository có bản ZIP **149 file**, Git bundle đã xác minh và manifest:

```text
../Blockchain_lab01_backups/part1-before-part2-20261105.zip
../Blockchain_lab01_backups/part1-before-part2-20261105.bundle
../Blockchain_lab01_backups/part1-before-part2-20261105.json
```

ZIP gồm cả source/document local chưa theo dõi, prompt và nguồn import, loại `.git`, cache, môi trường ảo, log tạm và các tên file khóa/secret. Không đưa backup vào commit.

Merge bằng `git merge --no-ff --no-commit origin/main`; không có conflict source. `requirements.txt` hai phía cùng khai báo `cryptography`, giữ một dòng. Không dùng reset hard, clean, ours/theirs hàng loạt hoặc giải nén ZIP cũ lên source mới. Giữ nguyên branch Phần 1 và branch `main` local.

Remote Người 2 có **27 file bytecode Python 3.14** đã theo dõi. Đã bỏ riêng chúng khỏi Git index bằng `git rm --cached`; giữ file local và để `.gitignore` loại cache. Không xóa source của Người 2.

## B. File đã nhập, sửa và giữ nguyên

### Mã Người 2 nhập nguyên từ remote

`PERSON2_SUMMARY.md`; `src/crypto/{domain,encoding,hashing,signing}.py`; `src/core/{transaction,header,block,vote,proposal,user,wire}.py`; `src/execution/{state,executor}.py`; `src/node/{ledger,proposer,query,sync,tx_pool,validation}.py`; `tests/tools/{show_chat,show_state}.py`; `tests/unit/test_{crypto,state,block_validation,limits}.py`.

Ngoài các thay đổi rõ dưới đây, giữ nguyên implementation và toàn bộ test Người 2. Không thay thuật toán hash, canonical encoding, Ed25519, domain, quorum hay tham số README.

### Chỉnh sửa sau merge

| File | Người phụ trách ban đầu | Thay đổi đã thực hiện | Lý do |
|---|---|---|---|
| `src/core/user.py` | Người 2, phối hợp workload Người 1 | **Sửa:** thêm `schedule_workload`, giữ User/keybook cũ | Dùng User ký thật; ghép normal, burst, replay_alice với scheduler |
| `src/core/wire.py` | Người 2 | **Sửa:** kiểm tra giải mã hết payload | Trước đây bỏ qua byte thừa, tạo nguy cơ nhận dữ liệu chưa được kiểm tra |
| `src/net/network.py` | Người 1 | **Sửa:** snapshot bằng deepcopy, tách dispatch, thêm client inject | Payload Core là dataclass mutable; không để node sửa dữ liệu của node khác hoặc gói đang chờ |
| `src/sim/simulator.py` | Người 1 | **Sửa:** thêm `inject_message` | Workload gửi qua callback/validation thay vì sửa pool/state trực tiếp |
| `src/faults/bad_signature.py` | Người 1 | **Sửa:** tìm chữ ký trong payload khi Message.signature rỗng, hỗ trợ Proposal.proposal_sig | Đã tái hiện lỗi ValueError khi dùng Message thật; dataclass replace không nhận property signature của Proposal |
| `src/faults/signed.py` | Phối hợp Người 1/2 | **Mới:** `SignedFaultAdapter` | Tạo vote/proposal mâu thuẫn ký thật bằng khóa của chính validator lỗi |
| `src/node/interfaces.py` | Điểm ghép Người 1/3, trước đó rỗng | **Điền hợp đồng:** NodeEnv, NodeCallbacks, Verdict | Thống nhất kiểu callback, dữ liệu trả về và reason; không triển khai Node/Consensus |
| `src/node/sync.py` | Người 2 | **Sửa:** kiểm tra keybook, certificate thiếu/sai, độ dài lists; chặn vote chưa xác minh | Trước đây certificate=None gây AttributeError, zip có thể bỏ sót block; không tin peer khi thiếu khóa |
| `src/main.py` | Người 1 | **Sửa:** nạp workload thật và thông báo chỉ rõ thiếu Người 3 | Workload đã có, không còn báo cả Phần 2 chưa ghép |
| `tests/tools/show_chat.py` | Người 2 | **Sửa:** unquote log; đọc snapshot qua LogLedgerView; bỏ phiếu/certificate giả quorum=1 và fallback TX của node khác | Tương thích log escape/Unicode của Người 1; phân biệt dữ liệu quan sát với ledger đã xác minh |
| `tests/helpers_chain.py` | Phối hợp | **Mới:** bộ ghép ChainRulesNode chỉ cho test | Dùng State/TxPool/SyncManager thật; không thay Node của Người 3 |
| `tests/check_part1_part2.py` | Phối hợp | **Mới:** chương trình kiểm tra 10 node và determinism | Chạy phần có thể kiểm chứng bằng certificate fixture ký thật, ghi rõ consensus PENDING |
| `tests/unit/test_part1_part2_integration.py` | Phối hợp | **Mới:** 17 test điểm ghép | Kiểm chứng lỗi thực tế và hợp đồng giữa hai phần |
| `INTEGRATION_HANDOFF.md`, `README_PART1.md` | Người 1 | **Sửa:** dẫn đến báo cáo hiện hành | Giữ lịch sử bàn giao nhưng tránh nhầm trạng thái cũ |
| `PART1_PART2_INTEGRATION_REPORT.md` | Phối hợp | **Mới:** báo cáo này | Bàn giao API, kết quả và việc còn thiếu |

### Giữ nguyên

- README gốc, toàn bộ config và các tham số giao thức; requirements vẫn chỉ `cryptography`.
- Các module crypto/execution, Transaction/Header/Block/Vote/Proposal, TxPool/Validation/Ledger/Query/Proposer và test gốc Người 2.
- Đồng hồ, queue, RNG, topology, link, rate limit, gossip, logger, summary và các fault khác của Người 1.
- Không sửa `src/node/{node,consensus,block_builder,view,vote_counter}.py`, `tests/{run_all,invariants,helpers}.py`, `tests/e2e/*` và unit test vote counter của Người 3. Các file này hiện còn rỗng.
- Source tạm `part1_import/`, prompt ZIP và log local tiếp tục được ignore; không dọn xóa công việc cũ.

## C. Interface và luồng gọi thống nhất

### Wire và transport

- `Message(kind: str, origin: str, payload: Any, signature: bytes=b'')` giữ nguyên cách tính `.msg_id` của Người 2. Đây là `HashHex`, vừa giống str vừa gọi được; Network hỗ trợ cả property/method/bytes ID. Không hash JSON để tạo ID.
- `Envelope(message, from_peer, to_peer, sent_at_ms)` và `.forward(...)` đổi hop nhưng giữ nguyên msg_id. Network không coi `origin` là peer đã gửi hop hiện tại.
- `TX`, `PROPOSAL`, `PREVOTE`, `PRECOMMIT` là gossip. BODY/BODY_REQUEST, STATUS, GET_BLOCKS/BLOCKS, GET_VOTES/VOTES gửi peer trực tiếp. Chỉ ACCEPT mới forward; dedup theo ID đầy đủ, log hiển thị 6 ký tự đầu.
- `Network.send(source,dest,message,h=-1,r=None)` áp dụng on_send đúng một lần rồi snapshot gói gửi. Callback nhận bản sao; forwarding giữ nội dung gốc mà callback đã chấp nhận. Không đưa BFT vào transport.

### NodeEnv / callback

`src.node.interfaces.NodeEnv` là Protocol độc lập sim/net:

| API | Đầu vào | Trả về / ý nghĩa |
|---|---|---|
| `now()` | Không | `int` ms ảo |
| `peers` | Thuộc tính | `list[str]` sắp ổn định |
| `rng(*labels)` | Nhãn luồng | `random.Random` giữ trạng thái theo node/nhãn |
| `send(peer,message,h=-1,r=None)` | Peer trực tiếp, Message | `None` |
| `gossip(message,h=-1,r=None)` | Một trong 4 kind gossip | `None` |
| `set_timer(name,delay_ms)` | Tên và số ms không âm | Token `int` |
| `cancel_timer(token)` | Token timer | `None`, timer đã hủy không gọi node |
| `log(ev,h=-1,**fields)` | Sự kiện, field đúng đặc tả | Một dòng log `str` |

`NodeCallbacks`: `on_start()`, `on_message(from_peer,message) -> Verdict | str`, `on_timer(name)`, `finalized_chain() -> list`, `final_state_hash() -> str`. `Verdict.accept()`, `.reject(reason)`, `.ignore()` tạo kết quả; reject bắt buộc reason trong đặc tả. Network vẫn hỗ trợ enum/status/kind hiện có.

`src.node.node.build_node(node_id,env,behavior,config)` do Người 3 cung cấp. Gắn `node.env`, `node.behavior`; không import sim/net trong node. `finalized_chain()` trả danh sách block đã finalized **không gồm genesis**, biểu diễn JSON được, khuyến nghị `[{height, hash}, ...]`. State hash là của state đã finalized, không phải pool.

### Workload ký thật

`src.core.user.schedule_workload(sim,config,root_path) -> None` đọc workload_file, tạo User/keybook từ seed, dùng child RNG `workload`, lập lịch qua `sim.schedule`. Không dùng thời gian thật/random toàn cục.

Luồng:

```text
workload -> User.make_message -> Message(TX) -> sim.inject_message(node_id,msg)
         -> Network.inject -> node.on_message(node_id,msg)
         -> ACCEPT -> gossip -> peer.on_message(from_peer,msg)
```

Client cục bộ có `from_peer == node_id` và log `details=client`; Node cần nhận TX này qua validation giống TX từ peer. TX mới chỉ vào pool, chưa cập nhật State. Cứ `every_ms` sinh một TX; burst bổ sung `count` TX trong cửa sổ đã cấu hình. `replay_alice` phát lại TX Alice đầu tiên sau một nhịp, đổi origin/node nhận để dedup wire không che kiểm tra replay transaction. TX ID/chữ ký gốc không đổi.

### Sync, ledger và log

- `SyncManager(node_id,ledger,state,tx_pool,validator_pubkeys,account_pubkeys,chain_id,quorum,...)` phải nhận keybook thật và State/Ledger riêng cho từng node.
- STATUS -> `handle_status(from_peer,payload,env)` -> GET_BLOCKS. GET_BLOCKS -> `handle_get_blocks(...)` -> BLOCKS. BLOCKS -> `handle_blocks(...) -> (ok,reason,applied_blocks)`.
- BLOCKS được kiểm tra header/body, chữ ký, tx_root, state_hash và certificate trước khi áp dụng. Thiếu keybook/certificate, chữ ký hỏng hoặc danh sách block/certificate lệch đều bị từ chối; không chép state/ledger từ peer.
- GET_VOTES/VOTES đi trực tiếp; `handle_votes` xác minh từng phiếu bằng validator keybook. Việc tally, dedup/conflict vote và quyết định quorum thuộc Người 3.
- Ledger.append kiểm tra parent/certificate; Node phải validate toàn bộ block và tính state mới trước khi append. Node phát `TX_APPLIED` với `details=json.dumps({account,nonce,key,value}, ensure_ascii=False, sort_keys=True)` và FINALIZE với `hash/state`. Logger sẽ escape nội dung; viewer đã giải mã đúng.
- Viewer log trả `LogLedgerView` chỉ để đọc, không tạo certificate. Chỉ dùng sự kiện TX_APPLIED/FINALIZE của node đang xem. Khi thiếu chi tiết trong log, viewer không chứng minh được block hay state thật; Node/Sync không được dùng LogLedgerView để tin peer.

### Fault ký thật

`SignedFaultAdapter(node_id,private_key,chain_id)` chỉ giữ khóa của validator đó. Người 3 có thể gắn:

```python
node.make_conflicting_vote = signer.make_conflicting_vote
node.make_conflicting_proposal = signer.make_conflicting_proposal
node.resign_wrong_domain = signer.resign_wrong_domain
node.tamper_signed_message = signer.tamper_signed_message
```

- Hai vote khác block_hash/NIL cùng height/round/phase đều được ký hợp lệ bằng khóa Byzantine.
- Proposal mới của chính validator có thể tạo header khác timestamp, ký lại HEADER và PROPOSAL đúng khóa; hai bản có block_hash khác nhau. Đề xuất lại block đã khóa cần callback Block Builder, adapter báo NotImplementedError.
- Sai domain cho vote/proposal dùng đúng khóa và domain sai; tamper đổi nội dung sau ký. TX ký sai domain cần khóa user/callback riêng, adapter không lấy khóa của user khác. `bad_key` hiện làm hỏng một byte chữ ký, kiểm chứng BAD_SIGNATURE; chưa mô tả nó như một chữ ký hợp lệ bằng khóa khác.
- Node gọi on_receive trước validation; gọi on_make_vote/proposal khi tạo. Network gọi on_send, Node không gọi lần hai. Timer `fault:` chuyển đến behavior.on_timer và gửi các cặp peer/message trả về.
- Invalid block/oversized/replayed_tx proposal vẫn cần Block Builder của Người 3; không bịa block/certificate để vượt test.

## D. Kết quả kiểm thử thực tế

Runtime: **Python 3.11.8**, Windows; pip requirements thành công, `cryptography 47.0.0` đã có.

| Lệnh / kiểm tra | Exit / số lượng | Kết quả |
|---|---|---|
| `python --version` | 0 | Python 3.11.8 |
| `python -m pip install -r requirements.txt` | 0 | Dependency có sẵn |
| `python -m compileall -q src tests` | 0 | Không lỗi |
| `python -m unittest discover -s tests/unit -p 'test_*.py' -v` | 0, **73 PASS / 0 FAIL** | 27 Người 1 + 29 Người 2 + 17 test điểm ghép |
| `python -m src.main --config config/scenarios/t1_normal.json --smoke-env` | 0 | Hạ tầng chạy được |
| CLI smoke từng T1–T8, X1/X2 | 0 từng lệnh, 10/10 cấu hình | Không coi là e2e blockchain |
| `python -m tests.check_determinism --config config/scenarios/t1_normal.json --smoke-env` | 0 | Same-seed byte-identical; khác seed khác log |
| `python -m tests.check_part1_part2` | 0 | TX ký thật, 10 node, sync certificate fixture; log và final state hash cùng seed giống nhau |
| So process PYTHONHASHSEED=1 và 98765 | 0 | Cùng log SHA-256 và summary node |
| Import mới từng module src trong process riêng | 45/45 | Không lỗi import/vòng import gây lỗi khởi tạo |
| Parse grammar Python 3.10 | 80/80 file | Tương thích cú pháp; chưa chạy runtime 3.10 |
| `python -m tests.tools.trace --log logs/PART1_PART2_run2_a.log --msg ae30c8` | 0 | 113 sự kiện, origin=N6, có hop/DUP |
| `python -m tests.tools.show_chat --log logs/PART1_PART2_run2_a.log --node 0 --last 1` | 0 | Hiển thị đúng “Kiểm tra tích hợp 👋”, height=1 và hash từ log |
| `python -m tests.tools.show_state --log logs/PART1_PART2_run2_a.log --node 0 --account alice` | 0 | nonce=1, Unicode đúng, state hash khớp |
| `python -m src.main --config config/scenarios/t1_normal.json` | **2** | Chỉ rõ thiếu build_node/Node/Consensus Người 3; không fallback sang mock |
| Kiểm tra source Node import sim/net | 0 | Không có |
| `git diff --check` và kiểm tra phạm vi stage | 0 | Không lỗi, không stage log/cache/backup/prompt |

Output chương trình kiểm tra tích hợp:

```text
mode: PART1_PART2_CERTIFICATE_FIXTURE_ONLY; consensus: PENDING
byte-identical logs: True
same finalized state hashes: True
different seed changes logs: True
signed fixture synchronized to 10 nodes: True
```

SHA-256 log kiểm tra với seed 42: `472a2b016dc5d25f1868767ed4098fc6fe1e0046f49b58290c80e32683645b2e`, giống nhau giữa hai process có PYTHONHASHSEED khác nhau. Các log/summary và output thô được giữ local trong `logs/`, `logs/summaries/part1_part2_*`; không commit.

17 test mới kiểm tra: TX thật và State/pool riêng; Envelope/msg_id và roundtrip; snapshot gói đang chờ; payload callback không làm đổi forwarding; chữ ký hỏng cho TX/Vote/Proposal; WRONG_DOMAIN/tamper với Ed25519; vote/proposal equivocation ký hợp lệ; sync qua mạng và log Unicode; certificate thiếu/hỏng/list lệch; thiếu keybook; GET_VOTES/VOTES; drop/duplicate sau-trước GST; reorder không đổi ID; payload dư byte; workload burst/replay; NodeEnv/Verdict. Một số test gom nhiều nhánh liên quan trong cùng test method.

**Giới hạn:** ChainRulesNode ở tests là bộ ghép kiểm thử không có consensus. Certificate fixture có đủ 7 PRECOMMIT ký thật được tạo chủ động trong test, không được coi là kết quả đồng thuận. T1–T8/X1/X2 thật, safety/liveness, block builder, lock/round, vote counting và liveness sau GST vẫn **CHƯA THỂ KIỂM THỬ**, do Người 3 chưa có mã. Không chạy tests.run_all rỗng rồi tính PASS.

## E. Hướng dẫn Người 3 tiếp tục

1. Giữ nguyên các thành phần Core/Execution/Validation đã có. Implement `build_node(node_id,env,behavior,config)` và các callback NodeCallbacks; dùng Protocol NodeEnv, không import sim/net.
2. Tạo State, TxPool, Ledger, SyncManager và ChatQuery riêng từng node. Tạo public keybook validator/user từ seed và accounts của workload. Node chỉ giữ private key của chính nó. Quorum dùng `2*f+1` theo cấu hình n=3f+1.
3. Route message theo kind, phân biệt `message.origin` với `from_peer`. Client TX có from_peer=node_id. Chỉ ACCEPT khi validation thành công. Dùng BODY_REQUEST/BODY theo header hợp lệ; không gossip BODY.
4. Block Builder dùng TxPool.select_for_block, executor thực thi thử trên State.clone, dừng tại TX đầu tiên quá giới hạn 4096 byte; dựng/sign Header và Proposal bằng API có sẵn. Không thay đổi thông số README.
5. Consensus implement các round/timeouts/lock/valid_value/POL/jump-round, xác minh và đếm vote qua keybook; ký vote bằng khóa node. Chỉ append khi certificate đủ quorum, validate block và cập nhật state/pool đúng một lần.
6. Route STATUS/GET_BLOCKS/BLOCKS/GET_VOTES/VOTES qua SyncManager; gửi STATUS mỗi 2000ms bằng env timer. Callback sync phải cập nhật view/height/round và bỏ timer cũ khi bắt kịp chain.
7. Gắn fault callbacks, gọi hook đúng nơi. Không dùng fixture hoặc ChainRulesNode từ tests làm production build_node. Với invalid proposal và đề xuất lại block đã khóa, hoàn thiện callback dựa trên Block Builder.
8. Phát log TX_APPLIED/FINALIZE như hợp đồng trên. Expose finalized_chain không gồm genesis và final_state_hash thật. CLI đã tự gọi schedule_workload sau khi đăng ký node; không lập lịch workload lần hai.
9. Hoàn thiện vote_counter, invariants, run_all và e2e; chạy T1–T8 cùng X1/X2 thật. T8 cần chạy cả T1 và T7, so byte log và state hash. Chỉ sau đó mới nghiệm thu safety/liveness.

Lệnh kiểm tra hiện chạy được:

```powershell
$env:PYTHONIOENCODING = 'utf-8'
python -m pip install -r requirements.txt
python -m compileall -q src tests
python -m unittest discover -s tests/unit -p 'test_*.py' -v
python -m tests.check_part1_part2
```

## F. Việc còn thiếu, ưu tiên và PR

| Hạng mục | Phụ trách | Ưu tiên / trạng thái |
|---|---|---|
| Node orchestration, build_node | Người 3 | P0 – thiếu, chặn CLI blockchain thật |
| Consensus, VoteCounter, View, Block Builder | Người 3 | P0 – file còn rỗng |
| Invariants, tests.run_all, T1–T8/X1/X2 e2e | Người 3, nhóm phối hợp | P0 – chưa thể chứng minh safety/liveness |
| Callback invalid block và locked proposal equivocation | Người 3 cùng Người 1/2 | P1 – cần block builder/state tương ứng |
| Ký sai domain TX bằng khóa user kiểm soát | Người 2/3 cùng workload | P1 – adapter validator không sở hữu khóa user |
| Runtime Python 3.10 | Nhóm/CI | P2 – mới kiểm cú pháp, runtime đã chạy 3.11.8 |

Đã rà diff, giữ nguyên source còn dở của Người 3 và toàn bộ test Người 1/2; thay đổi Phần 2 chỉ giới hạn ở interface/validation lỗi dữ liệu và log viewer đã liệt kê. Không force-push, không tự merge main, không tự push.

Sau khi người dùng cho phép:

```powershell
git push -u origin integration/part1-part2
```

Trên GitHub mở PR **base: main**, **compare: integration/part1-part2**. Tiêu đề gợi ý: `Integrate deterministic simulation with chain rules`. Nội dung nêu snapshot transport, workload ký thật, SyncManager và NodeEnv; validation 73 tests + determinism; ghi rõ consensus/e2e còn PENDING. Không đưa backup branch, log, bytecode hoặc prompt vào PR.
