#!/usr/bin/env python3
"""Consistent local backup using Docker; Python 3.10+ on the host is sufficient."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def compose(*args: str, **kwargs):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True, **kwargs)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "backups")
    parser.add_argument("--project-name", help="Compose project to back up; defaults to the current Compose project")
    args = parser.parse_args()
    if args.project_name:
        os.environ["COMPOSE_PROJECT_NAME"] = args.project_name
    args.output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = args.output / f"subject-hub-{stamp}.tar.gz"
    running = compose("ps", "--services", "--status", "running", capture_output=True, text=True).stdout.split()
    resume = [name for name in ("api", "worker", "web") if name in running]
    compose("stop", "web", "api", "worker")
    try:
        compose("up", "-d", "--wait", "postgres", "redis")
        with tempfile.TemporaryDirectory(prefix="subject-hub-backup-") as tmp:
            staging = Path(tmp)
            with (staging / "database.dump").open("wb") as out:
                compose("exec", "-T", "postgres", "pg_dump", "-U", "hub", "-d", "hub", "-Fc", stdout=out)
            code = (
                "import sys,tarfile; "
                "archive=tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz'); "
                "archive.add('/data/pdfs',arcname='pdfs'); archive.close()"
            )
            with (staging / "pdfs.tar.gz").open("wb") as out:
                compose("run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "api", "-c", code, stdout=out)
            manifest = {
                "format_version": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "files": {name: sha256(staging / name) for name in ("database.dump", "pdfs.tar.gz")},
                "note": "Restore with the same application source and embedding configuration. .env is excluded.",
            }
            (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            partial = destination.with_suffix(".partial")
            try:
                with tarfile.open(partial, "w:gz") as archive:
                    for name in ("database.dump", "pdfs.tar.gz", "manifest.json"):
                        archive.add(staging / name, arcname=name)
                partial.replace(destination)
            finally:
                partial.unlink(missing_ok=True)
        print(f"Backup saved: {destination.resolve()}")
    finally:
        if resume:
            compose("start", *resume)


if __name__ == "__main__":
    main()
