# Kế hoạch kiểm thử và nâng cấp portfolio

Ngày lập: 2026-09-10. Định hướng: portfolio AI Engineer / Applied AI, tập trung RAG trên PDF Việt/Anh, tool calling, evaluation và backend bền vững.

Đây là kế hoạch công việc; các tiêu chí và số liệu mục tiêu dưới đây chưa phải kết quả đã đạt. Lượt lập kế hoạch không triển khai tính năng hoặc chạy API trả phí.

## Đích bàn giao

Mục tiêu đã chốt với người dùng: ứng dụng chạy được và có số liệu thực, có thể tái lập để đưa vào CV. Ưu tiên độ đúng, chất lượng retrieval/QA, latency, token usage và khả năng xử lý tài liệu. Video, kịch bản demo và case study dài không thuộc bộ bàn giao.

Release portfolio cần có:

- Một luồng chạy thật: đăng ký → tạo môn → upload → xử lý → hỏi → mở đúng nguồn.
- Vòng đời tài liệu hoạt động đúng: thay phiên bản thành công/thất bại, xóa, kiểm tra câu trả lời và nguồn lịch sử.
- Một báo cáo so sánh retrieval có dữ liệu, cấu hình, kết quả và ví dụ thất bại.
- Một thí nghiệm cải tiến có giả thuyết và kết quả trước/sau; giữ baseline nếu cải tiến không có lợi.
- CI chạy kiểm thử cần thiết, cùng bằng chứng riêng cho browser, phục hồi worker và OpenAI thật.
- README đủ để chạy ứng dụng, báo cáo benchmark ngắn có lệnh tái lập và 2–3 câu CV dựa trên kết quả đo.

## Điểm xuất phát

- Đã có các luồng sản phẩm chính, 16 bảng và 30 thao tác API trong OpenAPI bàn giao.
- Bằng chứng ngày 2026-09-09: 59 backend tests pass, 22 integration tests skipped; frontend typecheck/build pass; browser mới được liệt kê test.
- Smoke 1.000 trang hiện dùng parser/chunker thật và embedding giả, không chạy PostgreSQL/Celery/OpenAI.
- Trong lượt review ngày 2026-09-10: cú pháp 38 file Python hợp lệ; bốn test logic evaluation chạy lại thành công; 111 checksum bàn giao khớp.
- Trên máy được kiểm tra, Docker daemon chưa kết nối được; chưa có `.env`, `frontend/node_modules`, và một số Python dependencies. Đây là điều kiện môi trường cần hoàn tất khi thực hiện.
- Bộ 61 câu hỏi hiện tại chứa nhiều paraphrase của cùng fact. Giữ làm regression; không coi 61 câu là 61 quan sát độc lập về chất lượng.
- QASPER có adapter nhưng chưa có 100 ID và hash nguồn thực.

## Thứ tự triển khai

| Mốc | Công việc | Điều kiện hoàn thành | Công sức dự kiến |
| --- | --- | --- | --- |
| M0 — Baseline có thể tái lập | Dựng stack sạch, cài theo lockfile, chạy migration và bộ test hiện có | Năm dịch vụ healthy, migrate exit 0; 22 integration tests hiện có thực sự được chạy và pass | 1–2 ngày |
| M1 — Độ tin cậy và lỗi đã thấy | Kiểm thử lifecycle/phục hồi; sửa lỗi; đồng bộ cấu hình evaluation và trạng thái summary | Không có lỗi chặn sử dụng; các invariant về scope, phiên bản và phục hồi được kiểm chứng | 2–3 ngày |
| M2 — Baseline AI thật | Smoke Việt/Anh và năm tools; xây bộ đánh giá, rubric; đo baseline | Có kết quả, usage, lỗi và đánh giá nội dung; chốt cấu hình baseline trên dev | 2–3 ngày |
| M3 — Nâng cấp có bằng chứng | Cải thiện retrieval, latency hoặc token theo lỗi/số liệu ở M2; bổ sung xuất metrics cần thiết | Có so sánh trước/sau, kiểm tra chất lượng và quyết định giữ/bỏ cải tiến | 2–4 ngày |
| M4 — Ứng dụng và số liệu CV | Chạy các gate cuối, cập nhật README và benchmark, soạn câu CV | Fresh setup tái lập được; các claim trong README/CV có bằng chứng tương ứng | 0,5–1 ngày |

