# Nghiệm thu Subject Knowledge Hub trên máy của bạn

Đọc [test-report.md](test-report.md) để phân biệt phần đã được agent kiểm thử với phần cần bạn xác minh. Các bước dưới đây dùng PDF bạn tự upload, tài khoản local và OpenAI thật nếu đã cấu hình key. Không coi fixture/fake provider là bằng chứng cho chất lượng API thật.

## Khởi động

Mở terminal trong thư mục source. Trên PowerShell:

```powershell
Copy-Item .env.example .env
notepad .env
docker compose up --build -d
docker compose ps -a
```

Trên Bash/WSL, thay `Copy-Item` bằng `cp .env.example .env`, dùng trình soạn thảo để điền `OPENAI_API_KEY`, rồi chạy cùng lệnh Compose. Không đưa key vào frontend.

Chờ `web`, `api`, `worker`, `postgres`, `redis` healthy; `migrate` hoàn tất với mã 0 là đúng. Mở [http://localhost:3000](http://localhost:3000). API docs: [http://localhost:8000/docs](http://localhost:8000/docs).

Nếu chưa sẵn sàng:

```bash
docker compose logs --tail 100 migrate api worker
```

## 10 bước dùng PDF của bạn

| Bước | Thao tác | Kết quả cần đối chiếu |
| --- | --- | --- |
| 1 | Đăng ký/đăng nhập; tạo môn `Học máy`, rồi chọn môn | Tên môn hiện rõ; khi chưa chọn môn, upload/chat bị khóa kèm hướng dẫn |
| 2 | Tab `Tài liệu`: chọn/kéo thả PDF có text | Tiến độ tải lên tách khỏi `queued → parsing → chunking → embedding → ready`; lỗi có nguyên nhân cụ thể; F5 không mất job |
| 3 | Tab `Hỏi đáp`: hỏi một chi tiết có trong tài liệu | Có câu trả lời với `[1]`/thẻ nguồn; click mở đúng file, phiên bản và trang PDF vật lý |
| 4 | Hỏi một thông tin chắc chắn ngoài tài liệu | Báo chưa có bằng chứng phù hợp; không tự tìm Internet hoặc tự thêm nguồn |
| 5 | Upload PDF thứ hai với thông tin mới, rồi hỏi thông tin đó | Chỉ tài liệu mới được xử lý; tài liệu cũ vẫn dùng được; câu trả lời có nguồn mới |
| 6 | Tạo/chuyển sang môn `Cơ sở dữ liệu`; thử câu hỏi trước | Conversation thay theo môn; không lấy nguồn/lịch sử từ `Học máy`; môn trống không gọi model vô ích |
| 7 | Về `Học máy`, thay một PDF bằng phiên bản sửa fact; sau đó xóa tài liệu khác | Bản cũ vẫn dùng trong lúc bản mới xử lý; chỉ đổi active khi thành công; hỏi lại không lấy evidence/cache đã thay/xóa; lịch sử hiển thị nhãn nguồn cũ |
| 8 | Chọn `Trợ lý tài liệu`; yêu cầu liệt kê, đọc 1–2 trang, tóm tắt phạm vi | Tool trace có tên/tham số/kết quả; phạm vi đúng môn; tóm tắt dài phải chủ động bắt đầu/xác nhận trên UI |
| 9 | Tab `Đánh giá`: import JSONL, map document keys, chạy bộ nhỏ, tải báo cáo | Dataset được validate; job có trạng thái thật; export JSON/CSV/Markdown có kết quả/lỗi; đáp án chuẩn không xuất hiện như tài liệu được index |
| 10 | Chạy `docker compose down`, rồi `docker compose up -d`; mở lại trình duyệt | Tài khoản, môn, PDF, job và lịch sử còn; có thể tiếp tục hỏi |

PDF được hỗ trợ mặc định tối đa **100 MiB, 1.200 trang**. Giới hạn hiện trên UI lấy từ backend; đổi `MAX_UPLOAD_MB`/`MAX_PDF_PAGES` trong `.env` rồi recreate API/worker/web. Trang nguồn là thứ tự vật lý bắt đầu từ 1, có thể khác số in trên sách.

## Kiểm tra lỗi và cô lập dữ liệu

- Upload lại cùng file, kể cả hai tab đồng thời: nhận diện trùng, không tăng bản active/chunks vô ích.
- Upload file rỗng/hỏng, PDF có mật khẩu, PDF scan toàn bộ: nhận lỗi hoặc `needs_ocr` rõ ràng; không `ready` giả, không loading vô hạn.
- Với PDF hỗn hợp, đối chiếu số trang có text và cảnh báo trang bỏ qua. V1 không OCR hay hiểu hình/công thức phức tạp.
- Dùng cửa sổ ẩn danh với tài khoản thứ hai: tài khoản đó không thấy môn của tài khoản đầu. Nếu bạn biết gọi API, thay subject/document/job/conversation ID bằng ID của người khác; backend phải từ chối, kể cả endpoint PDF.
- Upload file sửa có lỗi: phiên bản active cũ phải tiếp tục truy xuất được.
- Khi job ingestion chạy, thử `docker compose restart worker`; chờ reconciliation và theo dõi trạng thái. Đối chiếu cuối cùng không có chunks nhân đôi.
- Xóa key rồi recreate API/worker: trạng thái cấu hình thiếu phải hiện rõ. Sau đó điền lại key và recreate để tiếp tục; không dán key vào ảnh/log gửi người khác.

## Bộ đánh giá nhỏ của riêng bạn

Viết JSONL UTF-8, mỗi dòng là một object. Ví dụ này chỉ mô tả schema; thay câu hỏi, đáp án và số trang theo PDF thật:

```json
{"id":"my-001","question":"Tài liệu định nghĩa overfitting như thế nào?","reference_answer":"Đáp án bạn đã kiểm tra trong PDF.","answerable":true,"evidence":[{"document_key":"ml_notes","page_start":3,"page_end":3}],"tags":["vi","single_document"]}
```

Trong tab Đánh giá, map `ml_notes` đến PDF tương ứng. Không chọn một PDF khác chỉ để bỏ qua lỗi mapping. Thêm câu ngoài phạm vi với `answerable:false` và `evidence:[]`. Bắt đầu với 2–5 câu để kiểm tra pipeline và usage, sau đó mới mở rộng. Chạy dense/hybrid hoặc generation có thể phát sinh API usage; giới hạn tokens/calls vẫn áp dụng.

[evaluation.md](evaluation.md) có schema đầy đủ, fixture regression, CLI và QASPER. QASPER tiếng Anh dùng evidence theo đoạn, không phải bài test parser/trang PDF tiếng Việt.

## Ghi kết quả nghiệm thu

Dùng ba nhãn: **PASS** khi đã thao tác và có bằng chứng, **FAIL** khi kết quả khác kỳ vọng, **UNVERIFIED** khi chưa chạy hoặc thiếu điều kiện. Ghi tên PDF không nhạy cảm, số trang, cấu hình model/budget, thời điểm, số câu, lỗi và ảnh nguồn đối chiếu. Latency/chi phí chỉ điền sau khi có số liệu thực.

Live smoke tối thiểu cần một PDF Việt và một PDF Anh có text, 10 câu gồm có nguồn/không nguồn/nối tiếp, cùng 5 tác vụ tools đại diện. Không dùng kết quả fake embeddings của fixture 1.000 trang để đánh dấu live OpenAI 1.000 trang là PASS. Bài live lớn và benchmark trả phí cần estimate/ngân sách riêng.

## Tắt, sao lưu, khôi phục

`docker compose down` giữ dữ liệu. **Không dùng `down -v` trong nghiệm thu restart** vì lệnh đó xóa volumes.

Nếu có Python 3.10+ trên máy, chạy `python scripts/backup.py --output backups` (Windows có thể dùng `py -3`). Script tạm dừng các dịch vụ ghi, sao lưu PostgreSQL/PDF rồi bật lại. Xem [README](../README.md#backup-and-restore) trước khi khôi phục vì restore sẽ thay thế dữ liệu hiện tại và cần flag `--replace-data`.
