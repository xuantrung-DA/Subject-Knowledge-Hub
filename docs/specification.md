# Prompt triển khai: Subject Knowledge Hub

Bạn là coding agent chịu trách nhiệm thiết kế, triển khai và kiểm tra toàn bộ source code của một ứng dụng Applied AI. Hãy đọc hết đặc tả này rồi trực tiếp thực hiện trong repository hiện tại. Đây là yêu cầu xây dựng sản phẩm chạy được, không phải yêu cầu chỉ tư vấn kiến trúc hoặc tạo scaffold.

## 1. Mục tiêu và điều kiện bàn giao

Xây dựng **Subject Knowledge Hub**: kho tài liệu PDF được tổ chức theo môn học, có hỏi đáp dựa trên tài liệu và trích dẫn đúng trang.

Người dùng nghiệm thu bằng cách: lấy source code → cấu hình OpenAI API key → chạy Docker Compose → mở trình duyệt → tạo môn học → tự upload PDF → đợi xử lý → hỏi đáp và kiểm tra nguồn. Toàn bộ luồng này phải hoạt động với tài liệu người dùng upload, không phụ thuộc dữ liệu demo hoặc thao tác SQL thủ công.

Project cần thể hiện: RAG, tool calling, evaluation, backend/database, xử lý bất đồng bộ, vận hành và kiểm soát token/chi phí. Không tuyên bố một project chứng minh mọi kỹ năng của mọi vị trí AI Engineer.

Tự quyết định các chi tiết thông thường và tiếp tục triển khai qua các giai đoạn. Chỉ hỏi nếu thiếu thông tin thực sự chặn việc thực hiện. Đọc AGENTS.md nếu có; giữ nguyên những thay đổi không liên quan trong repository. Không dừng ở kế hoạch, pseudocode, TODO hoặc giao diện nối với dữ liệu giả.

## 2. Phạm vi và stack

Chọn một stack thống nhất, ưu tiên chạy local trên Windows với Docker Desktop/WSL2, RAM 16 GB; không yêu cầu GPU:

- Frontend: React, TypeScript, Vite; giao diện tiếng Việt, desktop trước, responsive cơ bản.
- Backend: Python, FastAPI, Pydantic, SQLAlchemy, Alembic.
- Database: PostgreSQL với pgvector; migration tạo extension và schema.
- Queue: Celery + Redis; worker xử lý ingestion và tóm tắt dài.
- PDF: pypdf cho metadata/đọc theo trang, pdfplumber khi cần trích xuất bảng; thống nhất thành một parser adapter có test.
- AI: official OpenAI Python SDK, Responses API cho sinh câu trả lời/function calling; Embeddings API cho embeddings.
- Lưu PDF gốc: persistent Docker volume dùng chung giữa API và worker. PostgreSQL lưu metadata, nội dung trang, chunks và vectors. Redis phục vụ queue và cache, không là nguồn dữ liệu duy nhất của job.
- Docker Compose gồm web, api, worker, postgres, redis và migration/bootstrap nếu cần. Không bắt người dùng đăng ký thêm dịch vụ cloud.

Default model cấu hình qua environment:

```dotenv
OPENAI_API_KEY=
OPENAI_CHAT_MODEL=gpt-4.1-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_EMBEDDING_DIMENSIONS=1536
```

Đây là defaults thực dụng, không phải khẳng định model mới nhất hoặc rẻ nhất. Trước khi code, đối chiếu tài liệu chính thức với SDK/model đang dùng. Pin phiên bản dependency tương thích và cung cấp lockfiles. Đổi embedding model/dimensions phải yêu cầu reindex hoặc migration rõ ràng; không trộn vectors khác không gian embedding.

V1 bắt buộc hỗ trợ PDF có text tiếng Việt/tiếng Anh, gồm PDF khoảng 1.000 trang trong giới hạn dung lượng cấu hình. PDF scan toàn bộ báo `needs_ocr`; không đánh dấu thành công khi không trích được nội dung. Với PDF hỗn hợp, hiển thị số trang có text và cảnh báo trang bỏ qua. OCR, hiểu hình vẽ/công thức phức tạp và tái tạo bảng hoàn hảo nằm ngoài V1.