Ước lượng tổng: khoảng 8–13 ngày làm việc tập trung cho một người, phụ thuộc lỗi khi chạy tích hợp, thời gian xây đáp án chuẩn và quota API. Đây là ước lượng lập kế hoạch. Mốc đầu tiên cần đạt là M0–M1; công việc không phụ thuộc API tiếp tục được khi chưa có ngân sách live.

## M0 — Dựng baseline và tổ chức bằng chứng

1. Kiểm tra Docker Desktop/Linux containers; tạo cấu hình local từ `.env.example`. Stack ứng dụng và stack test dùng Compose project/volumes riêng.
2. Build từ source theo `backend/uv.lock` và `frontend/package-lock.json`. Ghi OS, Docker/Compose, runtime, package lock hashes và cấu hình không chứa secret.
3. Chạy migration từ DB rỗng, kiểm tra extension vector, schema và health checks; chạy migration lần nữa để kiểm tra tính lặp lại.
4. Chạy toàn bộ deterministic backend suite với PostgreSQL/pgvector và Redis thật, đặt `RUN_INTEGRATION=1`. Sửa nguyên nhân của từng failure; không đổi skip hoặc giảm assertion để làm xanh báo cáo.
5. Chạy frontend typecheck/build và bài browser mặc định trên stack thật.
6. Khi đưa lên Git repository, ghi commit cho mỗi lần kiểm chứng. Bản thư mục hiện được review chưa có `.git`; trước đó dùng source manifest/hash để định danh.

Lệnh tham chiếu hiện có:

```powershell
docker compose up --build -d
docker compose ps -a
docker compose -p subject-hub-test -f compose.yaml -f compose.test.yaml run --build --rm tests
```

Mỗi lần chạy lưu bằng chứng vào thư mục riêng `artifacts/runs/<run-id>/`: cấu hình đã loại secret, môi trường, lệnh, thời điểm, exit codes, JUnit, browser traces và báo cáo JSON/Markdown khi tương ứng. `docs/test-report.md` dẫn đến lần chạy mới nhất; giữ được phân biệt kết quả lịch sử, offline, PostgreSQL và live.

## M1 — Ma trận kiểm thử hệ thống

| Nhóm | Tình huống phải kiểm tra | Assertion và bằng chứng |
| --- | --- | --- |
| Auth/scope | Hai user, hai môn; đổi ID tài liệu/job/conversation/evaluation/PDF; CSRF và hết phiên | Request trái quyền bị từ chối; không có dữ liệu chéo trong payload hoặc tool output |
| Upload/parser | PDF Việt/Anh; nhiều file; file trùng đồng thời; rỗng/hỏng/mã hóa; scan/mixed; vượt byte/page limit | Job/status/error đúng; không nhân bản version/chunk; file tạm được dọn; đúng trang vật lý |
| Ingestion | Thêm PDF, timeout ở batch, retry sau lỗi; mất kết nối trước/sau checkpoint | Chỉ xử lý phần cần thiết; không nhân đôi chunks; chỉ kích hoạt index hoàn chỉnh |
| Versioning | Bản thay thế tốt/xấu; hai bản hoàn thành ngược thứ tự; xóa khi embedding/generation đang chạy | Bản tốt cũ còn dùng khi replacement lỗi; active không lùi; câu trả lời mới không dùng nguồn đã loại |
| Cache/history | Câu độc lập lặp lại; hội thoại nối tiếp; thêm/thay/xóa tài liệu | Cache đúng scope/revision; lịch sử cũ không đưa nguồn không hợp lệ vào context mới |
| Worker/Redis | Dừng/khởi động worker giữa các stage; mất broker lúc API đã commit; xóa queue test rồi phục hồi | Job tồn tại trong PostgreSQL và được phục hồi; không kẹt vĩnh viễn hoặc xử lý đồng thời một job |
| Summary | Khoảng ngắn/dài; confirmation; vượt ngân sách; restart giữa map/reduce; thay/xóa nguồn | Phạm vi được báo chính xác; checkpoint và reservations còn; nội dung cũ được gắn trạng thái |
| Tools/provider | Sai args/tool/page range; timeout/429/quota; nhiều vòng; prompt injection | Scope và ngân sách được thực thi; lỗi có mã rõ; không gọi công cụ ngoài allowlist |
| Evaluation | JSONL sai; mapping sai/stale; lexical không generation; replay; budget hết; export | Không index đáp án chuẩn; không nhân đôi result; giữ báo cáo một phần và lỗi từng câu |
| Vận hành | Down/up giữ volumes; backup rồi restore trên stack dùng dữ liệu test | Khôi phục được account, PDF bytes/hash, active version, job, hội thoại và truy xuất |
| Quy mô | 1.000 trang qua PostgreSQL; một PDF có text dài/đậm đặc hơn; 1/3/5 phiên đồng thời | Báo thời gian, RAM, queue wait, lỗi; kiểm tra facts đầu/giữa/cuối; ghi giới hạn đo được |

