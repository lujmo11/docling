#!/usr/bin/env python3
import argparse
import json
import csv
import re
from pathlib import Path
from collections import Counter, defaultdict
from typing import List, Dict, Any, Optional, Tuple

# Reuse our conversion + extraction pipeline
import simple as pipeline


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not path.exists():
        return items
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                # Skip malformed lines
                continue
    return items


def summarize_requirements(reqs: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(reqs)
    by_category = Counter([r.get("category") or "unknown" for r in reqs])
    with_ac = sum(1 for r in reqs if r.get("acceptance_criteria"))
    strength = Counter([r.get("normative_strength") or "unknown" for r in reqs])
    ref_counter = Counter()
    for r in reqs:
        for ref in (r.get("references") or []):
            ref_counter[ref] += 1
    return {
        "total": total,
        "categories": dict(by_category),
        "with_acceptance_criteria": with_ac,
        "normative_strength": dict(strength),
        "top_references": ref_counter.most_common(8),
    }


def _get_text(item: Dict[str, Any]) -> str:
    return (
        item.get("canonical")
        or item.get("canonical_statement")
        or item.get("raw")
        or item.get("text")
        or ""
    )


def _get_uid(item: Dict[str, Any]) -> str:
    return item.get("uid") or item.get("requirement_uid") or item.get("id") or ""


def tokenize(text: str) -> List[str]:
    text = (text or "").lower()
    tokens = re.findall(r"\b[a-z0-9]+\b", text)
    return tokens


def extract_numbers(text: str) -> List[str]:
    return re.findall(r"\b\d+(?:[\.,]\d+)?\b", text or "")


def jaccard(a: List[str], b: List[str]) -> float:
    sa = set(a)
    sb = set(b)
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def match_requirements_to_design(reqs: List[Dict[str, Any]], design_reqs: List[Dict[str, Any]], out_csv_path: Path) -> Path:
    rows = []
    for r in reqs:
        r_text = _get_text(r)
        r_tokens = tokenize(r_text)
        r_nums = set(extract_numbers(r_text))
        r_refs = set(r.get("references") or [])

        best = None
        best_score = -1.0
        best_match = None
        for d in design_reqs:
            d_text = _get_text(d)
            d_tokens = tokenize(d_text)
            d_nums = set(extract_numbers(d_text))
            d_refs = set(d.get("references") or [])

            token_score = jaccard(r_tokens, d_tokens)
            num_score = 1.0 if (r_nums and (r_nums & d_nums)) else 0.0
            ref_score = 1.0 if (r_refs and (r_refs & d_refs)) else 0.0

            score = (0.6 * token_score) + (0.25 * num_score) + (0.15 * ref_score)

            if score > best_score:
                best_score = score
                best = d
                best_match = {
                    "score": score,
                    "token_score": token_score,
                    "num_score": num_score,
                    "ref_score": ref_score,
                    "matched_tokens": list(set(r_tokens) & set(d_tokens)),
                    "matched_numbers": list(r_nums & d_nums),
                    "matched_refs": list(r_refs & d_refs),
                }

        rows.append({
            "req_uid": _get_uid(r),
            "req_text": r_text,
            "best_design_uid": _get_uid(best) if best else "",
            "best_design_text": _get_text(best) if best else "",
            "match_score": round(best_match["score"], 4) if best_match else 0.0,
            "token_score": round(best_match["token_score"], 4) if best_match else 0.0,
            "num_score": best_match["num_score"] if best_match else 0.0,
            "ref_score": best_match["ref_score"] if best_match else 0.0,
            "matched_tokens": ";".join(sorted(best_match["matched_tokens"])) if best_match else "",
            "matched_numbers": ";".join(sorted(best_match["matched_numbers"])) if best_match else "",
            "matched_refs": ";".join(sorted(best_match["matched_refs"])) if best_match else "",
        })

    fieldnames = [
        "req_uid",
        "req_text",
        "best_design_uid",
        "best_design_text",
        "match_score",
        "token_score",
        "num_score",
        "ref_score",
        "matched_tokens",
        "matched_numbers",
        "matched_refs",
    ]
    out_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with out_csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    return out_csv_path


def convert_if_needed(doc_path: Path, out_dir: Optional[Path], reconvert: bool) -> Path:
    if out_dir is None:
        out_dir = Path(f"{doc_path.stem}_output")
    # Reuse if exists and not forced to reconvert
    if out_dir.exists() and not reconvert:
        return out_dir
    pipeline.convert_docx(str(doc_path), str(out_dir), extract_reqs=True)
    return out_dir


def pick_samples(reqs: List[Dict[str, Any]], n: int = 3) -> List[Dict[str, Any]]:
    # Choose first n with references if possible, else any
    with_refs = [r for r in reqs if r.get("references")]
    if len(with_refs) >= n:
        return with_refs[:n]
    return reqs[:n]


def print_summary(title: str, summary: Dict[str, Any]) -> None:
    print(f"\n=== {title} Summary ===")
    print(f"Total requirements: {summary['total']}")
    print(f"With acceptance_criteria: {summary['with_acceptance_criteria']}")
    print("Categories:")
    for k, v in sorted(summary["categories"].items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  - {k}: {v}")
    print("Normative strength:")
    for k, v in sorted(summary["normative_strength"].items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  - {k}: {v}")
    print("Top references:")
    if summary["top_references"]:
        for ref, cnt in summary["top_references"]:
            print(f"  - {ref}: {cnt}")
    else:
        print("  - (none)")


def intersect_references(rs_reqs: List[Dict[str, Any]], tps_reqs: List[Dict[str, Any]]) -> List[str]:
    rs_refs = set(ref for r in rs_reqs for ref in (r.get("references") or []))
    tps_refs = set(ref for r in tps_reqs for ref in (r.get("references") or []))
    return sorted(rs_refs & tps_refs)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Run real-world check for RS and design docs.")
    ap.add_argument("--rs", required=True, help="Path to requirements (RS) document")
    ap.add_argument("--design", required=True, help="Path to design/spec (TPS) document")
    ap.add_argument("--rs-out", default=None, help="Optional output dir for RS conversion")
    ap.add_argument("--design-out", default=None, help="Optional output dir for design conversion")
    ap.add_argument("--reconvert", action="store_true", help="Force reconversion even if output dir exists")
    args = ap.parse_args(argv)

    rs_path = Path(args.rs)
    design_path = Path(args.design)
    rs_out = Path(args.rs_out) if args.rs_out else None
    design_out = Path(args.design_out) if args.design_out else None

    if not rs_path.exists():
        print(f"RS file not found: {rs_path}")
        return 2
    if not design_path.exists():
        print(f"Design file not found: {design_path}")
        return 2

    print("Converting RS document ...")
    rs_out_dir = convert_if_needed(rs_path, rs_out, args.reconvert)
    print(f"RS output: {rs_out_dir}")

    print("Converting design document ...")
    design_out_dir = convert_if_needed(design_path, design_out, args.reconvert)
    print(f"Design output: {design_out_dir}")

    rs_reqs = load_jsonl(rs_out_dir / "requirements.jsonl")
    tps_reqs = load_jsonl(design_out_dir / "requirements.jsonl")

    print_summary("RS", summarize_requirements(rs_reqs))
    print_summary("Design/TPS", summarize_requirements(tps_reqs))

    both_refs = intersect_references(rs_reqs, tps_reqs)
    print("\nReferences present in both RS and Design:")
    if both_refs:
        for r in both_refs[:12]:
            print(f"  - {r}")
    else:
        print("  - (none)")

    # Show a few samples
    print("\nRS samples:")
    for r in pick_samples(rs_reqs, 3):
        print(f"- {r.get('requirement_uid')}: {r.get('canonical_statement')}  [cat={r.get('category')}, refs={r.get('references') or []}]")

    print("\nDesign samples:")
    for r in pick_samples(tps_reqs, 3):
        print(f"- {r.get('requirement_uid')}: {r.get('canonical_statement')}  [cat={r.get('category')}, refs={r.get('references') or []}]")

    # Match RS requirements to design items and write coverage CSV
    try:
        coverage_path = rs_out_dir / "requirements_coverage.csv"
        match_requirements_to_design(rs_reqs, tps_reqs, coverage_path)
        print(f"\nWrote requirements coverage CSV: {coverage_path}")
    except Exception as e:
        print(f"Failed to write coverage CSV: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
