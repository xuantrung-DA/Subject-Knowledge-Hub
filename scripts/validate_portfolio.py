"""Check source hashes and every synthetic runbook page against PDF extraction."""

import argparse
import hashlib
import json
from pathlib import Path
import re
from pypdf import PdfReader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "fixtures" / "portfolio"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for name, digest in manifest["hashes"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name

    def normalize(value):
        return re.sub(r"\s+", " ", value).strip()

    checks = []
    for document in json.loads((root / "corpus.json").read_text(encoding="utf-8")):
        reader = PdfReader(root / (document["document_key"] + ".pdf"))
        assert len(reader.pages) == 5
        for page in document["pages"]:
            checks.append(
                {
                    "document": document["document_key"],
                    "page": page["number"],
                    "valid": normalize(page["text"]) in normalize(reader.pages[page["number"] - 1].extract_text()),
                }
            )
    report = {
        "status": "PASS" if all(c["valid"] for c in checks) else "FAIL",
        "pages_checked": len(checks),
        "checks": checks,
        "limitations": "Checks PDF text provenance; does not establish independent human validation of labels.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "pages_checked": len(checks)}))
    assert report["status"] == "PASS"


if __name__ == "__main__":
    main()