Không thêm GraphRAG, multi-agent framework, fine-tuning, Kubernetes, voice hoặc web search trong V1. Không thay pipeline tự triển khai bằng OpenAI hosted File Search: người dùng cần source cho parsing, chunking, indexing, retrieval và evaluation.

## 3. Luồng sản phẩm bắt buộc

### 3.1 Tài khoản và môn học

- Có đăng ký/đăng nhập local đơn giản với password hashing và session an toàn. Không cần email, OAuth hoặc dịch vụ ngoài. Chỉ bind ứng dụng local theo mặc định.
- Mỗi người dùng có danh sách môn học: tạo, đổi tên, xem, xóa có xác nhận.
- Một môn học là một logical collection trong database chung, không tạo database vật lý riêng cho mỗi môn.
- **Bắt buộc chọn môn trước khi upload PDF và trước khi gửi câu hỏi.** Nếu chưa chọn, disable thao tác và hướng dẫn chọn/tạo môn.
- Hiển thị tên môn hiện tại rõ ràng ở cả khu vực tài liệu và chat. Đổi môn phải đổi conversation tương ứng hoặc tạo conversation mới; không mang lịch sử môn cũ sang môn mới.
- Backend xác thực quyền sở hữu môn và mọi tài nguyên con. Không tin `subject_id`, `document_id`, `conversation_id` chỉ vì frontend gửi lên; metadata filtering tự nó không phải kiểm soát truy cập.

### 3.2 Upload và quản lý tài liệu

- Kéo thả/chọn một hoặc nhiều PDF vào môn đang chọn. Upload streaming theo giới hạn cấu hình; không đọc toàn bộ file lớn vào RAM nếu tránh được.
- Mặc định `MAX_UPLOAD_MB=100`, `MAX_PDF_PAGES=1200`, cấu hình đồng bộ ở reverse proxy/backend và hiển thị trên UI. Vượt giới hạn trả lỗi dễ hiểu.
- Kiểm tra định dạng thực tế, file rỗng, hỏng, mã hóa và tên file không an toàn. Tên file gốc chỉ là metadata; đường dẫn lưu trữ dùng ID an toàn.
- Sau khi file được nhận/lưu và job được ghi bền vững, API trả document/job ID ngay, không chờ parse/embedding.
- UI tách upload progress khỏi processing progress. Hiển thị trạng thái thực: queued, parsing, chunking, embedding, ready, failed, needs_ocr; số trang/chunks đã xử lý nếu có. Không tạo phần trăm giả bằng timer.
- Bảng tài liệu có tên, ngày upload, số trang, số chunks, phiên bản, trạng thái, cảnh báo và lỗi có thể xử lý. Có xem PDF, thử lại job lỗi, thay phiên bản và xóa có xác nhận.
- Refresh hoặc đóng/mở trình duyệt không làm mất trạng thái job.

### 3.3 Hỏi đáp và nguồn

- Người dùng hỏi bằng tiếng Việt/Anh trong môn đã chọn; có lịch sử hội thoại lưu trong DB.
- Câu trả lời dựa trên nguồn được truy xuất, có citation theo dạng `[1]` và thẻ nguồn: tên tài liệu, phiên bản, trang PDF, trích đoạn hỗ trợ.
- Click nguồn mở PDF đúng trang trong viewer có kiểm soát truy cập. Số trang mặc định là thứ tự vật lý của PDF, bắt đầu từ 1; không nhầm với số in trên trang sách.
- Nếu chưa có tài liệu ready, báo rõ và không gọi model vô ích.
- Nếu không đủ bằng chứng, trả lời rằng chưa tìm thấy thông tin trong tài liệu môn này; không tự tìm Internet. Nếu nguồn mâu thuẫn, nêu mâu thuẫn và dẫn cả hai nguồn.
- Có loading, timeout, retry và thông báo lỗi OpenAI rõ ràng. Không biến lỗi API thành câu trả lời thành công.
- Render Markdown an toàn. Citation ID phải được backend đối chiếu với nguồn thực sự đã cung cấp cho model, không chấp nhận đường dẫn/trang do model tự bịa.

