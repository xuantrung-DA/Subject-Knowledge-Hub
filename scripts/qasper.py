#!/usr/bin/env python3
"""Download/adapt a fixed 100-question, seed-ranked QASPER v0.3 test subset.

Public paper paragraphs are corpus; test questions, answers and annotation
labels are written only to evaluation JSONL. No synthetic PDF page numbers.
"""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request

SOURCE = "https://qasper-dataset.s3.us-west-2.amazonaws.com/qasper-test-and-evaluator-v0.3.tgz"
SEED = 20260909
COUNT = 100


def normalized(text):
    return " ".join(text.split())


def adapt(data, source_sha256, output, expected_manifest=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    candidates = []
    excluded = {"no_textual_evidence": 0, "annotation_disagreement": 0, "unmapped_evidence": 0}
    paragraph_maps, all_papers = {}, {}
    for paper_id, paper in sorted(data.items()):
        paragraphs = []
        if paper.get("abstract"):
            paragraphs.append({"id": f"{paper_id}:abstract", "text": paper["abstract"], "section": "Abstract"})
        for section_number, section in enumerate(paper.get("full_text", [])):
            for paragraph_number, text in enumerate(section.get("paragraphs", [])):
                if text.strip():
                    paragraphs.append(
                        {
                            "id": f"{paper_id}:s{section_number}:p{paragraph_number}",
                            "text": text,
                            "section": section.get("section_name", ""),
                        }
                    )
        paragraph_maps[paper_id] = {normalized(p["text"]): p["id"] for p in paragraphs}
        all_papers[paper_id] = {
            "document_key": f"qasper:{paper_id}",
            "title": paper.get("title", paper_id),
            "source_type": "paragraph",
            "paper_id": paper_id,
            "paragraphs": paragraphs,
        }
        for q in paper.get("qas", []):
            annotations = [a["answer"] for a in q.get("answers", [])]
            if not annotations:
                continue
            labels = {bool(a.get("unanswerable")) for a in annotations}
            if len(labels) > 1:
                excluded["annotation_disagreement"] += 1
                continue
            answerable = not next(iter(labels))
            evidence_ids, references = set(), []
            unmapped = False
            for annotation in annotations:
                if annotation.get("unanswerable"):
                    reference = "Insufficient evidence in this paper."
                elif annotation.get("free_form_answer"):
                    reference = annotation["free_form_answer"]
                elif annotation.get("extractive_spans"):
                    reference = ", ".join(annotation["extractive_spans"])
                elif annotation.get("yes_no") is not None:
                    reference = "Yes" if annotation["yes_no"] else "No"
                else:
                    reference = ""
                if reference and reference not in references:
                    references.append(reference)
                for evidence in annotation.get("evidence", []):
                    if evidence.startswith("FLOAT SELECTED"):
                        unmapped = True
                        continue
                    pid = paragraph_maps[paper_id].get(normalized(evidence))
                    if pid:
                        evidence_ids.add(pid)
                    else:
                        unmapped = True
            if answerable and unmapped:
                excluded["unmapped_evidence"] += 1
                continue
            if answerable and (not evidence_ids or not references):
                excluded["no_textual_evidence"] += 1
                continue
            row = {
                "id": q["question_id"],
                "question": q["question"],
                "reference_answer": references[0] if references else "Insufficient evidence in this paper.",
                "reference_answers": references[1:],
                "answerable": answerable,
                "evidence": [{"document_key": f"qasper:{paper_id}", "paragraph_ids": sorted(evidence_ids)}]
                if evidence_ids
                else [],
                "tags": ["en", "qasper", "test", "paragraph_evidence"],
                "metadata": {
                    "paper_id": paper_id,
                    "target_document_key": f"qasper:{paper_id}",
                    "source_split": "test",
                    "annotation_policy": "Only unanimous answerability, all evidence textual and exactly mapped; reference score takes maximum over annotations.",
                },
            }
            candidates.append((paper_id, row))
    # A stable SHA256 rank is independent of dictionary order and Python RNG version.
    candidates.sort(key=lambda p: hashlib.sha256(f"{SEED}:{p[1]['id']}".encode()).hexdigest())
    if len(candidates) < COUNT:
        raise ValueError(f"Only {len(candidates)} eligible questions; require exactly {COUNT}")
    selected = candidates[:COUNT]
    ids = [row["id"] for _, row in selected]
    if expected_manifest:
        if expected_manifest.get("source_sha256") != source_sha256 or expected_manifest.get("question_ids") != ids:
            raise ValueError(
                "Source or fixed question IDs differ from pinned manifest; refusing to silently change test set"
            )
    papers = sorted({pid for pid, _ in selected})
    corpus = [all_papers[pid] for pid in papers]
    (output / "corpus.jsonl").write_text(
        "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in corpus), encoding="utf-8"
    )
    (output / "test100.jsonl").write_text(
        "".join(json.dumps(q, ensure_ascii=False) + "\n" for _, q in selected), encoding="utf-8"
    )
    manifest = {
        "dataset": "QASPER",
        "upstream_version": "0.3",
        "split": "test",
        "seed": SEED,
        "selection": "Lowest SHA256(seed:official_question_id) among eligible examples, exact 100, no replacement",
        "source_url": SOURCE,
        "dataset_card": "https://huggingface.co/datasets/allenai/qasper",
        "source_sha256": source_sha256,
        "license": "CC-BY-4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "Dasigi, Lo, Beltagy, Cohan, Smith, and Gardner. A Dataset of Information-Seeking Questions and Answers Anchored in Research Papers. NAACL 2021. https://aclanthology.org/2021.naacl-main.365/",
        "question_count": COUNT,
        "question_ids": ids,
        "paper_ids": papers,
        "eligibility_exclusions": excluded,
        "corpus_sha256": hashlib.sha256((output / "corpus.jsonl").read_bytes()).hexdigest(),
        "test_sha256": hashlib.sha256((output / "test100.jsonl").read_bytes()).hexdigest(),
        "evidence_unit": "original dataset paragraph ID; physical PDF pages are absent",
        "limitations": [
            "Subset excludes non-textual/unmapped evidence and answerability disagreement; results are not the full official benchmark.",
            "Reference answers and question labels are excluded from the indexed corpus.",
            "Uses full text, not PDF parser; does not evaluate Vietnamese.",
            "Do not tune on this fixed test subset. Use upstream train/dev separately.",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"output": str(output), "question_count": COUNT, "papers": len(papers), "source_sha256": source_sha256}
        )
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "artifacts" / "qasper")
    parser.add_argument(
        "--source", type=Path, help="Existing original v0.3 TGZ file; use when downloads are unavailable"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Verify an already pinned manifest; otherwise existing output manifest is verified",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.source or args.output / "qasper-test-and-evaluator-v0.3.tgz"
    if not archive.exists():
        temporary = archive.with_suffix(".download")
        try:
            with urllib.request.urlopen(SOURCE, timeout=90) as response, temporary.open("wb") as target:
                downloaded = 0
                while chunk := response.read(1024 * 1024):
                    downloaded += len(chunk)
                    if downloaded > 300 * 1024 * 1024:
                        raise ValueError("Download exceeded 300 MB limit")
                    target.write(chunk)
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    # Read only the expected member; never extract paths from an untrusted tar.
    with tarfile.open(archive, "r:gz") as tar:
        member = next(
            (m for m in tar.getmembers() if Path(m.name).name == "qasper-test-v0.3.json" and m.isfile()), None
        )
        if not member or member.size > 300 * 1024 * 1024:
            raise ValueError("Archive lacks the expected bounded v0.3 test JSON")
        with tar.extractfile(member) as stream:
            data = json.load(stream)
    expected_path = args.manifest or args.output / "manifest.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8")) if expected_path.exists() else None
    adapt(data, digest, args.output, expected)


if __name__ == "__main__":
    main()
