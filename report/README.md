# Bàn giao báo cáo Lab01

Bản PDF hoàn chỉnh: `output/pdf/REPORT.pdf` (tính từ thư mục gốc dự án).
Báo cáo có 11 trang PDF: bìa không in số trang, mục lục đánh số i,
và 9 trang nội dung đánh số 1-9. Báo cáo viết bằng tiếng Việt, dựa trên mã nguồn commit `add5f32`
và kết quả kiểm thử ngày 11/11/2026. Không thay đổi mã trong `src/` hay `tests/`.

## Các file cần giữ để sửa và biên dịch

- `main.tex`: nội dung báo cáo, hai sơ đồ TikZ và tài liệu tham khảo.
- `report/cover.tex`: bìa có viền đôi, tên trường/khoa/môn học, giảng viên và sinh viên.
- `report/frontmatter.tex`: mục lục tự động, tóm tắt và bảng phân công.
- `report/team.tex`: họ tên, MSSV ba thành viên.
- `report/results.tex`: bảng số liệu và phân tích kết quả.
- `report/figures/finalization.png`: hình dùng trong báo cáo; bản PDF cùng tên là hình vector.
- `report/evidence/scenario_metrics.json`: số liệu 15 lượt chạy và SHA-256 log gốc.
- `report/evidence/test_results.txt`: kết quả 127 PASS, không FAIL/ERROR.
- `report/build_results.py`: tái tạo bảng và biểu đồ từ bằng chứng đã lưu.
- `.vscode/settings.json`: recipe XeLaTeX hai lượt, PDF viewer trong IDE.

## Biên dịch và xem trong VS Code

Mở `main.tex`, nhấn **Ctrl+Alt+B** để build, **Ctrl+Alt+V** để xem PDF.
Recipe `XeLaTeX - REPORT.pdf` chạy hai lượt để cập nhật số trang và trích dẫn.
Máy cần XeLaTeX/MiKTeX và font Times New Roman, Arial, Consolas.
Không cần chạy Python khi chỉ sửa nội dung báo cáo.

Chạy thủ công tại thư mục gốc, lặp lệnh XeLaTeX hai lần:

```powershell
New-Item -ItemType Directory -Force output/pdf | Out-Null
xelatex -synctex=1 -interaction=nonstopmode -file-line-error -halt-on-error -jobname=REPORT -output-directory=output/pdf main.tex
```

Chỉ khi muốn dựng lại bảng/biểu đồ từ dữ liệu đã lưu, chạy
`python report/build_results.py` (cần matplotlib), rồi biên dịch LaTeX.
Script này không chạy lại simulator hoặc sửa source/test.

## Kiểm tra bàn giao

- PDF có 11 trang vật lý; đã kiểm tra trực quan bìa, mục lục và 9 trang nội dung.
- Nội dung bắt đầu từ trang 1, mục lục trỏ đến đúng 9 mục chính; sinh viên xếp tăng dần MSSV ở cả bìa và bảng phân công.
- Đã đối chiếu SHA-256 của 15 log gốc với số liệu đã lưu.
- Đã kiểm tra đủ họ tên/MSSV, số liệu chính, tham chiếu và số trang.
- Build XeLaTeX thành công; không còn cảnh báo tràn dòng, thiếu ký tự hoặc tham chiếu chưa giải quyết.
- Kết quả 127 PASS lấy từ lần chạy đã lưu, không chạy lại bộ test khi chỉ hoàn thiện tài liệu.
- Các giới hạn của replay workload, bad-key injection, kiểm tra tally, X1 và X2 được nêu trong báo cáo.

Trên máy này, latexmk/Perl gặp lỗi tạo thư mục trong đường dẫn có dấu;
recipe dùng XeLaTeX trực tiếp đã chạy thành công. MiKTeX vẫn in thông báo
về phiên bản Windows ở stderr dù XeLaTeX trả exit code 0 và tạo PDF hợp lệ.

Log mô phỏng gốc vẫn ở `tmp/pdfs/report_evidence/`; không xóa vì là bằng chứng
kiểm thử. Khi chuẩn bị bài nộp, đưa log/summary được chọn vào `logs/` và đặt
bản PDF tại vị trí `REPORT.pdf` theo cấu trúc nộp của đề. Không cần nộp các
file phụ LaTeX (`.aux`, `.log`, `.out`, `.synctex.gz`) hay ảnh kiểm tra layout.

Các file báo cáo được quản lý trên nhánh `docs/lab01-project-report`.
Commit báo cáo chỉ gồm nguồn LaTeX, cấu hình IDE, số liệu tổng hợp, hình và PDF;
không kèm log tạm hoặc file phụ biên dịch.

## Quy định số trang và nguồn tham khảo bìa

Đề Lab01 chỉ ghi `REPORT.pdf (max 10 pages)`, không bắt buộc bìa/mục lục
và không nói hai trang đó được miễn tính. Bản hiện tại tách cách đánh số
theo yêu cầu của nhóm, nhưng vẫn có 11 trang PDF. Không được coi việc đánh
số riêng là xác nhận đáp ứng giới hạn của đề; cần xác nhận cách tính với
giảng viên hoặc rút gọn tổng số trang trước khi nộp nếu giới hạn áp dụng toàn PDF.

Tham khảo phần tên trường/khoa trong tài liệu hướng dẫn mẫu LaTeX tại
[trang biểu mẫu chính thức của Khoa CNTT](https://www.fit.hcmus.edu.vn/vn/Default.aspx?tabid=1064).
Đây là tài liệu dành cho đề tài tốt nghiệp, không phải mẫu bắt buộc của môn Blockchain.
Bìa được tự soạn bằng TikZ/LaTeX, với thông tin giảng viên và môn học do nhóm cung cấp.