Kill/restart phải thực sự tác động tiến trình Celery và broker trong stack test; gọi lại hàm Python không thay thế phép thử này. Đo tại checkpoint quan sát được thay vì phụ thuộc khoảng sleep cố định. Mất queue/restore chỉ thao tác trên project test đã xác nhận.

Mở rộng browser test theo các luồng nghiệp vụ độc lập: happy path PDF/citation, version lifecycle, summary, evaluation và trạng thái phiên. Kiểm tra desktop và mobile 390px, bàn phím, loading/error/retry, console errors, lịch sử sau refresh. Không đặt quota số test hoặc coverage làm điều kiện thay cho assertion có ý nghĩa.

E2E offline cần provider xác định được, inject bằng entrypoint/harness chỉ thuộc test cho cả API và worker; vẫn đi qua HTTP, DB và queue thật. Runtime thông thường tiếp tục chỉ khởi tạo provider thật. Các bài offline và live lưu kết quả riêng.

Sửa trước hai điểm phát hiện qua source review:

- `frontend/src/Evaluations.tsx`: bỏ `top_k: 6` cố định; lấy giới hạn từ API config và cho chọn trong phạm vi hợp lệ. Kiểm tra cấu hình server thấp hơn 6, UI validation và backend validation.
- `frontend/src/Documents.tsx` và API job tương ứng: summary cũ cần document/version/range và trạng thái active/replaced/deleted rõ ràng; không trình bày như bản hiện hành. Giữ khả năng xem lịch sử theo quyền của user và chính sách hiện có.

## M2 — Chứng minh chất lượng AI

### Smoke live trước benchmark

Dùng hai PDF fixture Việt/Anh, 10 câu và năm tác vụ tools theo `scripts/live_smoke.py`, với `compose.live-smoke.yaml`. Kiểm tra câu trả lời, đoạn nguồn, trang PDF, tool được chọn, phạm vi và kết quả nhiệm vụ. HTTP 200 hoặc tên tool đúng chưa đủ kết luận hoàn thành.

Lượt lập kế hoạch chưa chốt ngân sách USD. Trước khi thực thi live cần chốt trần tổng, dùng giá cấu hình có ngày kiểm tra và dry-run dự toán. Tách allowance cho indexing, QA, tools, summary và benchmark. Lưu token/call reservations cùng usage provider trả về; lỗi timeout có thể có usage không quan sát được. Không suy ra số tiền từ token nếu chưa có bảng giá hợp lệ.

### Bộ dữ liệu portfolio

- Giữ nguyên 61 câu hiện có làm regression kỹ thuật và fixtures lifecycle.
- Bổ sung mục tiêu 100 câu trên khoảng 6–10 PDF Việt/Anh được phép sử dụng. Có văn xuôi, bảng cơ bản, nội dung nhiều trang, nguồn mâu thuẫn và câu thiếu bằng chứng.
- Phân nhóm đề xuất: 35 tra cứu trực tiếp, 20 paraphrase, 10 nối tiếp, 10 nhiều đoạn/nguồn, 5 mâu thuẫn và 20 unanswerable. Ghi ngôn ngữ, loại câu và nhóm fact riêng; điều chỉnh số lượng trước khi đóng băng tập test.
- Tách khoảng 30 dev / 70 held-out theo nhóm tài liệu/fact; mọi paraphrase của một fact ở cùng split. Đáp án và evidence cần người kiểm tra trực tiếp từ PDF. Không xem đáp án test để chọn cấu hình.
- Materialize QASPER 100 ID/hash thật và dùng collection đoạn riêng. QASPER test được giữ để báo cáo, không dùng chọn cấu hình; không suy ra chất lượng parser PDF hoặc tiếng Việt từ kết quả QASPER.