### 3.4 Giao diện

Sidebar: danh sách môn học. Nội dung chính có tab `Tài liệu`, `Hỏi đáp`, `Đánh giá` và một vùng trạng thái nhỏ.

Tab Hỏi đáp có chọn conversation, ô nhập, câu trả lời và nguồn. Thông tin debug như token, latency, retrieval scores và tool trace nằm trong phần mở rộng, không chen vào nội dung học tập. Dùng trạng thái empty/loading/error/success đầy đủ; mọi nút hiển thị phải hoạt động.

## 4. Pipeline ingestion bền vững

Luồng: lưu file → tạo document version/job → worker parse theo trang → chuẩn hóa → chunk → embedding theo batch → ghi dữ liệu → kích hoạt phiên bản → tăng revision của môn.

- Bảo toàn ánh xạ chunk → document version → một hoặc nhiều trang. Có `page_start`, `page_end`, danh sách trang hoặc offsets đủ để citation chính xác.
- Chunk theo cấu trúc đoạn/heading trong khả năng parser; mặc định khoảng 600 tokens, overlap 80 tokens. Không phá bảng nếu parser đã nhận diện được bảng; ghi rõ giới hạn của parser.
- Loại header/footer lặp chỉ khi có quy tắc đáng tin, tránh xóa nội dung thật. Token count dùng tokenizer phù hợp model, không dùng số ký tự như token thực.
- Embedding batch có giới hạn số inputs và tổng tokens, không gửi cả PDF 1.000 trang trong một request. Worker concurrency mặc định 1; timeout, backoff có jitter, retry hữu hạn cho lỗi tạm thời.
- Persist checkpoints theo giai đoạn/batch. Unique constraints và upsert đảm bảo retry không nhân đôi pages/chunks/embeddings.
- Hash file để nhận diện upload trùng trong cùng môn; upload lại cùng bytes không tạo bản copy hoặc trả tiền embedding lại. Có xử lý hai upload trùng chạy đồng thời.
- Chỉ xử lý tài liệu/phiên bản mới khi upload bổ sung. Không rebuild tất cả tài liệu của môn.
- Dùng durable job record và cơ chế enqueue/reconcile có thể phục hồi khi API commit DB xong nhưng publish queue thất bại. Celery redelivery không được coi là exactly-once. Worker restart không làm tài liệu mắc kẹt vĩnh viễn.
- Hoàn tất toàn bộ version trước khi chuyển active version trong transaction. Nếu bản thay thế thất bại, bản cũ vẫn truy xuất được. Không đưa chunks của phiên bản đang xử lý vào retrieval mặc định.
- Xóa tài liệu phải loại khỏi retrieval ngay, tăng corpus revision và vô hiệu cache liên quan. Worker chạy dở phải kiểm tra trạng thái xóa trước khi publish dữ liệu; không hồi sinh tài liệu đã xóa.
- Phiên bản cũ/deleted không được dùng như bằng chứng trong câu trả lời mới. Lịch sử có thể giữ citation cũ với nhãn đã thay thế/đã xóa, không âm thầm trỏ sang trang của phiên bản mới. Khi corpus revision thay đổi, loại evidence/lịch sử không còn hợp lệ khỏi model context.
- Retry sau mất kết nối có thể lặp một API call đã được provider xử lý; ghi nhận giới hạn này, không hứa tuyệt đối không phát sinh token trùng.

## 5. Retrieval và kiểm soát token

### 5.1 Retrieval

