#!/usr/bin/env python3
"""Batch-normalize existing *_output folders to the canonical naming convention.

This script reuses the same heuristics as simple.py to extract front-page info and
rename folders and key files with a prefix like `TPS - 0101-4242 V00 - Description`.

Run from the repo root: python normalize_outputs.py
"""
from pathlib import Path
import json, re, shutil, string

ROOT = Path(__file__).parent


def sanitize_for_filename(s: str) -> str:
    if not s:
        return ""
    invalid = '<>:"/\\|?*\n\r\t'
    table = str.maketrans({c: " " for c in invalid})
    out = s.translate(table)
    out = "".join(ch for ch in out if ch in string.printable)
    out = " ".join(out.split())
    return out.strip()


def find_doc_frontpage_info(out_path: Path) -> dict:
    info = {"type": None, "id": None, "desc": None}
    doc_json_path = out_path / "document.json"
    tables_json_path = out_path / "tables_data.json"
    md_path = out_path / "document.md"
    text_lines = []
    try:
        if doc_json_path.exists():
            raw = json.loads(doc_json_path.read_text(encoding="utf-8"))
            blocks = None
            if isinstance(raw, dict):
                if "blocks" in raw:
                    blocks = raw.get("blocks")
                elif "document" in raw and isinstance(raw["document"], dict) and "blocks" in raw["document"]:
                    blocks = raw["document"]["blocks"]
            if blocks:
                for b in blocks[:60]:
                    t = ""
                    if isinstance(b, dict):
                        if b.get("type") == "heading":
                            t = b.get("text", "")
                        elif b.get("type") in ("paragraph", "list"):
                            t = b.get("text", "")
                    if t:
                        text_lines.append(t)
    except Exception:
        pass
    # Try to get frontpage Document/Description from tables.json first
    try:
        if tables_json_path.exists():
            tbl_raw = json.loads(tables_json_path.read_text(encoding="utf-8"))
            for t in tbl_raw.values():
                csv = t.get("csv_data", "")
                if not csv:
                    continue
                if "Document:" in csv or "Description:" in csv:
                    # Handle multiline cells with Document:\nA012-5599 VER 05 format
                    doc_match = re.search(r'"Document:\s*\n([^"]+)"', csv)
                    if doc_match:
                        val = doc_match.group(1).strip()
                        if val and not val.lower() in ('confidential', 'tbd', 'tba'):
                            info["id"] = val
                    desc_match = re.search(r'"Description:\s*\n([^"]+)"', csv)
                    if desc_match:
                        val = desc_match.group(1).strip()
                        if val and not val.lower() in ('confidential', 'tbd', 'tba'):
                            info["desc"] = val
                    # Also try single-line format
                    for line in csv.splitlines():
                        if line.strip().startswith("Document:"):
                            val = line.split("Document:", 1)[1].strip().strip('"')
                            if val and not info.get("id") and not val.lower() in ('confidential', 'tbd', 'tba'):
                                info["id"] = val
                        if line.strip().startswith("Description:"):
                            val = line.split("Description:", 1)[1].strip().strip('"')
                            if val and not info.get("desc") and not val.lower() in ('confidential', 'tbd', 'tba'):
                                info["desc"] = val
                    if info.get("id") or info.get("desc"):
                        break
    except Exception:
        pass
    try:
        if not text_lines and md_path.exists():
            lines = md_path.read_text(encoding="utf-8").splitlines()
            for l in lines[:80]:
                if l.strip():
                    text_lines.append(l.strip())
    except Exception:
        pass

    joined = "\n".join(text_lines).upper()
    if "TECHNICAL PURCHASE SPECIFICATION" in joined or any(l.startswith("TPS") for l in joined.splitlines()[:6]):
        info["type"] = "TPS"
    elif "REQUIREMENT SPECIFICATION" in joined or "REQUIREMENTS SPECIFICATION" in joined:
        info["type"] = "RS"
    else:
        nm = str(out_path.name).upper()
        if nm.startswith("TPS"):
            info["type"] = "TPS"
        elif nm.startswith("RS"):
            info["type"] = "RS"

    m = re.search(r'\b(\d{4}[-\s]?\d{4})(?:\s*[Vv]\s*\d{1,3})?\b', joined)
    if m:
        info["id"] = m.group(0).replace(" ", "")

    desc = None
    for line in text_lines:
        up = line.strip()
        if not up:
            continue
        if info.get("id") and info["id"] in up.replace(" ", ""):
            continue
        up_words = up.split()
        if len(up_words) >= 3 and len(up) > 10:
            if not re.search(r'\bIEC\b|\bISO\b|\bDIN\b|\bTPS\b|\bRS\b|\bVESTAS\b', up, re.I):
                desc = up
                break
    if not desc and text_lines:
        desc = text_lines[1] if len(text_lines) > 1 else text_lines[0]
    if desc:
        info["desc"] = " ".join(desc.split())
    return info


def assemble_pretty_name(info: dict, fallback: str) -> str:
    typ = (info.get("type") or "").upper()
    docid = info.get("id") or ""
    desc = info.get("desc") or ""
    # normalize docid similar to simple.py
    m = re.search(r'(\d{4})[-\s]?(\d{4})(?:\D*([Vv]\s*\d{1,3}))?', docid)
    if m:
        part1 = m.group(1)
        part2 = m.group(2)
        v = m.group(3) or ''
        v = v.replace(' ', '') if v else ''
        if v:
            docid = f"{part1}-{part2} {v.upper()}"
        else:
            docid = f"{part1}-{part2}"
    desc = " ".join(desc.split())[:120]
    desc = re.sub(r'[<>:\\"\|\?\*\n\r\t]', ' ', desc).strip(" -_.,")
    parts = []
    if typ:
        parts.append(typ)
    if docid:
        parts.append(docid)
    if desc:
        parts.append(desc)
    if not parts:
        return sanitize_for_filename(fallback)
    pretty = " - ".join(parts)
    return sanitize_for_filename(pretty)


if __name__ == '__main__':
    for d in ROOT.iterdir():
        if not d.is_dir() or not d.name.endswith('_output'):
            continue
        try:
            info = find_doc_frontpage_info(d)
            base = d.name[:-7]
            pretty = assemble_pretty_name(info, base)
            if pretty and pretty != base:
                parent = d.parent
                candidate = parent / f"{pretty}_output"
                suffix = 1
                while candidate.exists():
                    candidate = parent / f"{pretty}_output_run{suffix}"
                    suffix += 1
                shutil.move(str(d), str(candidate))
                print(f"Renamed {d.name} -> {candidate.name}")
                # prefix common files inside
                for fname in [
                    "document.md",
                    "document.json",
                    "document.doctags.txt",
                    "tables_info.csv",
                    "tables_data.json",
                    "requirements.jsonl",
                    "requirements.csv",
                ]:
                    src = candidate / fname
                    if not src.exists():
                        continue
                    new_name = f"{pretty} - {fname}"
                    dst = candidate / new_name
                    if dst.exists():
                        continue
                    src.rename(dst)
                    print(f"  Prefixed file: {fname} -> {new_name}")
        except Exception as e:
            print(f"Failed to normalize {d.name}: {e}")