### Đo và chấm

| Phép đo | Cách thực hiện |
| --- | --- |
| Retrieval | Recall@k, precision@k, MRR; báo đơn vị trang/đoạn và số mẫu; so sánh lexical/dense/hybrid trên cùng dữ liệu/cấu hình |
| Câu trả lời | Người review chấm 0/1/2 cho sai hoặc thiếu nghiêm trọng / đúng một phần / đúng và đủ; lưu lý do và nguồn đối chiếu |
| Claim support | Chia câu trả lời thành factual claims, đánh dấu được nguồn hỗ trợ / mâu thuẫn / chưa hỗ trợ; báo số claim và số câu |
| Abstention | Tỷ lệ từ chối đúng trên unanswerable và tỷ lệ từ chối sai trên answerable; tránh đạt điểm bằng cách từ chối mọi câu |
| Citation | Kiểm tra cơ học source/version/page bằng code; chấm hỗ trợ nội dung riêng |
| Tools | Đúng công cụ, đúng tham số/phạm vi, kết quả nhiệm vụ hoàn tất; ghi rõ nhiệm vụ cần confirmation hoặc chưa hoàn tất |
| Hiệu năng | Latency p50/p95, số mẫu, cold/warm cache riêng, ingestion time và peak RAM; báo provider retries/errors |
| Chi phí | Token thực, số attempts/calls, cache hits, estimated USD khi đủ giá; ingestion và từng loại nhiệm vụ tách riêng |

Tạo form review CSV/JSON gồm run/question ID, câu hỏi, câu trả lời, reference, evidence, rubric scores, người review và ghi chú. Nếu chỉ có một người chấm, công bố giới hạn đó. Ragas/LLM judge là bổ sung sau, không thay thế nguồn chuẩn và review ban đầu.

Chạy ba baseline trên dev; chọn cấu hình theo chất lượng, latency và usage. Sau khi khóa cấu hình, chạy held-out và báo toàn bộ kết quả/lỗi. Một tập con cố định của dev có thể chạy lặp để kiểm tra độ biến thiên; ghi rõ số lần. Báo so sánh theo từng câu và nhóm fact để tránh coi paraphrase là quan sát độc lập.

Ngưỡng nội bộ đề xuất cho chất lượng, cần chốt trước khi chạy held-out: evidence Recall@6 ít nhất 90% trên các câu có ground truth phù hợp; ít nhất 85% câu answerable đạt rubric 2; ít nhất 90% unanswerable được từ chối đúng; ít nhất 90% factual claims được nguồn hỗ trợ. Đây là mục tiêu tối ưu trên tập nhỏ, chưa phải kết quả hay cam kết đạt. Nếu chưa đạt, ghi lỗi và làm vòng cải tiến trên dev; không sửa đáp án/test hoặc đổi ngưỡng để đạt điểm đẹp. Mọi lỗi vượt quyền hoặc citation trỏ sai source/version là lỗi chặn release.

## M3 — Nâng cấp để cải thiện chỉ số có ích

| Ưu tiên | Nâng cấp | Giá trị portfolio / tiêu chí |
| --- | --- | --- |
| P0 | Đồng bộ cấu hình eval và trạng thái summary nguồn cũ | Hai lỗi quan sát được được sửa, có regression test theo tình huống thực |
| P1 | Một cải tiến retrieval | Chọn từ lỗi dev; đo Recall@6/MRR và chất lượng câu trả lời trước/sau, kèm latency/token |
| P1 | Tối ưu token hoặc latency | Dựa trên profiling: candidate/context selection, cache hoặc truy vấn DB; so sánh cùng workload và kiểm tra chất lượng không giảm đáng kể |
| P1 | Đo xử lý tăng dần và phục hồi | Ghi pages/chunks/calls, thời gian xử lý và phục hồi; chứng minh thêm file không lập chỉ mục lại toàn bộ corpus |
| P1 | Export metrics đủ để tái lập | Có baseline/final, sample counts, cấu hình, usage, latency và lỗi; dùng JSON/CSV/Markdown hiện có trước khi thêm biểu đồ |
| P2 | Mở rộng giao diện đọc nguồn | Làm khi luồng kiểm chứng nguồn hiện có gây khó sử dụng; tính đúng đắn của citation vẫn là P0 |
| P2 | Streaming hoặc public hosting | Để backlog; không là điều kiện bàn giao ứng dụng local và số liệu CV |

