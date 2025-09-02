import json
import pandas as pd
from pathlib import Path
from typing import List
import dataclasses

from models import Requirement

def write_requirements_jsonl(requirements: List[Requirement], file_path: Path):
    """Writes a list of Requirement objects to a JSONL file."""
    with file_path.open("w", encoding="utf-8") as f:
        for req in requirements:
            f.write(json.dumps(dataclasses.asdict(req), ensure_ascii=False) + "\n")

def write_requirements_csv(requirements: List[Requirement], file_path: Path):
    """Writes a list of Requirement objects to a CSV file.

    Complex fields (lists/dicts) are serialized as JSON strings to keep the CSV flat.
    """
    # Define a stable set of CSV columns
    columns = [
        "requirement_uid",
        "section_path",
        "normative_strength",
        "canonical_statement",
        "requirement_raw",
        "acceptance_criteria",
        "verification_method",
        "references",
        "subject",
        "category",
        "tags",
        "evidence_query",
        "doc_meta",
        "source_anchor",
        "conflicts",
        "dependencies",
        "page_range",
        "parent_id",
        "confidence",
    ]

    if not requirements:
        pd.DataFrame(columns=columns).to_csv(file_path, index=False)
        return

    def to_json(value):
        return json.dumps(value, ensure_ascii=False) if value is not None else "null"

    records = []
    for req in requirements:
        records.append({
            "requirement_uid": req.requirement_uid,
            "section_path": " > ".join(req.section_path or []),
            "normative_strength": req.normative_strength,
            "canonical_statement": req.canonical_statement,
            "requirement_raw": req.requirement_raw,
            "acceptance_criteria": to_json([dataclasses.asdict(ac) for ac in (req.acceptance_criteria or [])]),
            "verification_method": req.verification_method,
            "references": to_json(req.references or []),
            "subject": req.subject,
            "category": req.category,
            "tags": to_json(req.tags or []),
            "evidence_query": req.evidence_query,
            "doc_meta": to_json(req.doc_meta),
            "source_anchor": to_json(req.source_anchor),
            "conflicts": to_json(req.conflicts or []),
            "dependencies": to_json(req.dependencies or []),
            "page_range": to_json(req.page_range),
            "parent_id": req.parent_id,
            "confidence": req.confidence,
        })

    pd.DataFrame(records, columns=columns).to_csv(file_path, index=False)
