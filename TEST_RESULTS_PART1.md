# Kết quả kiểm tra Phần 1 – chỉ cho môi trường mô phỏng

Ngày bàn giao: 04/11/2026.

## Kết quả sau tích hợp trong workspace (thay cho baseline của ZIP)

- `python --version`: **exit 0**, `Python 3.11.8` trên Windows.
- `python -m pip install -r requirements.txt`: **exit 0**, đã có `cryptography 47.0.0`.
- `python -m compileall -q src tests`: **exit 0** sau khi sửa f-string lỗi trên Python 3.11.
- `python -m unittest discover -s tests/unit -p 'test_part1_environment.py' -v`: **exit 0**, **27/27 PASS**, output `Ran 27 tests`, `OK` (13 test nền và 14 test bổ sung).
- Đã chạy riêng CLI `--smoke-env` với 10 cấu hình: `t1`–`t8`, `x1`, `x2`: **exit 0 từng lệnh**. Summary ghi `mode=ENV_SMOKE_ONLY`, `environment_ok=true`, `converged=null`; **không có nghĩa** blockchain test PASS.
- `python -m tests.check_determinism --config config/scenarios/t1_normal.json --smoke-env`:
  - Log hai lần chạy cùng seed giống hệt từng byte: **TRUE**.
  - Seed khác làm thay đổi log: **TRUE**.
  - Kiểm tra state hash blockchain: **CHƯA ÁP DỤNG**, vì smoke node chỉ chứa trạng thái giả.
- Đã kiểm tra topology có 10 node, 20 cạnh, mỗi node 4 peer; kiểm tra độ trễ liên kết sau GST <= Delta; kiểm tra duplicate gossip, rate limit/block/unblock, timer replay.
- Đã chạy determinism smoke trên cả `t1_normal.json` và `t7_byzantine_equivocate.json`: **exit 0**. Output thực tế:

```text
byte-identical logs: True
same final state hash: NOT_APPLICABLE_ENV_SMOKE
different seed changes logs: True
```

- Parse **76 file Python** với `ast.parse(..., feature_version=(3, 10))`: **exit 0**. Chưa chạy runtime Python 3.10; runtime thực tế là 3.11.8.
- So log T1 giữa hai process với `PYTHONHASHSEED=1` và `98765`: **exit 0**, cùng SHA-256 `c901164ff30c890c0b13f604fa32e714d3dfd954e0742680112f1d8d8042147b`.
- Trace `--msg 3fa4eb` trên `logs/T1_04112026_033015.log`: **exit 0**, 111 sự kiện, `origin=N0`, có hop và DUP. Tên log là lần chạy thực tế, có thể khác khi chạy lại.
- Log mẫu có **448 dòng**: SIM_START=1, SEND=124, DELAY=110, RECV=124, DUP=88, SIM_END=1. Đã xác nhận seq tăng liên tục, thời gian ảo không giảm và summary tồn tại.
- CLI thật riêng cho T1–T8 (không `--smoke-env`): **exit 2 từng lệnh**, báo thiếu `src.node.node.build_node` và `src.core.user.schedule_workload`: **PENDING INTEGRATION**, không tính vào test passed.
- Diff README gốc, source và test Người 2/3: **exit 0**, không thay đổi. `git diff --check`: **exit 0**.

Output đầy đủ từng lệnh và exit code lưu local tại `logs/summaries/part1_validation.json`, `part1_extended_validation.json`, `part1_hashseed_validation.json`; các artifact này được ignore và không commit.

14 test bổ sung kiểm tra RNG có trạng thái theo nhãn, timer hủy và thứ tự đồng thời, dừng theo height, giới hạn thời gian/quá khứ, REJECT/IGNORE không forward, BODY trực tiếp, outbound rate limit và log, cấu hình link sai, ID/Verdict, sửa chữ ký một lần và tái tạo ID, từ chối ID cũ, thiếu callback báo lỗi, cấu hình scenario và override node lỗi.

Smoke chỉ phát 4 TX tổng hợp; không thực thi workload có chữ ký, burst X1, replay transaction T4 hay hook tạo vote/proposal T7. T5 smoke không dùng để kết luận liveness sau GST. Delay sau GST và BLOCK/UNBLOCK được kiểm chứng riêng trong unit tests.

## Chưa được xác nhận (sau khi ghép)

- T1–T8 của đề bài với chữ ký thật, state thật, voting thật; không đánh dấu PASS trước khi chạy.
- Điều kiện safety/liveness của consensus, chứng nhận PRECOMMIT, hợp lệ giao dịch và đồng bộ block.
- `--smoke-env` không thay thế bài trình diễn blockchain thật.
- `tests/run_all.py`, `tests/e2e/*` và các unit test Người 2/3 đang rỗng. Không chạy file rỗng rồi ghi nhận là PASS.

## Chạy kiểm tra nhanh

```bash
python -m unittest discover -s tests/unit -p 'test_part1_environment.py' -v
python -m src.main --config config/scenarios/t1_normal.json --smoke-env
python -m tests.check_determinism --config config/scenarios/t1_normal.json --smoke-env
```
