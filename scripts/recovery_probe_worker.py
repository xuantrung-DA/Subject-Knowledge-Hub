"""Explicit offline fault-injection worker, never imported by the application."""

import json
import os
from pathlib import Path
import time
from app.config import settings

if not settings.test_mode or settings.openai_api_key or not os.environ.get("SKH_RECOVERY_PROBE"):
    raise RuntimeError("Recovery probe requires TEST_MODE, an empty API key, and its explicit fixture directory.")

probe = Path(os.environ["SKH_RECOVERY_PROBE"])


class ProbeProvider:
    def __init__(self):
        self.calls = 0

    def embed(self, texts, **kwargs):
        self.calls += 1
        with (probe / "calls.jsonl").open("a") as stream:
            stream.write(json.dumps({"job_id": kwargs.get("job_id"), "texts": texts, "pid": os.getpid()}) + "\n")
        if self.calls == 2 and not (probe / "paused").exists():
            (probe / "paused").write_text("second batch entered; first batch committed")
            time.sleep(120)
        return [[1.0] + [0.0] * (settings.openai_embedding_dimensions - 1) for _ in texts]


import app.provider  # noqa: E402 - guard above must run before installing the probe

app.provider.get_provider = ProbeProvider
