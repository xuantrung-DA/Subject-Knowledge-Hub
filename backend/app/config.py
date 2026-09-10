from pathlib import Path
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)
    app_name: str = "Subject Knowledge Hub"
    database_url: str = "postgresql+psycopg://hub:hub@postgres:5432/hub"
    redis_url: str = "redis://redis:6379/0"
    storage_dir: Path = Path("/data/pdfs")
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dimensions: int = Field(default=1536, ge=1, le=3072)
    openai_timeout_seconds: float = 60.0
    openai_max_retries: int = Field(default=3, ge=0)
    max_upload_mb: int = Field(default=100, ge=1, le=1000)
    max_pdf_pages: int = Field(default=1200, ge=1, le=10000)
    parser_max_page_chars: int = 300000
    parse_checkpoint_pages: int = Field(default=10, ge=1)
    chunk_tokens: int = Field(default=600, ge=32)
    chunk_overlap_tokens: int = Field(default=80, ge=0)
    chunk_page_boundaries: bool = True
    embedding_batch_size: int = Field(default=64, ge=1)
    embedding_batch_tokens: int = Field(default=16000, ge=32)
    max_ingestion_tokens: int = Field(default=2000000, ge=1)
    max_ingestion_calls: int = Field(default=200, ge=1)
    retrieval_mode: str = "dense"
    retrieval_top_k: int = Field(default=6, ge=1)
    retrieval_candidates: int = Field(default=20, ge=1)
    max_context_tokens: int = Field(default=4500, ge=1)
    max_history_tokens: int = Field(default=1500, ge=0)
    max_output_tokens: int = Field(default=900, ge=1)
    max_input_tokens: int = Field(default=9000, ge=1)
    max_question_tokens: int = Field(default=24000, ge=1)
    max_question_calls: int = Field(default=5, ge=1)
    max_tool_rounds: int = Field(default=3, ge=1)
    max_tool_output_tokens: int = 4500
    max_tool_page_range: int = 10
    max_summary_tokens: int = Field(default=150000, ge=1)
    max_summary_calls: int = Field(default=100, ge=1)
    summary_confirmation_tokens: int = 12000
    summary_batch_tokens: int = 4500
    answer_cache_ttl: int = 600
    query_cache_ttl: int = 3600
    config_version: str = "v1"
    prompt_version: str = "v2"
    pricing_json: str = "{}"
    pricing_updated_at: str = ""
    session_cookie_name: str = "subject_hub_session"
    session_days: int = Field(default=7, ge=1)
    cookie_secure: bool = False
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    chat_rate_limit_per_minute: int = Field(default=12, ge=1)
    auth_rate_limit_per_minute: int = Field(default=20, ge=1)
    max_user_jobs: int = Field(default=10, ge=1)
    job_stale_seconds: int = Field(default=180, ge=10)
    job_reconcile_seconds: int = Field(default=30, ge=1)
    job_max_attempts: int = Field(default=4, ge=1)
    job_timeout_seconds: int = Field(default=7200, ge=1)
    log_level: str = "INFO"
    test_mode: bool = False

    @model_validator(mode="after")
    def coherent_limits(self):
        if self.chunk_overlap_tokens >= self.chunk_tokens:
            raise ValueError("CHUNK_OVERLAP_TOKENS must be smaller than CHUNK_TOKENS")
        if self.retrieval_top_k > self.retrieval_candidates:
            raise ValueError("RETRIEVAL_TOP_K cannot exceed RETRIEVAL_CANDIDATES")
        return self

    @field_validator("retrieval_mode")
    @classmethod
    def valid_retrieval(cls, value):
        if value not in {"dense", "lexical", "hybrid"}:
            raise ValueError("RETRIEVAL_MODE must be dense, lexical or hybrid")
        return value


settings = Settings()