Chọn đúng một giả thuyết retrieval cho vòng đầu:

- Nếu miss do xếp hạng: thử reranking tập candidates và so với baseline trên cùng câu hỏi.
- Nếu miss ở câu nối tiếp: thử query rewrite có điều kiện, tính cả token/call và lỗi rewrite.
- Nếu miss vì chunk mất ranh giới nội dung: thử thay đổi chiến lược chunk trên corpus dev, dùng index riêng để so sánh.

Không đổi cả ba biến cùng lúc. Đăng ký cấu hình, tập dev, metric chính và trade-off chấp nhận được trước thí nghiệm. Nếu hiệu quả không rõ hoặc chi phí/latency không phù hợp, giữ baseline và ghi kết quả âm trong báo cáo benchmark.

### Các con số ưu tiên để đưa vào CV

| Nhóm | Kết quả cần đo | Điều kiện so sánh |
| --- | --- | --- |
| Chất lượng retrieval | Recall@6, MRR, mức tăng theo điểm phần trăm so với baseline | Cùng tập câu hỏi, scope, ground truth và ngân sách context; báo số câu/nhóm fact |
| Chất lượng trả lời | Tỷ lệ câu đúng và đủ, claim được nguồn hỗ trợ, từ chối đúng/sai | Rubric và split cố định; có review và mẫu lỗi |
| Tốc độ | p50/p95 từ gửi request đến nhận câu trả lời hoàn chỉnh; thời gian ingestion | Cùng model, máy, workload, concurrency; báo số mẫu và cold/warm cache riêng |
| Token/chi phí | Input/output tokens trung bình mỗi câu, mức giảm so với baseline, USD khi đủ bảng giá | Cùng workload, tính cả embedding/rewrite/rerank; giữ chất lượng ở mức đã chốt |
| Cache | Provider calls/tokens tiết kiệm và latency trên workload có câu lặp | Công bố tỷ lệ câu lặp, số cache hits và revision; không dùng toàn câu lặp đại diện mọi truy vấn |
| Quy mô và độ bền | Số trang/chunks, peak RAM, tỷ lệ job hoàn tất, thời gian phục hồi | Ghi rõ PDF tổng hợp hay thực, provider, lỗi đã gây ra, số lần thử và thành phần đã chạy |

Chọn 2–3 kết quả mạnh nhất đã kiểm chứng cho CV; giữ toàn bộ kết quả và giới hạn trong báo cáo. Mục tiêu là cải thiện hệ thống để có số liệu tốt. Không dùng số API endpoints, số dòng code hoặc chỉ số cache trên câu lặp làm đại diện cho độ chính xác RAG.

Trước final evaluation, khóa cả baseline và cấu hình cải tiến. Nếu CV dùng mức tăng/giảm trên held-out, chạy cả hai cấu hình trên cùng held-out theo protocol đã chốt và không dùng kết quả đó để tiếp tục chọn cấu hình. Công bố mẫu số; phân biệt điểm phần trăm với phần trăm tương đối. Với latency/chi phí, theo dõi đồng thời chất lượng để phát hiện đánh đổi.

Mẫu câu CV sẽ được điền sau khi đo, các ký hiệu hiện tại không phải kết quả:

- Built a Vietnamese/English PDF RAG application, achieving [R]% evidence Recall@6 on [N] held-out questions, improving by [D] percentage points over [baseline].
- Reduced average provider token usage per question by [T]% while maintaining [Q]% fully correct answers on the same evaluation set.
- Implemented resumable ingestion for [P] pages / [C] chunks, recovering [J/J] interrupted jobs without duplicate chunks across [K] controlled restart trials.