- Baseline dense search bằng pgvector; có lexical search bằng PostgreSQL full-text search với cấu hình phù hợp dữ liệu Việt/Anh. Không gọi full-text search là BM25 nếu chưa thực sự triển khai BM25.
- Có chế độ `dense`, `lexical`, `hybrid`; hybrid hợp nhất thứ hạng bằng Reciprocal Rank Fusion. Mặc định hybrid nếu đã kiểm chứng hữu ích; ghi quyết định qua kết quả eval.
- Áp dụng ownership, subject và active-version filtering trong truy vấn. Không lấy top-k toàn database rồi mới lọc ở Python.
- Có index phù hợp; với vector approximate index, kiểm tra tình huống filter làm thiếu kết quả và chọn exact search/fallback phù hợp quy mô. Không hy sinh cô lập dữ liệu để lấy đủ k.
- Retrieval ứng viên khoảng 20, khử trùng lặp rồi chọn tối đa 6 chunks theo ngân sách token. Các số là config có thể điều chỉnh bằng eval.
- Câu hỏi nối tiếp cần được xử lý bằng lịch sử ngắn hoặc query rewrite có điều kiện; rewrite cũng phải được tính vào usage.

### 5.2 Ngân sách và cache

Chọn môn trước giúp thu hẹp tập tìm kiếm; **không có nghĩa tự động giảm tokens nếu vẫn gửi cùng lượng context**. Thực hiện đồng thời:

- Không gửi toàn bộ PDF, toàn database hoặc toàn lịch sử chat cho model.
- Cấu hình khởi đầu: `RETRIEVAL_TOP_K=6`, `MAX_CONTEXT_TOKENS=4500`, `MAX_HISTORY_TOKENS=1500`, `MAX_OUTPUT_TOKENS=900`, `MAX_TOOL_ROUNDS=3`. Tính cả system prompt, tool schema và tool outputs khi kiểm tra ngân sách đầu vào. Tránh cắt citation mapping khi trim.
- Mỗi câu hỏi có tổng ngân sách cho tất cả model calls, không chỉ từng request. Mỗi job ingestion/summary có giới hạn tokens/calls cấu hình, dừng với trạng thái rõ khi vượt giới hạn.
- Cache embedding cho nội dung không đổi theo user scope, content hash, model và dimensions. Có cache query embedding và exact-answer cache TTL.
- Answer cache key phải chứa user/authorization scope, subject, corpus revision, model, prompt/retrieval config version và lịch sử liên quan. Có thể giới hạn answer cache cho câu hỏi độc lập để tránh sai ngữ cảnh.
- Không cache lỗi tạm thời hoặc dùng cache cũ sau thêm/thay/xóa tài liệu. Semantic cache là mở rộng sau V1; không cần thêm để hoàn thành.
- Ghi usage thực trả về từ OpenAI cho embedding, generation và evaluation: input/output/cached tokens nếu có, model, latency, retries, cache hit. Chi phí USD là ước tính từ bảng giá cấu hình có ngày cập nhật; nếu thiếu giá thì hiển thị tokens, không bịa giá.
- Hiển thị tổng tokens của một lần hỏi/job trong chi tiết. Không quảng cáo latency hoặc chi phí bằng 0 nếu chưa đo.

## 6. Tool calling có chức năng thật

Dùng OpenAI function calling với schemas được validate và giới hạn vòng lặp. Có hai chế độ trong chat: `Hỏi tài liệu` mặc định dùng retrieval trực tiếp để ít round trips; `Trợ lý tài liệu` cho các yêu cầu cần chọn/chạy tools. Không giả lập tool calling bằng if/else rồi tuyên bố model đã chọn tool.

Các tools trong chế độ Trợ lý:

1. `search_documents(query, limit)`: tìm evidence trong môn hiện tại.
2. `read_document_pages(document_id, page_start, page_end)`: đọc một khoảng trang có giới hạn, kiểm tra quyền và phiên bản.
3. `list_documents()`: trả danh sách/trạng thái tài liệu từ DB, không gọi vector search để đoán danh sách.
4. `summarize_document(document_id, page_start, page_end)`: tóm tắt phạm vi chỉ định; nếu toàn tài liệu dài thì tạo hoặc tái sử dụng summary job và trả job ID/trạng thái.
5. `get_job_status(job_id)`: kiểm tra trạng thái và kết quả job thuộc user/môn hiện tại.

