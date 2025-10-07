import re
from typing import List, Dict, Any, Iterable, Tuple, Optional

# Lightweight structural extraction using docx2python without forcing global dependency at import time.
# We only import docx2python inside the function so environments lacking the package can still use other features.

# Expanded patterns:
#  - HASH_ID_RE: hash-prefixed numeric IDs with optional dot part (#004.1, #057.0, #101.0)
#  - MULTI_DOT_ID_RE: traditional hierarchical multi-dot (4.1.1.2)
#  - SHALLOW_NUM_ID_RE: two-level numbers without hash (4.1, 12.5) to catch simple section requirements
#  - TABLE_ID_CELL_RE: allow optional leading hash and 1-5 dot groups
HASH_ID_RE = re.compile(r"^#(\d{1,4}(?:\.\d{1,3})?)\b")
MULTI_DOT_ID_RE = re.compile(r"^(\d+\.\d+\.\d+(?:\.\d+)*)\b")
SHALLOW_NUM_ID_RE = re.compile(r"^(\d+\.\d{1,3})\b")
TABLE_ID_CELL_RE = re.compile(r"^#?(\d+(?:\.\d+){0,5})\b")


def _flatten_docx_tables(docx_obj) -> Iterable[Tuple[str, List[List[str]]]]:
    # Yields (section, table_rows)
    for i, doc in enumerate(docx_obj.body):  # body is list of pages/sections depending on version
        if not isinstance(doc, list):
            continue
        for j, tbl in enumerate(doc):
            # docx2python returns nested list: pages -> tables -> rows -> cells
            if not isinstance(tbl, list):
                continue
            # Heuristic: treat any 2D list of strings as a table
            if tbl and isinstance(tbl[0], list):
                rows: List[List[str]] = []
                for row in tbl:
                    if isinstance(row, list):
                        cleaned = [" ".join(c.split()) for c in row]
                        rows.append(cleaned)
                if rows:
                    yield f"section_{i}_{j}", rows


def _extract_numbered_paragraphs(docx_obj) -> Iterable[Tuple[str, str]]:
    # docx2python.paragraphs returns flattened paragraphs with numbering embedded as text usually.
    try:
        paragraphs = docx_obj.text.splitlines()
    except Exception:
        return []
    for idx, line in enumerate(paragraphs):
        t = line.strip()
        if not t:
            continue
        # Priority: multi-dot deep > hash id > shallow num id
        if MULTI_DOT_ID_RE.match(t) or HASH_ID_RE.match(t) or SHALLOW_NUM_ID_RE.match(t):
            yield f"p{idx}", t


def extract_docx_structural_requirements(docx_path: str) -> List[Dict[str, Any]]:
    """Extract potential TPS requirements from a DOCX preserving numbering using docx2python.

    Produces list of dicts with keys similar to other pipeline sources:
      requirement_uid, subject, canonical_statement, source_type, source_anchor
    """
    try:
        from docx2python import docx2python  # type: ignore
    except ImportError:
        raise RuntimeError("docx2python not installed. Install via requirements.txt")

    doc = docx2python(docx_path, html=False)

    candidates: List[Dict[str, Any]] = []

    # Paragraph-based IDs (hierarchical, hash, shallow)
    for anchor, text in _extract_numbered_paragraphs(doc):
        rid = None
        raw_id_span_len = 0
        m_multi = MULTI_DOT_ID_RE.match(text)
        m_hash = HASH_ID_RE.match(text)
        m_shallow = SHALLOW_NUM_ID_RE.match(text)
        if m_multi:
            rid = m_multi.group(1)
            raw_id_span_len = len(m_multi.group(0))
        elif m_hash:
            rid = '#' + m_hash.group(1)
            raw_id_span_len = len(m_hash.group(0))
        elif m_shallow:
            rid = m_shallow.group(1)
            raw_id_span_len = len(m_shallow.group(0))
        if not rid:
            continue
        remainder = text[raw_id_span_len:].lstrip(" 	-:\u2013")
        # Skip pure heading style lines that are too short (just a heading word) here; let downstream filters handle minimal content
        subject = remainder.split('. ')[0].split(';')[0][:120] if remainder else rid
        candidates.append({
            "requirement_uid": f"TPS:{rid}",
            "subject": subject,
            "canonical_statement": remainder or text,
            "source_type": "docx2python_paragraph",
            "source_anchor": {"type": "paragraph_index", "value": anchor},
            "raw": text,
        })

    # Table-based IDs (look for ID pattern in first one or two cells)
    for anchor, rows in _flatten_docx_tables(doc):
        for r_index, row in enumerate(rows):
            if not row:
                continue
            first_cells = row[:2]
            for cell in first_cells:
                cm = TABLE_ID_CELL_RE.match(cell)
                if cm:
                    rid_raw = cm.group(1)
                    rid = rid_raw if rid_raw.startswith('#') else rid_raw
                    rest_parts = [c for c in row if c != cell]
                    remainder = " | ".join(p for p in rest_parts if p)
                    subject = remainder.split(" | ")[0][:120] if remainder else rid
                    candidates.append({
                        "requirement_uid": f"TPS:{rid}",
                        "subject": subject,
                        "canonical_statement": remainder or cell,
                        "source_type": "docx2python_table_row",
                        "source_anchor": {"type": "table_row", "table": anchor, "row_index": r_index},
                        "raw": row,
                    })
                    break

    # De-dupe: keep shortest canonical_statement per requirement_uid preferring table rows over paragraphs
    best: Dict[str, Dict[str, Any]] = {}
    preference_order = {"docx2python_table_row": 0, "docx2python_paragraph": 1}
    for c in candidates:
        uid = c["requirement_uid"]
        prev = best.get(uid)
        if prev is None:
            best[uid] = c
        else:
            # prefer table; or shorter text length
            if preference_order.get(c["source_type"], 99) < preference_order.get(prev["source_type"], 99):
                best[uid] = c
            elif len(c.get("canonical_statement", "")) < len(prev.get("canonical_statement", "")):
                best[uid] = c

    # Sort for determinism
    out = list(best.values())
    out.sort(key=lambda d: d["requirement_uid"])
    return out

__all__ = ["extract_docx_structural_requirements"]
