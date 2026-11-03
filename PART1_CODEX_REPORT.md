# Báo cáo bàn giao tích hợp Phần 1

Ngày: 04/11/2026 (Asia/Bangkok).

## Kết quả

Đã tích hợp mã nguồn Phần 1 từ ZIP nhúng, sửa lỗi và kiểm thử thực tế trên branch `feature/lab01-part1-environment`. Không merge vào `main`. Commit tích hợp dùng thông điệp `feat(lab01): add deterministic simulation environment`; lấy mã commit bằng `git log -1 --oneline`.

Đầu phiên, chỉ có prompt chưa được theo dõi; các file code/config trong bộ khung đều rỗng. Đã so từng file trước khi copy, không ghi đè file có nội dung khác. `README.md`, `src/core/`, `src/crypto/`, `src/execution/`, `src/node/`, `tests/e2e/`, test/công cụ Người 2/3 giữ nguyên so với HEAD ban đầu.

Payload đủ **50 đường dẫn**, SHA-256 xác nhận:

```text
4a82345017e7a7dd90b68b3c03e44d0cea616f8b21e674c3be3896355eb1b764
```

Không có `Lab01 (2).pdf` trong workspace; đặc tả đối chiếu theo README gốc và toàn bộ hướng dẫn A–F của prompt. Nguồn tạm `part1_import/` được giải nén riêng, không stage. Lệnh terminal dọn thư mục này kèm stage bị kiểm duyệt tự động từ chối với lý do `blocked by policy`; không thực hiện xóa, giữ thư mục được ignore. Prompt base64 giữ nguyên ở local và loại khỏi stage bằng `.git/info/exclude`.

## File đã thêm/sửa

| Nhóm | File và chức năng |
|---|---|
| Mô phỏng | `src/sim/{clock,event_queue,rng,simulator}.py`: đồng hồ ảo, queue, RNG, NodeEnv |
| Mạng | `src/net/{topology,link,rate_limit,gossip,network}.py`: topology, delay/drop/dup, hạn mức, dedup, transport |
| Log | `src/logsys/{event,logger,summary}.py`: chuẩn log, log xác định, summary |
| Fault | `src/faults/{base,silent,bad_signature,replay,equivocate,invalid_block}.py`: hook lỗi, callback tích hợp |
| CLI | `src/main.py`: deep-merge, validation, override, ghép factory, chạy và báo kết quả |
| Config | `config/{base,topology,workload}.json`, 10 file `config/scenarios/*.json` |
| Kiểm thử | `tests/helpers_env.py`, `tests/unit/test_part1_environment.py`, `tests/check_determinism.py`, `tests/tools/trace.py` |
| Package | `__init__.py` mới trong sim/net/logsys/faults và tests/unit/tools |
| Bàn giao | `README_PART1.md`, `INTEGRATION_HANDOFF.md`, `TEST_RESULTS_PART1.md`, báo cáo này |
| Hỗ trợ | `requirements.txt` thêm `cryptography`; `.gitignore` loại cache, `.venv`, nguồn import và log thử; hai `.gitkeep` giữ thư mục logs/summaries |

## Lỗi đã sửa so với payload

1. F-string dùng dấu nháy lồng trùng loại trong `tests/check_determinism.py` gây SyntaxError trên Python 3.11: dùng biến trung gian, giữ yêu cầu Python 3.10+.
2. `env.rng(*labels)` tạo lại RNG mỗi lần: cache `random.Random` theo node và nhãn để tiếp tục luồng cũ, độc lập các luồng khác.
3. Simulator ưu tiên MAX_TIME trước khi nhận biết đạt height: kiểm tra TARGET_HEIGHT trước sự kiện tiếp theo. Kiểm tra giới hạn thời gian, height và đăng ký Env trước khi chạy.
4. Fault sửa payload/chữ ký nhưng giữ ID cũ: `refresh_wire_message` yêu cầu callback Core tính lại ID chuẩn khi cần; thiếu callback báo `NotImplementedError`, adapter không đổi ID báo `ValueError`.
5. Bad signature có thể sửa ở cả hook tạo vote/proposal và outbound, đảo byte hai lần phục hồi chữ ký: chỉ sửa outbound, cache bản sửa theo ID, không sửa lại bản đã phát khi quay về.
6. Link có trễ sau GST vượt Delta chỉ báo lỗi ngẫu nhiên khi chạy: kiểm tra cận trên ngay trong constructor; từ chối extra delay âm.
7. CLI `--faulty 2 5 8` trước đây không quy về N2/N5/N8, ID không tồn tại có thể bị bỏ qua: chuẩn hóa và kiểm tra topology, ID trùng, f, seed, thời gian, xác suất, hạn mức, fault params.
8. Log height không áp dụng dùng `h=-` theo README. Trace in thêm `origin`. Summary từ chối tập node trung thực rỗng hoặc ID không tồn tại thay vì kết luận hội tụ rỗng.

## API và cách ghép Người 2/3