Scope user/subject phải do backend inject từ request đã xác thực, không do model chọn. Không cho model SQL tùy ý, shell, đường dẫn file tùy ý hoặc truy cập tài liệu môn khác. Tool outputs có giới hạn độ dài. UI có trace tên tool, tham số đã làm sạch, thời gian và kết quả tóm tắt; không cần lưu chain-of-thought.

Tóm tắt toàn tài liệu dùng xử lý phân cấp trong background worker, không lấy vài top-k chunks rồi gọi đó là tóm tắt toàn bộ. Hiển thị phạm vi đã đọc, tiến độ và token estimate; yêu cầu người dùng chủ động bắt đầu job dài trên UI trước khi chạy chi phí lớn. Cache summary theo document version và cấu hình. Nếu vượt ngân sách, báo chưa hoàn thành và đề nghị chọn khoảng trang, không âm thầm bỏ phần còn lại.

Nội dung PDF là dữ liệu không đáng tin. Prompt injection nằm trong PDF không được đổi scope, lộ secret, kích hoạt tool ngoài allowlist hoặc vượt ngân sách. Giới hạn phải được thực thi trong code, không chỉ bằng system prompt.

## 7. Data model và API

Thiết kế schema tối thiểu gồm users/sessions, subjects với corpus_revision, documents, document_versions với active pointer, document_pages, chunks với embedding/config version, ingestion_jobs/checkpoints, conversations/messages, tool_runs, usage_events, summaries, evaluation_runs/results. Có foreign keys, unique constraints, timestamps và indexes cho truy vấn thực tế.

API phải phục vụ đầy đủ UI: authentication; CRUD subjects; upload/list/view/replace/delete documents; job status/retry; conversations/messages/chat; summary jobs; chạy/xem/export evaluation. Endpoint scope rõ như `/api/subjects/{subject_id}/...`. Cung cấp OpenAPI docs, validation và lỗi có machine-readable code cùng thông báo dễ hiểu.

PDF viewer tải file qua endpoint xác thực, không public toàn thư mục uploads. Secrets chỉ ở backend environment; không dùng frontend environment chứa API key, không commit `.env`, không log key hoặc toàn bộ tài liệu mặc định. Có giới hạn upload, chat rate và job concurrency; cơ chế session chống CSRF phù hợp cách triển khai.

## 8. Evaluation thực chất và tái lập

Triển khai evaluation CLI và một UI đơn giản để chọn môn, upload dataset JSONL, chạy job, xem/export kết quả. Evaluation phải dùng cùng ingestion/retrieval/generation code với ứng dụng. Dataset là tài nguyên đánh giá riêng, không được indexing vào kho tài liệu.

### 8.1 Dataset riêng

Cung cấp fixture PDFs do project tự tạo và ít nhất 50 câu hỏi có đáp án cùng evidence được kiểm tra bằng nội dung fixture. Có câu hỏi Việt/Anh, paraphrase, nối tiếp, nhiều nguồn, ngoài phạm vi, nguồn mâu thuẫn, tài liệu mới/thay thế/xóa và nội dung prompt injection. Ghi rõ đây là bộ regression của project; không gọi nó là benchmark độc lập hoặc nói đã được chuyên gia duyệt.

Schema gợi ý, có validation và file mẫu:

```json
{"id":"q001","question":"...","reference_answer":"...","answerable":true,"evidence":[{"document_key":"fixture_chapter_1","page_start":3,"page_end":3}],"tags":["vi","single_document"]}
```

Document key được map sang tài liệu/phiên bản trong môn khi import; báo lỗi nếu không map được. Cho phép người dùng tự viết bộ câu hỏi chuẩn cho PDF của mình. Đáp án chuẩn chỉ dùng chấm điểm, không đưa vào prompt trả lời hoặc vector index.

