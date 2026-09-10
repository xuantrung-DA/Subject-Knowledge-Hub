#!/usr/bin/env python3
"""Restore a project backup. Requires explicit --replace-data acknowledgement."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def compose(*args: str, **kwargs):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True, **kwargs)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_pdf_archive(path: Path) -> None:
    with tarfile.open(path) as archive:
        for member in archive:
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or ".." in relative.parts or not relative.parts or relative.parts[0] != "pdfs":
                raise ValueError("Unsafe PDF archive path")
            if not (member.isfile() or member.isdir()):
                raise ValueError("PDF archive must contain only regular files and directories")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--replace-data", action="store_true", help="Replace current database/PDFs and clear Redis")
    parser.add_argument(
        "--project-name", help="Target Compose project; use an isolated project when rehearsing restore"
    )
    args = parser.parse_args()
    if not args.replace_data:
        parser.error("Restore replaces local data. Back up first, then pass --replace-data explicitly.")
    if args.project_name:
        os.environ["COMPOSE_PROJECT_NAME"] = args.project_name
    with tempfile.TemporaryDirectory(prefix="subject-hub-restore-") as tmp:
        staging = Path(tmp)
        expected = {"database.dump", "pdfs.tar.gz", "manifest.json"}
        with tarfile.open(args.archive) as archive:
            members = archive.getmembers()
            if (
                {item.name for item in members} != expected
                or len(members) != 3
                or any(not item.isfile() for item in members)
            ):
                raise ValueError("Unrecognized backup format")
            for member in members:
                with archive.extractfile(member) as source, (staging / member.name).open("wb") as target:
                    shutil.copyfileobj(source, target)
        manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("format_version") != 1:
            raise ValueError("Unsupported backup version")
        for name in ("database.dump", "pdfs.tar.gz"):
            if sha256(staging / name) != manifest.get("files", {}).get(name):
                raise ValueError(f"Backup checksum mismatch: {name}")
        validate_pdf_archive(staging / "pdfs.tar.gz")
        compose("stop", "web", "api", "worker")
        compose("up", "-d", "--wait", "postgres", "redis")
        # If a restore step fails, leave writers stopped so partial state is visible.
        with (staging / "database.dump").open("rb") as source:
            compose(
                "exec",
                "-T",
                "postgres",
                "pg_restore",
                "-U",
                "hub",
                "-d",
                "hub",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--exit-on-error",
                stdin=source,
            )
        code = """
import pathlib,shutil,sys,tarfile
root=pathlib.Path('/data/pdfs')
for child in root.iterdir():
    shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
with tarfile.open(fileobj=sys.stdin.buffer,mode='r|gz') as archive:
    for member in archive:
        parts=pathlib.PurePosixPath(member.name).parts
        if not parts or parts[0] != 'pdfs' or '..' in parts or member.name.startswith('/'):
            raise ValueError('Unsafe archive')
        member.name='/'.join(parts[1:])
        if member.name:
            archive.extract(member,path=root,filter='data')
"""
        with (staging / "pdfs.tar.gz").open("rb") as source:
            compose("run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "api", "-c", code, stdin=source)
        compose("exec", "-T", "redis", "redis-cli", "FLUSHALL")
        compose("run", "--rm", "--no-deps", "migrate")
        compose("up", "-d", "--wait")
        print("Restore completed. Queued jobs are recovered from PostgreSQL by the reconciler.")


if __name__ == "__main__":
    main()
