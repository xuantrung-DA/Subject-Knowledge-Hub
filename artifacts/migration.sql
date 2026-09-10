BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001_initial

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE users (
    id VARCHAR(36) NOT NULL, 
    email VARCHAR(320) NOT NULL, 
    password_hash TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (email)
);

CREATE TABLE sessions (
    id VARCHAR(36) NOT NULL, 
    user_id VARCHAR(36) NOT NULL, 
    token_hash VARCHAR(64) NOT NULL, 
    csrf_token VARCHAR(128) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    UNIQUE (token_hash)
);

CREATE INDEX ix_sessions_user_id ON sessions (user_id);

CREATE INDEX ix_sessions_expires_at ON sessions (expires_at);

CREATE TABLE subjects (
    id VARCHAR(36) NOT NULL, 
    user_id VARCHAR(36) NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    corpus_revision INTEGER DEFAULT '0' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_subjects_user_id ON subjects (user_id);

CREATE TABLE embedding_cache (
    id VARCHAR(36) NOT NULL, 
    user_id VARCHAR(36) NOT NULL, 
    content_hash VARCHAR(64) NOT NULL, 
    model VARCHAR(100) NOT NULL, 
    dimensions INTEGER NOT NULL, 
    embedding JSON NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_embedding_cache UNIQUE (user_id, content_hash, model, dimensions), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_embedding_cache_user_id ON embedding_cache (user_id);

CREATE TABLE documents (
    id VARCHAR(36) NOT NULL, 
    subject_id VARCHAR(36) NOT NULL, 
    name VARCHAR(255) NOT NULL, 
    document_key VARCHAR(120), 
    source_type VARCHAR(30) DEFAULT 'pdf' NOT NULL, 
    active_version_id VARCHAR(36), 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(subject_id) REFERENCES subjects (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_documents_subject_key ON documents (subject_id, document_key) WHERE deleted_at IS NULL AND document_key IS NOT NULL;

CREATE INDEX ix_documents_subject_id ON documents (subject_id);

CREATE TABLE conversations (
    id VARCHAR(36) NOT NULL, 
    subject_id VARCHAR(36) NOT NULL, 
    title VARCHAR(200) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(subject_id) REFERENCES subjects (id) ON DELETE CASCADE
);

CREATE INDEX ix_conversations_subject_id ON conversations (subject_id);

CREATE TABLE document_versions (
    id VARCHAR(36) NOT NULL, 
    document_id VARCHAR(36) NOT NULL, 
    version INTEGER NOT NULL, 
    sha256 VARCHAR(64) NOT NULL, 
    file_path TEXT NOT NULL, 
    size_bytes INTEGER NOT NULL, 
    status VARCHAR(30) NOT NULL, 
    page_count INTEGER NOT NULL, 
    text_page_count INTEGER NOT NULL, 
    chunk_count INTEGER NOT NULL, 
    warning JSON NOT NULL, 
    error_code VARCHAR(100), 
    error_message TEXT, 
    embedding_model VARCHAR(100) NOT NULL, 
    embedding_dimensions INTEGER NOT NULL, 
    config_version VARCHAR(100) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_document_version UNIQUE (document_id, version), 
    FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE
);

CREATE INDEX ix_document_versions_sha256 ON document_versions (sha256);

CREATE INDEX ix_document_versions_document_id ON document_versions (document_id);

CREATE TABLE messages (
    id VARCHAR(36) NOT NULL, 
    conversation_id VARCHAR(36) NOT NULL, 
    role VARCHAR(20) NOT NULL, 
    content TEXT NOT NULL, 
    citations JSON NOT NULL, 
    debug JSON NOT NULL, 
    corpus_revision INTEGER NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
);

CREATE INDEX ix_messages_conversation_id ON messages (conversation_id);

CREATE TABLE document_pages (
    id VARCHAR(36) NOT NULL, 
    version_id VARCHAR(36) NOT NULL, 
    page_number INTEGER NOT NULL, 
    text TEXT NOT NULL, 
    has_text BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_version_page UNIQUE (version_id, page_number), 
    FOREIGN KEY(version_id) REFERENCES document_versions (id) ON DELETE CASCADE
);

CREATE INDEX ix_document_pages_version_id ON document_pages (version_id);

CREATE TABLE chunks (
    id VARCHAR(36) NOT NULL, 
    version_id VARCHAR(36) NOT NULL, 
    ordinal INTEGER NOT NULL, 
    text TEXT NOT NULL, 
    token_count INTEGER NOT NULL, 
    page_start INTEGER, 
    page_end INTEGER, 
    paragraph_ids JSON, 
    pages JSON NOT NULL, 
    content_hash VARCHAR(64) NOT NULL, 
    embedding VECTOR(1536), 
    embedding_model VARCHAR(100) NOT NULL, 
    config_version VARCHAR(100) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_version_chunk UNIQUE (version_id, ordinal), 
    FOREIGN KEY(version_id) REFERENCES document_versions (id) ON DELETE CASCADE
);

CREATE INDEX ix_chunks_version_id ON chunks (version_id);

CREATE INDEX ix_chunks_content_hash ON chunks (content_hash);

CREATE INDEX ix_chunks_lexical ON chunks USING gin (to_tsvector('simple'::regconfig, text));

CREATE TABLE jobs (
    id VARCHAR(36) NOT NULL, 
    user_id VARCHAR(36) NOT NULL, 
    subject_id VARCHAR(36) NOT NULL, 
    document_id VARCHAR(36), 
    version_id VARCHAR(36), 
    kind VARCHAR(30) NOT NULL, 
    status VARCHAR(30) NOT NULL, 
    progress JSON NOT NULL, 
    checkpoint JSON NOT NULL, 
    result JSON NOT NULL, 
    error_code VARCHAR(100), 
    error_message TEXT, 
    attempts INTEGER NOT NULL, 
    heartbeat_at TIMESTAMP WITH TIME ZONE, 
    enqueued_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id), 
    FOREIGN KEY(subject_id) REFERENCES subjects (id), 
    FOREIGN KEY(document_id) REFERENCES documents (id), 
    FOREIGN KEY(version_id) REFERENCES document_versions (id)
);

CREATE INDEX ix_jobs_subject_id ON jobs (subject_id);

CREATE INDEX ix_jobs_status ON jobs (status);

CREATE INDEX ix_jobs_user_id ON jobs (user_id);

CREATE INDEX ix_jobs_document_id ON jobs (document_id);

CREATE INDEX ix_jobs_version_id ON jobs (version_id);

CREATE TABLE tool_runs (
    id VARCHAR(36) NOT NULL, 
    message_id VARCHAR(36), 
    user_id VARCHAR(36) NOT NULL, 
    subject_id VARCHAR(36) NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    arguments JSON NOT NULL, 
    result JSON NOT NULL, 
    latency_ms FLOAT NOT NULL, 
    status VARCHAR(30) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(message_id) REFERENCES messages (id) ON DELETE SET NULL, 
    FOREIGN KEY(user_id) REFERENCES users (id), 
    FOREIGN KEY(subject_id) REFERENCES subjects (id)
);

CREATE INDEX ix_tool_runs_subject_id ON tool_runs (subject_id);

CREATE INDEX ix_tool_runs_message_id ON tool_runs (message_id);

CREATE TABLE usage_events (
    id VARCHAR(36) NOT NULL, 
    user_id VARCHAR(36) NOT NULL, 
    subject_id VARCHAR(36), 
    job_id VARCHAR(36), 
    message_id VARCHAR(36), 
    kind VARCHAR(50) NOT NULL, 
    model VARCHAR(100) NOT NULL, 
    input_tokens INTEGER NOT NULL, 
    output_tokens INTEGER NOT NULL, 
    cached_tokens INTEGER NOT NULL, 
    latency_ms FLOAT NOT NULL, 
    retries INTEGER NOT NULL, 
    cache_hit BOOLEAN NOT NULL, 
    estimated_cost_usd FLOAT, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id), 
    FOREIGN KEY(subject_id) REFERENCES subjects (id), 
    FOREIGN KEY(job_id) REFERENCES jobs (id), 
    FOREIGN KEY(message_id) REFERENCES messages (id)
);

CREATE INDEX ix_usage_events_user_id ON usage_events (user_id);

CREATE INDEX ix_usage_events_subject_id ON usage_events (subject_id);

CREATE INDEX ix_usage_events_job_id ON usage_events (job_id);

CREATE INDEX ix_usage_events_message_id ON usage_events (message_id);

CREATE TABLE summaries (
    id VARCHAR(36) NOT NULL, 
    version_id VARCHAR(36) NOT NULL, 
    config_key VARCHAR(200) NOT NULL, 
    status VARCHAR(30) NOT NULL, 
    job_id VARCHAR(36), 
    page_start INTEGER NOT NULL, 
    page_end INTEGER NOT NULL, 
    content TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_summary_scope UNIQUE (version_id, config_key, page_start, page_end), 
    FOREIGN KEY(version_id) REFERENCES document_versions (id) ON DELETE CASCADE, 
    FOREIGN KEY(job_id) REFERENCES jobs (id)
);

CREATE INDEX ix_summaries_version_id ON summaries (version_id);

CREATE TABLE evaluation_runs (
    id VARCHAR(36) NOT NULL, 
    user_id VARCHAR(36) NOT NULL, 
    subject_id VARCHAR(36) NOT NULL, 
    job_id VARCHAR(36), 
    name VARCHAR(200) NOT NULL, 
    dataset JSON NOT NULL, 
    mapping JSON NOT NULL, 
    config JSON NOT NULL, 
    status VARCHAR(30) NOT NULL, 
    report JSON NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id), 
    FOREIGN KEY(subject_id) REFERENCES subjects (id), 
    FOREIGN KEY(job_id) REFERENCES jobs (id)
);

CREATE INDEX ix_evaluation_runs_subject_id ON evaluation_runs (subject_id);

CREATE INDEX ix_evaluation_runs_user_id ON evaluation_runs (user_id);

CREATE TABLE evaluation_results (
    id VARCHAR(36) NOT NULL, 
    run_id VARCHAR(36) NOT NULL, 
    question_id VARCHAR(200) NOT NULL, 
    mode VARCHAR(30) NOT NULL, 
    result JSON NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_evaluation_result UNIQUE (run_id, question_id, mode), 
    FOREIGN KEY(run_id) REFERENCES evaluation_runs (id) ON DELETE CASCADE
);

CREATE INDEX ix_evaluation_results_run_id ON evaluation_results (run_id);

ALTER TABLE documents ADD CONSTRAINT fk_documents_active_version FOREIGN KEY(active_version_id) REFERENCES document_versions (id) ON DELETE SET NULL;

INSERT INTO alembic_version (version_num) VALUES ('0001_initial') RETURNING alembic_version.version_num;

COMMIT;