### 8.2 Dataset công khai

Cung cấp script tải và adapter cho một subset cố định 100 câu hỏi QASPER, có IDs, split, seed, nguồn và license trong manifest. Index phần nội dung bài báo; giữ questions/answers/evidence của tập test tách biệt. Dùng train/dev để chỉnh cấu hình nếu cần, test giữ cố định.

QASPER dùng để đánh giá QA/retrieval trên bài báo tiếng Anh. Nếu sử dụng bản full-text, không gán trang PDF giả và không coi kết quả đó là kiểm thử parser PDF hoặc chất lượng tiếng Việt. Dùng evidence theo đoạn của dataset; chạy benchmark ở collection riêng không lẫn tài liệu người dùng.

### 8.3 Metrics và báo cáo

- Retrieval: evidence Recall@k, precision hoặc MRR khi ground truth phù hợp; định nghĩa rõ đơn vị evidence là trang/đoạn và cách mapping sang chunks.
- Answer: answer relevance/correctness so với reference; unanswerable handling; faithfulness nếu dùng LLM judge. Faithfulness đo sự nhất quán với context, không chứng minh sự thật tuyệt đối.
- Citation: hợp lệ về document/page và có thật sự hỗ trợ claim là hai phép đo khác nhau. Kiểm tra cơ học và cung cấp sample để review nội dung.
- Tool: chọn đúng tool, đúng phạm vi, hoàn thành tác vụ, xử lý tool error và giới hạn vòng lặp.
- Operations: latency p50/p95 từ đủ số mẫu, token usage, estimated cost, cache hit và thời gian ingestion; báo sample size và môi trường.

So sánh lexical/dense/hybrid với cùng tập câu hỏi, chat model, prompt và context budget. Xuất JSON/CSV và report Markdown có dataset/config/git revision nếu có, lỗi theo câu hỏi và ví dụ thất bại. LLM judge/Ragas là đánh giá bổ sung, pin phiên bản và ghi rõ chi phí; deterministic suite không phụ thuộc judge trả phí. Không điền sẵn điểm đẹp, không hardcode PASS, không khẳng định benchmark đã chạy nếu chỉ có pipeline.

## 9. Chạy local, vận hành và chất lượng code

- Sau clone, người dùng chỉ cần copy `.env.example`, thêm key và chạy `docker compose up --build -d`. Web tại `http://localhost:3000`, API docs được ghi rõ trong README.
- Có hướng dẫn Bash/WSL và PowerShell, không bắt buộc `make`. Các thao tác fixture, test và eval có script/command cụ thể chạy trong container.
- Khởi động tự chạy migration an toàn, kiểm tra readiness PostgreSQL/Redis; phân biệt liveness của process và readiness phụ thuộc. Thiếu OpenAI key hiển thị cấu hình thiếu; app không giả vờ xử lý AI thành công.
- Dữ liệu còn sau `docker compose down` rồi `up`; reset dữ liệu là lệnh riêng ghi rõ hậu quả, không nằm trong quickstart.
- Structured logs có request/job IDs; worker heartbeat, lỗi, retry và usage đủ để debug. Không cần thêm một hệ monitoring nặng chỉ để có tên công nghệ trong README.
- CI chạy backend tests, frontend typecheck/build và integration tests cần PostgreSQL/Redis bằng service containers. Không dùng SQLite thay thế để tuyên bố đã kiểm tra pgvector, transactions hoặc concurrency.
- Unit/integration tests có fake provider chỉ cho test offline. Runtime mặc định gọi OpenAI thật; không tự fallback sang mock khi key sai hoặc quota hết.
- API timeout, invalid key, model không được cấp quyền, rate limit và quota exhausted phải được phân loại. Retry hữu hạn cho lỗi retryable; không loop mãi với invalid key/insufficient quota.

## 10. Checklist nghiệm thu bắt buộc

