# Browser acceptance against the real application

These Playwright tests do not intercept routes, mock APIs, or launch a fake provider. Start the actual Docker stack first. The default test creates isolated accounts/subjects, checks missing-document controls, uploads only empty/corrupt fixtures, waits for a real failed job, checks cross-account resource access, reload persistence, and the 390px layout. It does not call generation or upload a valid PDF.

From `frontend/`:

```bash
npm ci
npx playwright install chromium
npm run test:browser
```

The optional second test uses **real paid OpenAI** for two PDF ingestions (the original and its replacement), one question and a two-page summary, plus a lexical-only evaluation. It also checks failed replacement and historical summary labels after replacement/deletion. Review `compose.live-smoke.yaml`, set the actual API key, and start with that override first. The test refuses large configured per-question/ingestion budgets. The planned envelope is two ingestions at 25,000 tokens each, one question at 8,000 tokens and one summary at 25,000 tokens (83,000 reserved tokens across these operations); the repeated upload must deduplicate. The corrupt replacement has no embedding call. Real usage is visible in the application's usage records. A lost provider response may mean provider usage is not fully reported.

```bash
# Bash / WSL, from repository root:
docker compose -f compose.yaml -f compose.live-smoke.yaml up --build -d
cd frontend
SKH_BROWSER_LIVE=1 npm run test:browser
```

```powershell
# PowerShell, from repository root:
docker compose -f compose.yaml -f compose.live-smoke.yaml up --build -d
Set-Location frontend
$env:SKH_BROWSER_LIVE = "1"
npm run test:browser
Remove-Item Env:SKH_BROWSER_LIVE
```

Optional `SKH_BROWSER_URL` defaults to `http://localhost:3000`. Reports are written to `artifacts/browser-report`, screenshots/traces to `artifacts/browser`. Tests leave their clearly named accounts/subjects for inspection. They do not reset the database.

Authoring or listing these tests is **not** browser acceptance. See `docs/test-report.md` for whether they were actually executed. The separate `scripts/live_smoke.py` covers the larger ten-question/five-tool smoke; this browser test is intentionally smaller.