OCR, GraphRAG, fine-tuning, multi-agent framework, Kubernetes, voice và nhiều provider để backlog. Chỉ mở rộng khi lỗi hoặc use case đo được chứng minh cần thiết. Nâng cấp thư viện/model thực hiện khi bắt đầu triển khai, có đối chiếu tài liệu/changelog và rerun checks tương ứng; không đổi theo nhãn “latest” trong kế hoạch này.

## M4 — CI, ứng dụng chạy được và báo cáo CV

- CI mỗi PR: backend deterministic tests với PostgreSQL/Redis thật, frontend typecheck/build, và các E2E offline quan trọng trên test stack. Failed dependency phải làm job lỗi, không âm thầm skip.
- Kiểm thử restart/backup/restore và 1.000 trang chạy ở workflow thủ công hoặc release, trên dữ liệu test. Bài live dùng workflow/lệnh chủ động với ngân sách đã chốt; không chạy trên mọi PR.
- Chạy lại fresh setup theo đúng README ở môi trường sạch; ghi lệnh thực tế và các điều kiện cần có.
- README ghi bài toán, cách chạy, luồng dùng và bảng kết quả đã đo; có giới hạn và liên kết evidence.
- Báo cáo benchmark ngắn ghi dataset/split, baseline/final, cấu hình/môi trường, lệnh tái lập, metrics và lỗi còn lại. Giữ giải thích kiến trúc trong tài liệu hiện có.
- Chuẩn bị 2–3 câu mô tả CV với số liệu đã có artifact; không dùng số liệu của fake-vector smoke như hiệu năng OpenAI thật.

Các artifact dự kiến:

```text
docs/portfolio-roadmap.md       Kế hoạch này
docs/test-report.md             Bằng chứng verification cập nhật
docs/evaluation.md              Protocol, dataset và metric
docs/benchmark-report.md        Kết quả baseline/final và cách tái lập
docs/cv-results.md              2–3 câu CV cùng liên kết evidence
artifacts/runs/<run-id>/        Logs, môi trường, cấu hình, kết quả
fixtures/portfolio/             Dataset được phép chia sẻ và manifest split
```

## Điều kiện hoàn thành release portfolio

Cập nhật thực thi 2026-09-10: các gate kỹ thuật bên dưới đã có evidence trong [test-report.md](test-report.md), [benchmark-report.md](benchmark-report.md) và [cv-results.md](cv-results.md). Review nội dung hiện do assistant thực hiện; chấm độc lập bởi người và claim-support toàn diện chưa hoàn tất, nên không dùng làm claim CV. QASPER là retrieval-only, 58,35% Recall@6; không suy từ bộ tổng hợp ra chất lượng tổng quát.


- [x] Fresh setup, migration và các dịch vụ chạy đúng theo README.
- [x] Toàn bộ 22 integration tests đang bị skip được chạy và pass; các lỗi phát hiện được sửa bằng regression có ý nghĩa.
- [x] Browser happy path và vòng đời tài liệu được kiểm chứng; không có lỗi chặn sử dụng hoặc rò scope.
- [x] Worker restart, queue recovery và backup/restore có bằng chứng trên stack thật.
- [x] Có smoke OpenAI thật Việt/Anh, 10 câu và năm tác vụ tools, với usage và review nội dung.
- [x] Có baseline dev, cấu hình đóng băng, kết quả held-out và failure analysis.
- [x] Có một thí nghiệm cải tiến được báo trung thực, kể cả khi kết quả âm.
- [x] QASPER có ID/hash thực; công bố rõ đã chạy retrieval, generation hay chỉ materialize dữ liệu.
- [x] Kết quả 1.000 trang ghi đúng provider và thành phần đã chạy. Live 1.000 trang là gate riêng nếu tiếp tục công bố đã nghiệm thu đầy đủ yêu cầu V1 này.
- [x] README chạy lại được; báo cáo benchmark và 2–3 câu CV phản ánh đúng kết quả, baseline và phạm vi đã đo.

Đích hoàn thành là một ứng dụng dùng được và bộ số liệu có thể kiểm chứng để đưa vào CV. Trạng thái production readiness vẫn cần đánh giá theo yêu cầu triển khai riêng.