### A. Engineering — offline/deterministic

1. Fresh setup build/start được; web, API, worker, DB và Redis healthy; migrations chạy được từ DB rỗng.
2. Tạo tài khoản và hai môn A/B; user khác không đọc được tài liệu, jobs, PDF hoặc conversation của user đầu. Sửa ID trong API/tool không vượt quyền.
3. Upload PDF fixture, theo dõi đến ready; xem PDF và citation đúng trang. Upload cùng file hai lần, kể cả đồng thời, không nhân đôi active chunks.
4. Thêm tài liệu mới chỉ index phần mới. Replacement thành công chuyển active version; replacement lỗi giữ bản cũ. Xóa chặn retrieval, cache và new-answer evidence kể cả từ conversation cũ.
5. Worker bị stop/restart giữa ingestion tiếp tục hoặc retry an toàn; không mất job hoặc tạo duplicate. Kiểm tra cả tình huống publish queue thất bại sau DB commit.
6. PDF hỏng, quá lớn, có mật khẩu, scan toàn bộ và thiếu key đều có trạng thái/lỗi đúng; không stuck loading.
7. Provider timeout/429/quota failure qua fake provider cho thấy retry có giới hạn và trạng thái phù hợp.
8. Kiểm thử context budget, scope filtering và cache invalidation. Một tài liệu chứa prompt injection không thay đổi quyền truy cập hoặc gọi tool bị cấm.
9. Tạo fixture 1.000 trang có text khác nhau và facts ở đầu/giữa/cuối; đo ingestion, peak memory và retrieval ba vùng. Chạy offline trước. Đây là scalability smoke test, không đại diện mọi PDF thực tế.
10. Restart toàn stack giữ tài liệu, tài khoản, job state và chat history; UI không có nút dead-end.

### B. Live OpenAI — bắt buộc phân biệt với mock

Khi có API key và network phù hợp, thực hiện smoke test bằng API thật với giới hạn tokens/calls nhỏ được ghi trong config: ít nhất một PDF tiếng Việt và một PDF tiếng Anh có text, tối thiểu 10 câu hỏi gồm trả lời được/không có nguồn/nối tiếp, kiểm tra citations và ít nhất 5 tác vụ tools đại diện. Ghi actual usage, model, kết quả và lỗi. Không tự chạy toàn bộ benchmark trả phí hoặc summary 1.000 trang khi chưa biết ngân sách; để lệnh riêng có estimate và giới hạn.

Live full-scale ingestion của PDF 1.000 trang là bài test riêng, có token estimate và chi phí ước tính trước chạy. Nếu chỉ chạy 1.000 trang với fake embeddings, ghi rõ giới hạn; không gọi đó là đã kiểm chứng end-to-end OpenAI cho file lớn.

### C. Người dùng tự nghiệm thu trên browser

1. Mở app, đăng nhập, tạo môn `Học máy` và chọn môn này.
2. Upload PDF bất kỳ có text trong giới hạn công bố; theo dõi đến ready hoặc nhận lỗi cụ thể có thể xử lý.
3. Hỏi một thông tin có trong PDF; click nguồn và đối chiếu đúng trang.
4. Hỏi thông tin không có trong tài liệu; hệ thống báo thiếu bằng chứng.
5. Upload thêm PDF có thông tin mới; hỏi về nội dung mới mà không phải rebuild kho cũ.
6. Chuyển sang môn khác; câu hỏi không lấy nguồn/lịch sử từ môn `Học máy`.
7. Thay/xóa tài liệu, hỏi lại và kiểm tra không sử dụng evidence/cache cũ.
8. Dùng Trợ lý để liệt kê tài liệu, đọc khoảng trang hoặc tóm tắt; xem tool trace.
9. Import bộ câu hỏi JSONL, chạy evaluation nhỏ và tải báo cáo.
10. Tắt/bật stack, tiếp tục dùng dữ liệu đã lưu.

