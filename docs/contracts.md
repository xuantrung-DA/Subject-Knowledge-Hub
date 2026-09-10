# Implementation contracts (internal, authoritative across modules)
Root: backend/app; imports `app.*`. Python 3.12. Sync SQLAlchemy 2 Session. UUIDs stored as String(36), generated `new_id()`. All timestamps timezone aware. JSON fields plain JSON (assign new object, no mutation).

Shared modules owned by core agent: `config.py` exports `settings` (lowercase fields), `db.py` exports Base, SessionLocal, engine, get_db, `models.py` exports classes below. `security.py` exports `current_user` dependency, `require_subject(db,user_id,subject_id)`. `errors.py` exports `AppError(code,message,status_code=400)`. Services should raise AppError. Core API router `router` prefix /api in `api.py`. Main app owned core.

Models (required fields; extra allowed):
User(id,email,password_hash,created_at); SessionRecord(id, user_id, token_hash, csrf_token, expires_at, created_at).
Subject(id,user_id,name,corpus_revision default 0,created_at,deleted_at nullable).
Document(id,subject_id,name,document_key nullable,active_version_id nullable,deleted_at nullable,created_at).
DocumentVersion(id,document_id,version int,sha256,file_path,size_bytes,status,page_count,text_page_count,chunk_count,warning JSON,error_code nullable,error_message nullable,embedding_model,embedding_dimensions,config_version,created_at). Unique(document_id,version). Partial uniqueness sha256 per subject handled by upload locking and subject locking; versions can reuse hash across documents only when rejected as duplicate in transaction.
DocumentPage(id,version_id,page_number,text,has_text,created_at) unique version/page. Chunk(id,version_id,ordinal,text,token_count,page_start,page_end,pages JSON,content_hash,embedding Vector(dim config),embedding_model,config_version,created_at) unique(version,ordinal); lexical computed via to_tsvector('simple',text) GIN expression index.
Job(id,user_id,subject_id,document_id nullable,version_id nullable,kind [ingestion|summary|evaluation],status [queued|parsing|chunking|embedding|running|ready|failed|needs_ocr|cancelled],progress JSON,checkpoint JSON,result JSON,error_code nullable,error_message nullable,attempts int,heartbeat_at nullable,enqueued_at nullable,created_at,updated_at). Persistent reconciler claims using advisory locks/heartbeat.
Conversation(id,subject_id,title,created_at); Message(id,conversation_id,role,content,citations JSON,debug JSON,corpus_revision,created_at). ToolRun(id,message_id nullable,user_id,subject_id,name,arguments JSON,result JSON,latency_ms,status,created_at).
UsageEvent(id,user_id,subject_id nullable,job_id nullable,message_id nullable,kind,model,input_tokens,output_tokens,cached_tokens,latency_ms,retries,cache_hit,estimated_cost_usd nullable,created_at).
EmbeddingCache(id,user_id,content_hash,model,dimensions,embedding JSON,created_at) unique(user,hash,model,dimensions).
Summary(id,version_id,config_key,status,job_id nullable,page_start,page_end,content,created_at) unique(version,config_key,page_start,page_end).
EvaluationRun(id,user_id,subject_id,job_id nullable,name,dataset JSON,mapping JSON,config JSON,status,report JSON,created_at). EvaluationResult(id,run_id,question_id,mode,result JSON,created_at).

Services assigned ingestion: `parser.py`, `chunking.py`, `ingestion.py`, `worker.py`. exports ingestion.ingest_job(job_id, provider=None); worker.dispatch_job(job_id), worker.reconcile_jobs(); Celery app worker.celery_app; ingestion may import provider lazily. worker routes kind ingestion to ingest_job, summary to rag.run_summary_job(job_id), evaluation to evaluation.run_evaluation_job(job_id). API creates and commits Job before dispatch_job; failed dispatch retains queued.
Provider assigned RAG: `provider.py` exports OpenAIProvider with `embed(texts, *, user_id, subject_id=None, job_id=None, db=None)` -> list[list[float]], `respond(input, *, tools=None, user_id, subject_id=None, job_id=None, db=None, max_output_tokens=None)` -> SDK Response-like object; factory `get_provider()` production only. Usage commits must not commit caller transaction unexpectedly. Token helpers `tokens.py`: count_tokens(text), trim_tokens(text,limit).
RAG `retrieval.py`: retrieve(db,user_id,subject_id,query,mode=None,limit=None,provider=None,job_id=None) -> list dict evidence {id,chunk_id,document_id,version_id,document_name,version,page_start,page_end,text,score}. `rag.py`: answer(db,user_id,subject_id,question,conversation_id=None,mode='direct',retrieval_mode=None,provider=None) -> dict {answer,citations,debug,conversation_id,message_id}; run_summary_job(job_id); create_summary_job(db,user_id,subject_id,document_id,page_start=None,page_end=None,confirmed=False) -> dict. RAG endpoints module `chat_api.py` exports router with full /api/subjects/... paths. Core include router lazily. Use existing core auth dependencies.
Evaluation agent `evaluation.py`, `evaluation_api.py` exports router with full /api paths; CLI `python -m app.eval_cli`. Fixture scripts, tests specific evaluation. Evaluation endpoints GET/POST `/api/subjects/{subject_id}/evaluations` (POST multipart file + mapping JSON string; config JSON string); POST `.../{run_id}/run`; GET `.../{run_id}`; GET `.../{run_id}/export?format=json|csv|md`. Document keys explicitly mapped at upload. Evaluation run worker reuses retrieval/rag; separate dataset.

Frontend contract:
GET /api/config -> max_upload_mb,max_pdf_pages,openai_configured,chat_model,retrieval_mode;
POST /api/auth/register or login JSON {email,password} -> user {id,email},csrf_token; GET /api/auth/me same; POST /api/auth/logout. Cookies same-origin; mutations header X-CSRF-Token from auth response.
GET /api/subjects -> list; POST {name}; PATCH /api/subjects/{id} {name}; DELETE.
GET /api/subjects/{sid}/documents -> list documents with id,name,document_key,active_version_id,created_at, versions list, latest_version, job (latest). Version includes status,page_count,text_page_count,chunk_count,version,warning,error_message.
POST /api/subjects/{sid}/documents multipart file (+document_key optional) -> {document_id,job_id,duplicate}; replacement POST .../documents/{did}/versions multipart file. DELETE .../documents/{did}. GET .../documents/{did}/pdf?version_id=... authenticated inline PDF.
GET /api/subjects/{sid}/jobs -> list; GET .../jobs/{jid}; POST .../jobs/{jid}/retry.
GET/POST /api/subjects/{sid}/conversations -> list / new {title}; GET .../conversations/{cid}/messages -> list with citation state enrichment.
POST /api/subjects/{sid}/chat {question,conversation_id nullable,mode:'direct'|'assistant',retrieval_mode:'dense'|'lexical'|'hybrid'} -> answer result above.
POST /api/subjects/{sid}/documents/{did}/summary {page_start:null|int,page_end:null|int,confirmed:bool} -> estimate or job (explicit confirmation for long).
GET /api/subjects/{sid}/usage -> summary usage list/aggregate.
GET /api/health/live; GET /api/health/ready (DB/Redis; missing key info not liveness fail).

Conventions: list endpoints return arrays except auth wrapped above; errors JSON {error:{code,message},request_id}. Numeric IDs citations stable response-local, PDF physical page 1-based. All dependencies pydantic lower case settings; core agent to document actual names in config. No fallback fake provider in runtime. Tests can inject provider objects directly. No SQLite acceptance substitution.
