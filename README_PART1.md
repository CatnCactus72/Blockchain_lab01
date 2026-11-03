# Phần 1 – Môi trường mô phỏng, mạng, logging, fault injection

**Mục tiêu:** Đây là phần code được giao cho Người 1, tách biệt với luật blockchain (Người 2) và consensus/node (Người 3). Mọi comment trong source code đều viết tiếng Việt. **Chưa phải bản Lab 01 hoàn chỉnh** nếu chưa ghép 2 phần còn lại.

## Đã hiện thực

- Đồng hồ ảo nguyên mili-giây; event queue với `(time, seq)`; RNG con tái lập từ seed.
- `env.rng(*labels)` giữ trạng thái `random.Random` theo từng luồng; timer hỗ trợ hủy bằng token; dừng ngay khi mọi node trung thực đạt height đích.
- Topology 10 node N0..N9, 20 liên kết hai chiều, 4 peer mỗi node; có kiểm tra liên thông.
- Phân phối gói qua liên kết, pre-GST có drop/dup/delay, post-GST đảm bảo mỗi gói được giao có delay không vượt `Delta` trong điều kiện giới hạn mạng đã cấu hình.
- Gossip chỉ cho `TX`, `PROPOSAL`, `PREVOTE`, `PRECOMMIT`, ID xuyên các hop, seen-id và forward sau ACCEPT.
- Rate limit gửi 300 gói/s; recv threshold 200 gói/1000 ms mỗi peer, chặn 3000 ms và tự mở khi hết hạn.
- Log `MM:SS:mmm seq=... node=... ev=... h=...`, thứ tự trường cố định, ghi và so byte.
- Lớp hành vi lỗi: silent, duplicate/replay, bad signature, equivocation, invalid block; những thao tác phải **ký lại chữ ký hợp lệ** được ủy quyền thông qua callback node của Người 2/3.
- Cấu hình `base`, `topology`, `workload`, T1–T8, X1–X2, công cụ `trace`, `check_determinism`.
- CLI chấp nhận `--faulty 2 5 8` hoặc `--faulty N2 N5 N8`, kiểm tra ID tồn tại, cấu hình và hạn mức trước khi chạy. `.gitignore` loại cache, môi trường ảo, nguồn giải nén tạm và log thử nghiệm.

## Kiểm tra độc lập không cần code Người 2/3

```bash
python -m unittest discover -s tests/unit -p 'test_part1_environment.py' -v
python -m src.main --config config/scenarios/t1_normal.json --smoke-env --out logs
python -m tests.check_determinism --config config/scenarios/t1_normal.json --smoke-env
python -m tests.tools.trace --log logs/<tên_file>.log --msg <6_ký_tự_đầu_id>
```

**Quan trọng:** `--smoke-env` chạy node GIẢ, chỉ xác minh simulator/network/log có hoạt động. Nó không chạy BFT, không thực thi transaction có chữ ký và tuyệt đối không được ghi là T1–T8 PASS.

## Chạy thật sau khi ghép

```bash
python -m src.main --config config/scenarios/t1_normal.json
```

Lệnh này yêu cầu hai hàm do các thành viên khác tạo:

```python
# src/node/node.py – Người 3
build_node(node_id: str, env, behavior, config: dict) -> Node

# src/core/user.py – Người 2 (hoặc phối hợp Người 3)
schedule_workload(simulator, config: dict, root_path) -> None
```

Và các method Node: `on_start()`, `on_message(from_peer, message)`, `on_timer(timer_name)`, `finalized_chain()`, `final_state_hash()`.

Đọc `INTEGRATION_HANDOFF.md` để biết giao diện chính xác, cách gọi behavior, danh sách file và các giới hạn. Kết quả đã chạy nằm trong `TEST_RESULTS_PART1.md`.

Sau tích hợp: **27/27 unit tests PASS**; smoke của 10 cấu hình chạy được. T1–T8 thật còn **PENDING INTEGRATION** vì các file Core/Node/Consensus hiện rỗng. Xem báo cáo thực thi `PART1_CODEX_REPORT.md`.
