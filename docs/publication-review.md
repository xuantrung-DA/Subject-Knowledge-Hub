# GitHub publication review — 2026-09-10

This release prepares the verified local portfolio application for its first GitHub publication at https://github.com/xuantrung-DA/Subject-Knowledge-Hub.

## Changes

- Standardized Python formatting and removed unused imports; documented the few imports whose initialization order is intentional.
- Added line-ending/editor rules and excluded TypeScript build state from Git.
- Added Python lint/format and frontend formatting checks to CI.
- Rewrote the public README around installation, actual features, architecture, measured results and limits.
- Added a self-contained root `HANDOVER.md` with module ownership, data flow, invariants and maintenance recipes.
- Separated detailed operational instructions from the README and corrected the expanded live browser test description.
- Retained original benchmark artifacts; new publication checks are stored separately under `artifacts/runs/20260910-github/`.

## Verification

| Check | Result | Evidence |
| --- | --- | --- |
| Backend after dependency patches | 90 passed, no skips, 8.58 s | [JUnit](../artifacts/runs/20260910-github/backend-tests.xml) |
| Actual-stack Chromium after patches | 1 offline flow passed, 10.9 s | [Log](../artifacts/runs/20260910-github/browser-final.log) |
| Python lint/format | Pass; 48 source/test/script/migration files checked | Local Ruff and CI definition |
| Frontend formatting/typecheck/build | Pass; Vite 6.4.3, production bundle built | [Build](../artifacts/runs/20260910-github/final-build.log) |
| Python dependency audit | 0 known advisories in 77 installed packages | [Audit](../artifacts/runs/20260910-github/backend-dependency-after.json) |
| npm dependency audit | 0 known advisories | [Audit](../artifacts/runs/20260910-github/frontend-dependency-after.json) |
| PDF fixture validation with patched parser | 50/50 source pages verified | [JSON](../artifacts/runs/20260910-github/pdf-validation.json) |
| Publication files and local Markdown links | Pass | [Audit](../artifacts/runs/20260910-github/publication-audit.json) |

The initial Python scan reported 55 advisories across five packages. Updated pins: FastAPI 0.141.1, Starlette 1.3.1, pypdf 6.16.1, pdfplumber 0.11.10 (pdfminer.six 20260107), python-multipart 0.0.31 and pytest 9.0.3. Frontend patches: Playwright 1.55.1 and Vite 6.4.3. Model/embedding configuration and application schema remain the same.

Versions were selected from published package metadata and advisory fix ranges; see [FastAPI release notes](https://fastapi.tiangolo.com/release-notes/) and [Vite advisory](https://github.com/vitejs/vite/security/advisories/GHSA-fx2h-pf6j-xcff). Clean audit means no matching known advisory in the queried database, not a guarantee against every vulnerability.

The first post-upgrade browser attempt lacked the matching Chromium binary; after installing that binary the full offline flow passed. Prior paid browser/benchmark evidence remains in the implementation run; this publication verification made no additional paid API calls.

Publication checks are recorded in the run directory. The original paid benchmark was not rerun merely for formatting/documentation changes. Its baseline, held-out dataset, raw results and cost estimates remain historical evidence for the implementation snapshot.

The Git publication is checked for generated/local data, credentials, tracked-file size, Markdown targets and consistency with the source manifest before push. This inspection covers the files actually staged for publication, including binary files for exact local-secret matching.

## Scope

No public application deployment is included. GitHub hosts the source and evidence; Docker Compose runs the application. AI quality limitations, the synthetic benchmark scope and QASPER's lower recall remain stated in README and the benchmark report.
