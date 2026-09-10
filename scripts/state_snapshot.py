"""Read-only database/PDF fingerprints and provider usage for restore verification."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from sqlalchemy import inspect, text
from app.config import settings
from app.db import engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tables = {}
    with engine.connect() as connection:
        for name in sorted(inspect(engine).get_table_names(schema="public")):
            identifier = engine.dialect.identifier_preparer.quote(name)
            count, digest = connection.execute(
                text(
                    f"SELECT count(*), md5(coalesce(string_agg(h, '' ORDER BY h), '')) FROM (SELECT md5(t::text) AS h FROM {identifier} t) rows"
                )
            ).one()
            tables[name] = {"rows": count, "row_fingerprint_md5": digest}
        usage = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT model, kind, count(*) AS events, sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens, sum(retries) AS retries, sum(estimated_cost_usd) AS estimated_cost_usd FROM usage_events WHERE NOT cache_hit GROUP BY model, kind ORDER BY model, kind"
                )
            ).mappings()
        ]
        active = connection.execute(
            text("SELECT count(*) FROM jobs WHERE status IN ('queued','parsing','chunking','embedding','running')")
        ).scalar()
    files = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(settings.storage_dir.glob("*.pdf"))
        if p.is_file()
    }
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tables": tables,
        "pdf_sha256": files,
        "active_jobs": active,
        "provider_usage": usage,
        "estimated_cost_usd": sum(float(row["estimated_cost_usd"] or 0) for row in usage),
        "note": "Database row fingerprints compare trusted restore output; archive and PDFs use SHA256. Usage-based cost is an estimate, not an invoice.",
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "tables": len(tables),
                "pdfs": len(files),
                "active_jobs": active,
                "estimated_cost_usd": report["estimated_cost_usd"],
            }
        )
    )


if __name__ == "__main__":
    main()
