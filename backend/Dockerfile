# syntax=docker/dockerfile:1
FROM python:3.12.11-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.8 /uv /uvx /usr/local/bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken \
    PATH=/app/.venv/bin:$PATH
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY ruff.toml /ruff.toml
COPY backend/pyproject.toml backend/uv.lock ./
# Development tools are deliberately included so documented offline tests can run
# in the identical image. Runtime never selects a fake provider automatically.
RUN uv sync --frozen --no-install-project \
    && python -c "import tiktoken; tiktoken.get_encoding('cl100k_base'); tiktoken.get_encoding('o200k_base')"
COPY backend/ ./
COPY scripts/ ./scripts/
COPY fixtures/ ./fixtures/
RUN groupadd --gid 10001 hub \
    && useradd --uid 10001 --gid hub --no-create-home hub \
    && mkdir -p /data/pdfs /app/artifacts \
    && chown -R hub:hub /data/pdfs /app/artifacts /app/fixtures \
    && chmod -R a+rX /opt/tiktoken
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
