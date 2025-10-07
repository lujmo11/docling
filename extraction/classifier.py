from __future__ import annotations
from typing import Dict, Any, Optional
import re
from .strategy_base import DocumentProfile

RS_KEYWORDS = ["REQUIREMENT SPECIFICATION", "REQUIREMENTS SPECIFICATION"]
TPS_KEYWORDS = ["TECHNICAL PURCHASE SPECIFICATION", "TPS"]


def classify_document(doc_json: Dict[str, Any], tables_data: Dict[str, Any], filename: str | None = None, marker_index: Optional[object] = None) -> DocumentProfile:
    blocks = doc_json.get("blocks", []) or []
    text_samples = []
    for b in blocks[:80]:
        if isinstance(b, dict):
            txt = b.get("text") or ""
            if txt:
                text_samples.append(txt)
    joined_upper = "\n".join(text_samples).upper()

    rs_hits = sum(1 for kw in RS_KEYWORDS if kw in joined_upper)
    tps_hits = sum(1 for kw in TPS_KEYWORDS if kw in joined_upper)

    # Feature: requirement markers density
    # Legacy inline marker detection (paragraph only)
    marker_pattern = re.compile(r'#\s*\d+')
    marker_count = len(marker_pattern.findall(joined_upper))
    rs_marker_index_count = None
    tps_marker_index_count = None
    if marker_index is not None:
        try:
            rs_marker_index_count = marker_index.rs_count()
            tps_marker_index_count = marker_index.tps_count()
        except Exception:
            rs_marker_index_count = None
            tps_marker_index_count = None

    table_count = len(tables_data or {})

    # Simple heuristic scoring
    rs_score = rs_hits + (marker_count / 40.0)
    tps_score = tps_hits + (table_count / 50.0)

    # If marker index provided, strengthen evidence using discovered markers (including table cells)
    if rs_marker_index_count is not None:
        rs_score += (rs_marker_index_count / 60.0)  # calibrated: 60 RS markers -> +1
    if tps_marker_index_count is not None:
        tps_score += (tps_marker_index_count / 120.0)  # TPS markers (hierarchical ids) usually fewer

    # Filename hints (strong prior)
    if filename:
        fn_up = filename.upper()
        if ' REQUIREMENT ' in f' {fn_up} ' or fn_up.startswith('RS') or 'REQUIREMENT SPECIFICATION' in fn_up:
            rs_score += 2.5
        if fn_up.startswith('TPS') or 'TECHNICAL PURCHASE SPECIFICATION' in fn_up:
            tps_score += 2.0

    # Absolute override: many inline # markers almost always means RS textual spec
    total_discovered = (rs_marker_index_count or 0) + (tps_marker_index_count or 0)
    if (rs_marker_index_count or 0) >= 30 and (rs_marker_index_count or 0) >= 2 * (tps_marker_index_count or 0 + 1):
        rs_score += 4  # strong RS override based on marker dominance
    elif marker_count >= 20 and rs_hits >= 0:
        rs_score += 5

    if rs_score == 0 and tps_score == 0:
        doc_type = "UNKNOWN"
        confidence = 0.0
    else:
        if rs_score >= tps_score:
            doc_type = "RS"
            confidence = rs_score / (rs_score + tps_score + 1e-6)
        else:
            doc_type = "TPS"
            confidence = tps_score / (rs_score + tps_score + 1e-6)

    return DocumentProfile(
        doc_type=doc_type,
        confidence=round(confidence, 3),
        features={
            "rs_score": round(rs_score,3),
            "tps_score": round(tps_score,3),
            "marker_count": marker_count,
            "rs_marker_index_count": rs_marker_index_count,
            "tps_marker_index_count": tps_marker_index_count,
            "table_count": table_count,
            "filename_hint": bool(filename),
        }
    )
