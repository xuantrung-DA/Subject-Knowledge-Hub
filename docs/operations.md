# Local operations

Run from the repository root. The default Compose project is subject-knowledge-hub; fresh ports are 3000/8000. The original workstation uses 13000/18000.

## Health and settings

```bash
docker compose ps -a
docker compose logs --tail 100 migrate api worker
docker compose restart worker
docker compose down
docker compose up -d --wait
```

Expect five healthy services and migrate exit 0. Readiness checks PostgreSQL/Redis/vector dimensions; Nginx health and worker ping have narrower meanings. Down retains volumes. After changing env, recreate API/worker/web:

```bash
docker compose up -d --force-recreate api worker web
```

Set WEB_PORT/API_PORT and matching ALLOWED_ORIGINS if changing ports. An existing PostgreSQL volume keeps its original password; editing POSTGRES_PASSWORD does not change it. Embedding-space changes require a new corpus or migration/reindex. Keep chunk settings stable during partial jobs.

## Backup and isolated restore

Host Python 3.10+ and Docker are enough (Windows can use py -3).

```bash
python scripts/backup.py --project-name subject-knowledge-hub --output backups
```

The script stops writers briefly, saves PostgreSQL/PDFs together with checksums and restarts previously running services. Archives contain accounts/documents/history and must stay private. Env and API keys are excluded.

Restore with matching source/embedding configuration into a new project and free ports. The explicit flag replaces the target project's data:

```powershell
$env:WEB_PORT = "13300"
$env:API_PORT = "18800"
$env:ALLOWED_ORIGINS = "http://localhost:13300,http://127.0.0.1:13300"
python scripts/restore.py backups/subject-hub-YYYYMMDDTHHMMSSZ.tar.gz --project-name subject-hub-restore --replace-data
docker compose -p subject-hub-restore ps -a
Remove-Item Env:WEB_PORT, Env:API_PORT, Env:ALLOWED_ORIGINS
```

Restore validates paths/hashes, replaces DB/PDFs, clears target Redis, migrates and starts. Failure after replacement leaves writers stopped. Inspect the restored UI/files; scripts/state_snapshot.py can compare table/PDF fingerprints. Stop the rehearsal with docker compose -p subject-hub-restore down.

## Tests and live smoke

```bash
docker compose -p subject-hub-test -f compose.yaml -f compose.test.yaml run --build --rm tests
docker compose -p subject-hub-test -f compose.yaml -f compose.test.yaml down
```

Integration/recovery tests require separate data. A disposable container loses /app/artifacts on removal; add a writable bind mount to retain reports. Linux hosts must give the container user write access to the output folder.

The first command below only reports the live-smoke envelope:

```bash
docker compose exec -T api python scripts/live_smoke.py
```

For explicitly authorized paid execution:

```bash
docker compose -f compose.yaml -f compose.live-smoke.yaml up -d --force-recreate api worker
docker compose exec -T api python scripts/live_smoke.py --register --execute-paid
docker compose cp api:/app/artifacts/live-smoke.json artifacts/live-smoke.json
docker compose up -d --force-recreate api worker
```

The script creates an isolated test account/subject. Other live scripts have separate budgets. Token/call caps are not global USD billing limits.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| API never starts | Migration logs, DB password and schema/extension permissions |
| Vector schema mismatch | Current dimension vs OPENAI_EMBEDDING_DIMENSIONS; reindex/migration |
| Job stays queued | Worker/Redis health, durable job/enqueued/heartbeat and reconciler |
| needs_ocr | Extractable text is absent; OCR externally before upload |
| Replacement fails | Inspect failed version/job; previous complete version remains active |
| Historical source label | Replaced/deleted is expected; never redirect old citations silently |
| Key/quota error | Server-side configuration and provider account access |
| Timeout | Refresh durable state before retrying |
| Windows NativeCommandError | Separate stderr wrapping from subprocess exit code and structured result |

docker compose down -v deletes the selected project's volumes. Use it only for deliberate reset, not normal shutdown or migration repair. Do not publish env dumps, browser sessions or backup data.
