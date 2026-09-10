"""Initial schema snapshot. The vector dimension is fixed on first bootstrap.

Existing databases never change dimensions automatically; an explicit reindex/migration
is required. Keep this historical DDL snapshot stable for later schema revisions.
"""

from alembic import op
from app.config import settings

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

UP = [
    "\nCREATE TABLE users (\n\tid VARCHAR(36) NOT NULL, \n\temail VARCHAR(320) NOT NULL, \n\tpassword_hash TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (email)\n)\n\n",
    "\nCREATE TABLE sessions (\n\tid VARCHAR(36) NOT NULL, \n\tuser_id VARCHAR(36) NOT NULL, \n\ttoken_hash VARCHAR(64) NOT NULL, \n\tcsrf_token VARCHAR(128) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, \n\tUNIQUE (token_hash)\n)\n\n",
    "CREATE INDEX ix_sessions_user_id ON sessions (user_id)",
    "CREATE INDEX ix_sessions_expires_at ON sessions (expires_at)",
    "\nCREATE TABLE subjects (\n\tid VARCHAR(36) NOT NULL, \n\tuser_id VARCHAR(36) NOT NULL, \n\tname VARCHAR(200) NOT NULL, \n\tcorpus_revision INTEGER DEFAULT '0' NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tdeleted_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE\n)\n\n",
    "CREATE INDEX ix_subjects_user_id ON subjects (user_id)",
    "\nCREATE TABLE embedding_cache (\n\tid VARCHAR(36) NOT NULL, \n\tuser_id VARCHAR(36) NOT NULL, \n\tcontent_hash VARCHAR(64) NOT NULL, \n\tmodel VARCHAR(100) NOT NULL, \n\tdimensions INTEGER NOT NULL, \n\tembedding JSON NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_embedding_cache UNIQUE (user_id, content_hash, model, dimensions), \n\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE\n)\n\n",
    "CREATE INDEX ix_embedding_cache_user_id ON embedding_cache (user_id)",
    "\nCREATE TABLE documents (\n\tid VARCHAR(36) NOT NULL, \n\tsubject_id VARCHAR(36) NOT NULL, \n\tname VARCHAR(255) NOT NULL, \n\tdocument_key VARCHAR(120), \n\tsource_type VARCHAR(30) DEFAULT 'pdf' NOT NULL, \n\tactive_version_id VARCHAR(36), \n\tdeleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(subject_id) REFERENCES subjects (id) ON DELETE CASCADE\n)\n\n",
    "CREATE UNIQUE INDEX uq_documents_subject_key ON documents (subject_id, document_key) WHERE deleted_at IS NULL AND document_key IS NOT NULL",
    "CREATE INDEX ix_documents_subject_id ON documents (subject_id)",
    "\nCREATE TABLE conversations (\n\tid VARCHAR(36) NOT NULL, \n\tsubject_id VARCHAR(36) NOT NULL, \n\ttitle VARCHAR(200) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(subject_id) REFERENCES subjects (id) ON DELETE CASCADE\n)\n\n",
    "CREATE INDEX ix_conversations_subject_id ON conversations (subject_id)",
    "\nCREATE TABLE document_versions (\n\tid VARCHAR(36) NOT NULL, \n\tdocument_id VARCHAR(36) NOT NULL, \n\tversion INTEGER NOT NULL, \n\tsha256 VARCHAR(64) NOT NULL, \n\tfile_path TEXT NOT NULL, \n\tsize_bytes INTEGER NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\tpage_count INTEGER NOT NULL, \n\ttext_page_count INTEGER NOT NULL, \n\tchunk_count INTEGER NOT NULL, \n\twarning JSON NOT NULL, \n\terror_code VARCHAR(100), \n\terror_message TEXT, \n\tembedding_model VARCHAR(100) NOT NULL, \n\tembedding_dimensions INTEGER NOT NULL, \n\tconfig_version VARCHAR(100) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_document_version UNIQUE (document_id, version), \n\tFOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE\n)\n\n",
    "CREATE INDEX ix_document_versions_sha256 ON document_versions (sha256)",
    "CREATE INDEX ix_document_versions_document_id ON document_versions (document_id)",
    "\nCREATE TABLE messages (\n\tid VARCHAR(36) NOT NULL, \n\tconversation_id VARCHAR(36) NOT NULL, \n\trole VARCHAR(20) NOT NULL, \n\tcontent TEXT NOT NULL, \n\tcitations JSON NOT NULL, \n\tdebug JSON NOT NULL, \n\tcorpus_revision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE\n)\n\n",
    "CREATE INDEX ix_messages_conversation_id ON messages (conversation_id)",
    "\nCREATE TABLE document_pages (\n\tid VARCHAR(36) NOT NULL, \n\tversion_id VARCHAR(36) NOT NULL, \n\tpage_number INTEGER NOT NULL, \n\ttext TEXT NOT NULL, \n\thas_text BOOLEAN NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_version_page UNIQUE (version_id, page_number), \n\tFOREIGN KEY(version_id) REFERENCES document_versions (id) ON DELETE CASCADE\n)\n\n",
    "CREATE INDEX ix_document_pages_version_id ON document_pages (version_id)",
    "\nCREATE TABLE chunks (\n\tid VARCHAR(36) NOT NULL, \n\tversion_id VARCHAR(36) NOT NULL, \n\tordinal INTEGER NOT NULL, \n\ttext TEXT NOT NULL, \n\ttoken_count INTEGER NOT NULL, \n\tpage_start INTEGER, \n\tpage_end INTEGER, \n\tparagraph_ids JSON, \n\tpages JSON NOT NULL, \n\tcontent_hash VARCHAR(64) NOT NULL, \n\tembedding VECTOR({dimensions}), \n\tembedding_model VARCHAR(100) NOT NULL, \n\tconfig_version VARCHAR(100) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_version_chunk UNIQUE (version_id, ordinal), \n\tFOREIGN KEY(version_id) REFERENCES document_versions (id) ON DELETE CASCADE\n)\n\n",
    "CREATE INDEX ix_chunks_version_id ON chunks (version_id)",
    "CREATE INDEX ix_chunks_content_hash ON chunks (content_hash)",
    "CREATE INDEX ix_chunks_lexical ON chunks USING gin (to_tsvector('simple'::regconfig, text))",
    "\nCREATE TABLE jobs (\n\tid VARCHAR(36) NOT NULL, \n\tuser_id VARCHAR(36) NOT NULL, \n\tsubject_id VARCHAR(36) NOT NULL, \n\tdocument_id VARCHAR(36), \n\tversion_id VARCHAR(36), \n\tkind VARCHAR(30) NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\tprogress JSON NOT NULL, \n\tcheckpoint JSON NOT NULL, \n\tresult JSON NOT NULL, \n\terror_code VARCHAR(100), \n\terror_message TEXT, \n\tattempts INTEGER NOT NULL, \n\theartbeat_at TIMESTAMP WITH TIME ZONE, \n\tenqueued_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tFOREIGN KEY(subject_id) REFERENCES subjects (id), \n\tFOREIGN KEY(document_id) REFERENCES documents (id), \n\tFOREIGN KEY(version_id) REFERENCES document_versions (id)\n)\n\n",
    "CREATE INDEX ix_jobs_subject_id ON jobs (subject_id)",
    "CREATE INDEX ix_jobs_status ON jobs (status)",
    "CREATE INDEX ix_jobs_user_id ON jobs (user_id)",
    "CREATE INDEX ix_jobs_document_id ON jobs (document_id)",
    "CREATE INDEX ix_jobs_version_id ON jobs (version_id)",
    "\nCREATE TABLE tool_runs (\n\tid VARCHAR(36) NOT NULL, \n\tmessage_id VARCHAR(36), \n\tuser_id VARCHAR(36) NOT NULL, \n\tsubject_id VARCHAR(36) NOT NULL, \n\tname VARCHAR(100) NOT NULL, \n\targuments JSON NOT NULL, \n\tresult JSON NOT NULL, \n\tlatency_ms FLOAT NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(message_id) REFERENCES messages (id) ON DELETE SET NULL, \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tFOREIGN KEY(subject_id) REFERENCES subjects (id)\n)\n\n",
    "CREATE INDEX ix_tool_runs_subject_id ON tool_runs (subject_id)",
    "CREATE INDEX ix_tool_runs_message_id ON tool_runs (message_id)",
    "\nCREATE TABLE usage_events (\n\tid VARCHAR(36) NOT NULL, \n\tuser_id VARCHAR(36) NOT NULL, \n\tsubject_id VARCHAR(36), \n\tjob_id VARCHAR(36), \n\tmessage_id VARCHAR(36), \n\tkind VARCHAR(50) NOT NULL, \n\tmodel VARCHAR(100) NOT NULL, \n\tinput_tokens INTEGER NOT NULL, \n\toutput_tokens INTEGER NOT NULL, \n\tcached_tokens INTEGER NOT NULL, \n\tlatency_ms FLOAT NOT NULL, \n\tretries INTEGER NOT NULL, \n\tcache_hit BOOLEAN NOT NULL, \n\testimated_cost_usd FLOAT, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tFOREIGN KEY(subject_id) REFERENCES subjects (id), \n\tFOREIGN KEY(job_id) REFERENCES jobs (id), \n\tFOREIGN KEY(message_id) REFERENCES messages (id)\n)\n\n",
    "CREATE INDEX ix_usage_events_user_id ON usage_events (user_id)",
    "CREATE INDEX ix_usage_events_subject_id ON usage_events (subject_id)",
    "CREATE INDEX ix_usage_events_job_id ON usage_events (job_id)",
    "CREATE INDEX ix_usage_events_message_id ON usage_events (message_id)",
    "\nCREATE TABLE summaries (\n\tid VARCHAR(36) NOT NULL, \n\tversion_id VARCHAR(36) NOT NULL, \n\tconfig_key VARCHAR(200) NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\tjob_id VARCHAR(36), \n\tpage_start INTEGER NOT NULL, \n\tpage_end INTEGER NOT NULL, \n\tcontent TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_summary_scope UNIQUE (version_id, config_key, page_start, page_end), \n\tFOREIGN KEY(version_id) REFERENCES document_versions (id) ON DELETE CASCADE, \n\tFOREIGN KEY(job_id) REFERENCES jobs (id)\n)\n\n",
    "CREATE INDEX ix_summaries_version_id ON summaries (version_id)",
    "\nCREATE TABLE evaluation_runs (\n\tid VARCHAR(36) NOT NULL, \n\tuser_id VARCHAR(36) NOT NULL, \n\tsubject_id VARCHAR(36) NOT NULL, \n\tjob_id VARCHAR(36), \n\tname VARCHAR(200) NOT NULL, \n\tdataset JSON NOT NULL, \n\tmapping JSON NOT NULL, \n\tconfig JSON NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\treport JSON NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tFOREIGN KEY(subject_id) REFERENCES subjects (id), \n\tFOREIGN KEY(job_id) REFERENCES jobs (id)\n)\n\n",
    "CREATE INDEX ix_evaluation_runs_subject_id ON evaluation_runs (subject_id)",
    "CREATE INDEX ix_evaluation_runs_user_id ON evaluation_runs (user_id)",
    "\nCREATE TABLE evaluation_results (\n\tid VARCHAR(36) NOT NULL, \n\trun_id VARCHAR(36) NOT NULL, \n\tquestion_id VARCHAR(200) NOT NULL, \n\tmode VARCHAR(30) NOT NULL, \n\tresult JSON NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_evaluation_result UNIQUE (run_id, question_id, mode), \n\tFOREIGN KEY(run_id) REFERENCES evaluation_runs (id) ON DELETE CASCADE\n)\n\n",
    "CREATE INDEX ix_evaluation_results_run_id ON evaluation_results (run_id)",
    "ALTER TABLE documents ADD CONSTRAINT fk_documents_active_version FOREIGN KEY(active_version_id) REFERENCES document_versions (id) ON DELETE SET NULL",
]

DOWN = [
    "ALTER TABLE documents DROP CONSTRAINT fk_documents_active_version",
    "\nDROP TABLE evaluation_results",
    "\nDROP TABLE evaluation_runs",
    "\nDROP TABLE summaries",
    "\nDROP TABLE usage_events",
    "\nDROP TABLE tool_runs",
    "\nDROP TABLE jobs",
    "\nDROP TABLE chunks",
    "\nDROP TABLE document_pages",
    "\nDROP TABLE messages",
    "\nDROP TABLE document_versions",
    "\nDROP TABLE conversations",
    "\nDROP TABLE documents",
    "\nDROP TABLE embedding_cache",
    "\nDROP TABLE subjects",
    "\nDROP TABLE sessions",
    "\nDROP TABLE users",
]


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for statement in UP:
        op.execute(statement.replace("{dimensions}", str(settings.openai_embedding_dimensions)))


def downgrade():
    for statement in DOWN:
        op.execute(statement)