Nếu môi trường agent không có Docker, browser automation, network hoặc API key: hoàn thiện mọi phần có thể, chạy các kiểm tra còn lại và ghi rõ `PASS / FAIL / UNVERIFIED` cho từng mục cùng bằng chứng. Không coi unit tests là đã nghiệm thu full stack; không tuyên bố chạy ổn end-to-end khi live test chưa được chạy. Cung cấp lệnh chính xác để người dùng hoàn tất mục chưa xác minh.

## 11. Cách triển khai và bộ bàn giao

Triển khai lần lượt nhưng thực hiện đến cùng:

1. Khảo sát repo, ghi quyết định ngắn trong `docs/architecture.md`, scaffold và stack chạy được.
2. Hoàn thiện một luồng xuyên suốt: tài khoản → môn → upload → worker → retrieval → câu trả lời OpenAI → citation viewer. Kiểm tra trước khi mở rộng.
3. Thêm incremental ingestion, versioning, deletion, recovery và cache đúng revision.
4. Thêm tools, summary jobs và observability/usage.
5. Thêm evaluation, fixtures, integration/browser tests và sửa lỗi qua checklist.
6. Rà lại fresh setup và bàn giao bằng chứng.

Source code phải gồm frontend, backend, worker, migrations, Dockerfiles/Compose, lockfiles, `.env.example`, tests, scripts và dataset fixtures không vi phạm bản quyền. Không đặt key thật hoặc PDF riêng tư trong repo.

Các tài liệu bắt buộc:

- `README.md`: tiếng Anh, mục tiêu, quickstart, yêu cầu máy, cấu hình OpenAI, kiến trúc, test/eval commands, cách shutdown/backup/restore và giới hạn thực tế.
- `docs/acceptance_vi.md`: hướng dẫn tiếng Việt để người dùng tự upload PDF và nghiệm thu theo mục 10C.
- `docs/architecture.md`: data flow, schema, decision/trade-off, nguồn tài liệu kỹ thuật, Mermaid ngắn nếu hữu ích.
- `docs/evaluation.md`: dataset, metrics, cách chạy, benchmark limitations và kết quả thực nếu có.
- `docs/test-report.md`: môi trường, lệnh đã chạy, thời điểm, PASS/FAIL/UNVERIFIED, số liệu và lỗi còn lại. Dẫn đến logs/artifacts có thật.
- `docs/progress.md`: trạng thái và bước tiếp theo để tiếp tục sau khi hết context; không thay tài liệu này cho việc thực hiện.

Thông báo cuối khi code xong phải ghi: chức năng đã hoạt động, lệnh khởi động và URL, config cần điền, kiểm thử đã chạy, mục chưa xác minh và giới hạn còn lại. Không gọi sản phẩm production-ready chỉ vì chạy Docker được.

**Bắt đầu thực hiện ngay. Đích cuối là source code có thể chạy để tôi tự chọn môn, upload PDF của mình và kiểm tra câu trả lời, chứ không chỉ là một bản thiết kế.**

## Tài liệu chính thức để đối chiếu khi triển khai

- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling): cách xử lý tool calls/results bằng API chính thức.
- [OpenAI embeddings](https://developers.openai.com/api/docs/guides/embeddings): embedding model, kích thước vector và API; `text-embedding-3-small` mặc định 1536 chiều.
- [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini): đối chiếu model default và capabilities, không suy ra mọi tài khoản đều truy cập được.
- [FastAPI background tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/): tác vụ nặng nên dùng hệ worker phù hợp.
- [Celery tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html): idempotency, acknowledgment, retry và worker failure.
- [Docker Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/): dependencies và health checks.
- [pgvector](https://github.com/pgvector/pgvector): vector search, indexing và filtering.
- [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html): giới hạn text extraction và PDF scan/OCR.
- [QASPER dataset](https://huggingface.co/datasets/allenai/qasper): dữ liệu QA/evidence trên bài báo khoa học, kiểm tra license và dataset card.
- [Ragas faithfulness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/): diễn giải đúng phạm vi metric.