- `VirtualClock.now()/advance_to(t)`, `EventQueue.push()/pop()/peek()`, `SeededRNG.child(*labels)/stream()` cung cấp nền xác định.
- `Simulator.create_env(node_id)`, `register_with_env(node_id,node,env)`, `schedule(at_ms,name,callback,...)`, `run(max_virtual_time_ms,target_height,honest_nodes)` điều phối vòng lặp.
- `SimNodeEnv.now()`, `peers`, `rng(*labels) -> random.Random`, `send(peer,message,h=-1,r=None)`, `gossip(message,h=-1,r=None)`, `log(ev,h=-1,**fields)`, `set_timer(name,delay_ms) -> token`, `cancel_timer(token)` là hợp đồng NodeEnv.
- Người 3 cung cấp `src.node.node.build_node(node_id,env,behavior,config)`. Node có `on_start`, `on_message`, `on_timer`, `finalized_chain`, `final_state_hash`; chuỗi là danh sách dict height/hash không gồm genesis và có thể JSON serialize.
- Người 2/3 cung cấp `src.core.user.schedule_workload(sim,config,root_path)` để tạo, ký và đưa giao dịch thực vào node.
- Core/Wire cung cấp `.kind`, `.origin`, `.msg_id` hoặc dict tương đương. ID dùng canonical encoding từ Core; mạng không hash JSON. `Verdict` nhận chuỗi, enum hoặc object có status/kind ACCEPT/REJECT/IGNORE.
- Network tự gọi `behavior.on_send`, kể cả forwarding; Node không gọi lần hai. Node gọi `on_receive` trước validation và `on_make_vote/proposal` khi tạo. Timer `fault:` phải gọi `behavior.on_timer` rồi gửi các cặp peer/message trả về.
- Callback `rebuild_wire_message`, `resign_wrong_domain`, `tamper_signed_message`, `make_conflicting_vote`, `make_conflicting_proposal`, `make_invalid_proposal` cần khóa/encoding thật của Người 2/3. Chưa có thì báo **PENDING INTEGRATION**, không giả phiếu/certificate.

Chi tiết trong `INTEGRATION_HANDOFF.md`. Mạng không chứa BFT và không xác minh chữ ký. Delay sau GST là cận trên từng liên kết kể từ lúc transmit; thời gian chờ rate limit và peer blocking vẫn có thể ảnh hưởng nhận tin.

## Kiểm thử thực tế

Runtime `Python 3.11.8`; pip requirements exit 0, `cryptography 47.0.0` đã có. Compileall exit 0; **27/27 unit tests PASS** (exit 0). 76 file Python parse được với grammar 3.10; chưa xác nhận runtime 3.10 trên máy này.

Smoke cả T1–T8 và X1/X2 exit 0. Determinism smoke trên T1 và T7 exit 0, output:

```text
byte-identical logs: True
same final state hash: NOT_APPLICABLE_ENV_SMOKE
different seed changes logs: True
```

Hai process có PYTHONHASHSEED=1 và 98765 cũng thu cùng hash log T1 `c901164ff30c890c0b13f604fa32e714d3dfd954e0742680112f1d8d8042147b`. Log có SIM_START/SIM_END, seq tăng, thời gian ảo không giảm, SEND/RECV và summary. Trace gói `3fa4eb` in 111 sự kiện, origin N0, các hop và DUP; exit 0.

Đã chạy CLI thật riêng cho T1–T8: **exit 2**, thông báo `Chưa ghép phần Người 2/3. Cần src.node.node.build_node và src.core.user.schedule_workload; dùng --smoke-env để tự kiểm môi trường.` Đây là **PENDING**, không phải T1–T8 PASS. `tests/run_all.py`, test e2e và unit test Người 2/3 đều rỗng nên không lấy exit 0 của file rỗng làm kết quả kiểm thử.

Smoke chỉ tạo 4 TX tổng hợp. State hash thật, cryptography, BFT safety/liveness, transaction replay, burst, equivocation có chữ ký và certificate chưa được kiểm chứng. Chữ ký/ID tổng hợp trong `tests/helpers_env.py` chỉ phục vụ hạ tầng.

Lệnh, exit code, output và giới hạn chi tiết: `TEST_RESULTS_PART1.md`. Output thô lưu local ở `logs/summaries/part1_*validation.json`, không commit. `git diff --check` đạt; kiểm tra diff các đường dẫn bảo vệ không có thay đổi.

## Review và chạy lại

```powershell
$env:PYTHONIOENCODING = 'utf-8'
python -m pip install -r requirements.txt
python -m compileall -q src tests
python -m unittest discover -s tests/unit -p test_part1_environment.py -v
python -m src.main --config config/scenarios/t1_normal.json --smoke-env
python -m tests.check_determinism --config config/scenarios/t1_normal.json --smoke-env
python -m tests.tools.trace --log logs/<file>.log --msg 3fa4eb
git diff main...feature/lab01-part1-environment --stat
git diff main...feature/lab01-part1-environment -- src/node src/core src/crypto src/execution tests/e2e README.md
```

Đổi `<file>` thành log T1 vừa tạo. Lệnh diff cuối phải không in thay đổi. Chạy thật sau khi Người 2/3 hoàn thiện factory/workload và callbacks, rồi mới chạy tests.run_all và nghiệm thu T1–T8.

## Remote, commit và PR

GitHub plugin xác nhận tài khoản `vtpy23`, repository `CatnCactus72/Blockchain_lab01` có `permissions.push=false` (pull=true). Vì vậy không thử push qua tài khoản này và chưa tạo PR; `gh` cũng chưa cài trên máy. Thay đổi được commit local trên feature branch, không đổi main.

Khi tài khoản có quyền ghi, chạy:

```powershell
git push -u origin feature/lab01-part1-environment
```

Sau đó mở PR từ branch này vào main. Nếu chưa được cấp quyền, fork repository trên GitHub rồi đẩy commit hiện tại sang fork (thay `<tai-khoan>`):

```powershell
git remote add part1-fork https://github.com/<tai-khoan>/Blockchain_lab01.git
git push -u part1-fork feature/lab01-part1-environment
```

Mở PR từ `<tai-khoan>:feature/lab01-part1-environment` về `CatnCactus72:main`, nêu rõ 27 test môi trường đạt và T1–T8 thật còn PENDING. Không merge trước khi nhóm review.
