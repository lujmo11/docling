from typing import List, Dict, Any, Optional, Tuple
import re
from models import Requirement, AcceptanceCriterion
from marker_index import MarkerIndex, Marker
import csv, io
from utils import find_normative_strength, extract_numbers_with_units, canonicalize, infer_subject, collect_references, guess_category, make_evidence_query

def build_requirements_from_markers(marker_index: MarkerIndex, doc_json: Dict[str, Any], doc_meta: Dict[str, Any], tables_data: Optional[Dict[str, Any]] = None) -> List[Requirement]:
    """Segment containers containing markers into Requirement objects (RS focus).

    Current scope:
      - RS markers in paragraphs: split text between markers
      - RS markers in table cells: create stub requirements (will be enriched later)
    TPS handling will remain with existing table extractor for now.
    """
    requirements: List[Requirement] = []
    blocks = (doc_json or {}).get('blocks', [])

    # Group markers by container
    by_cont = marker_index.by_container()

    for (ctype, cindex, table_id), markers in by_cont.items():
        if ctype == 'paragraph':
            if cindex >= len(blocks):
                continue
            block = blocks[cindex]
            text = block.get('text', '') or ''
            # Only process RS markers here
            rs_markers = [m for m in markers if m.kind == 'RS']
            if not rs_markers:
                continue
            # Sort by start offset
            rs_markers.sort(key=lambda m: m.start or 0)
            for i, m in enumerate(rs_markers):
                start_text = m.end or 0
                end_text = rs_markers[i+1].start if i + 1 < len(rs_markers) else len(text)
                raw = text[start_text:end_text].strip()
                if not raw:
                    # Create stub (will be filled later maybe)
                    requirements.append(_stub_req(m, doc_meta, source_type='paragraph'))
                    continue
                normative = find_normative_strength(raw)
                ac_list = extract_numbers_with_units(raw)
                refs = collect_references(raw)
                subject = infer_subject([], raw, 'generator')
                category = guess_category([], raw)
                canonical = canonicalize(subject, raw)
                ev_query = make_evidence_query(subject, canonical, refs)
                requirements.append(Requirement(
                    requirement_uid=f"RS:{m.uid}",
                    doc_meta=doc_meta,
                    section_path=[],
                    source_anchor={"type": "paragraph", "index": cindex, "offset": m.start},
                    normative_strength=normative,
                    canonical_statement=canonical,
                    requirement_raw=raw,
                    acceptance_criteria=ac_list,
                    verification_method=None,
                    references=refs,
                    subject=subject,
                    category=category,
                    tags=[],
                    evidence_query=ev_query,
                    source_type='paragraph',
                    source_location={"block_index": cindex},
                    is_stub=False,
                    raw_section_header=None,
                ))
        elif ctype == 'table_cell':
            # Enrich table-cell RS markers by parsing cell text
            if not tables_data:
                for m in markers:
                    if m.kind == 'RS':
                        requirements.append(_stub_req(m, doc_meta, source_type='table_cell'))
                continue
            table_id = markers[0].table_id
            tinfo = (tables_data or {}).get(table_id) or {}
            csv_data = tinfo.get('csv_data') or ''
            if not csv_data:
                for m in markers:
                    if m.kind == 'RS':
                        requirements.append(_stub_req(m, doc_meta, source_type='table_cell'))
                continue
            # Build row list using csv module (supports multi-line quoted cells)
            try:
                reader = csv.reader(io.StringIO(csv_data))
                rows = list(reader)
            except Exception:
                rows = [r.split(',') for r in csv_data.splitlines()]  # very naive fallback
            header_row = rows[0] if rows else []
            for m in markers:
                if m.kind != 'RS':
                    continue
                row_idx, col_idx = (m.cell_coords or (None, None))
                if row_idx is None or row_idx >= len(rows):
                    requirements.append(_stub_req(m, doc_meta, source_type='table_cell'))
                    continue
                row = rows[row_idx]
                cell_text = ''
                if col_idx is not None and col_idx < len(row):
                    cell_text = (row[col_idx] or '').strip()
                # If marker is in second column typical format: first column holds requirement text
                if (not cell_text or cell_text.startswith('#')) and len(row) > 0:
                    # try first column
                    cell_text = (row[0] or '').strip()
                if not cell_text:
                    requirements.append(_stub_req(m, doc_meta, source_type='table_cell'))
                    continue
                # Extract metadata lines
                lines = [l.rstrip() for l in cell_text.splitlines()]
                # Identify metadata start indices
                meta_prefixes = ('Motivation:', 'Source:', 'Verification method:', 'Conflicts:')
                meta_index = len(lines)
                for idx_l, ln in enumerate(lines):
                    if any(ln.startswith(p) for p in meta_prefixes):
                        meta_index = idx_l
                        break
                content_lines = lines[:meta_index]
                requirement_raw = '\n'.join(l for l in content_lines if l).strip() or lines[0].strip()
                # Extract verification method line
                verification_method = None
                for ln in lines:
                    if ln.lower().startswith('verification method:'):
                        verification_method = ln.split(':',1)[1].strip().rstrip('. ')
                        break
                # Derive normative strength from full cell text content (not metadata lines alone)
                normative = find_normative_strength(requirement_raw)
                ac_list = extract_numbers_with_units(requirement_raw)
                refs = collect_references(cell_text)
                subject = infer_subject([], requirement_raw, 'generator')
                category = guess_category([], requirement_raw)
                canonical = canonicalize(subject, requirement_raw)
                ev_query = make_evidence_query(subject, canonical, refs)
                # Section header context (first header cell of table row 0)
                raw_section_header = None
                if header_row:
                    hdr0 = (header_row[0] or '').strip()
                    if hdr0 and hdr0.lower() != requirement_raw.lower():
                        raw_section_header = hdr0
                requirements.append(Requirement(
                    requirement_uid=f"RS:{m.uid}",
                    doc_meta=doc_meta,
                    section_path=[raw_section_header] if raw_section_header else [],
                    source_anchor={"type": "table_cell", "table": table_id, "cell": m.cell_coords},
                    normative_strength=normative,
                    canonical_statement=canonical,
                    requirement_raw=requirement_raw,
                    acceptance_criteria=ac_list,
                    verification_method=verification_method,
                    references=refs,
                    subject=subject,
                    category=category,
                    tags=[],
                    evidence_query=ev_query,
                    source_type='table_cell',
                    source_location={"table_id": table_id, "cell": m.cell_coords},
                    is_stub=False,
                    raw_section_header=raw_section_header,
                ))
        else:
            continue

    return requirements


def _stub_req(marker: Marker, doc_meta: Dict[str, Any], source_type: str) -> Requirement:
    return Requirement(
        requirement_uid=f"RS:{marker.uid}",
        doc_meta=doc_meta,
        section_path=[],
        source_anchor={"type": source_type, "table": marker.table_id, "coord": marker.cell_coords, "offset": marker.start},
        normative_strength=None,
        canonical_statement=f"Requirement {marker.uid}",
        requirement_raw=marker.raw,
        acceptance_criteria=[],
        verification_method=None,
        references=[],
        subject='generator',
        category=None,
        tags=[],
        evidence_query=f"requirement {marker.uid}",
        source_type=source_type,
        source_location={"table_id": marker.table_id, "cell": marker.cell_coords, "offset": marker.start},
        is_stub=True,
        raw_section_header=None,
    )


def build_tps_requirements_from_markers(marker_index: MarkerIndex, doc_json: Dict[str, Any], doc_meta: Dict[str, Any], tables_data: Optional[Dict[str, Any]] = None) -> List[Requirement]:
    """Construct TPS requirements using marker-first approach.

    We treat TPS markers (hierarchical numeric ids without '#') as anchors. For each unique TPS marker:
      - If inside a table row with structured columns (ID / Requirement / LSL/Target/USL etc.) we extract quantitative acceptance criteria.
      - If inside a table but no structured columns, we use the full row text (concatenate cells).
      - If inside a paragraph, we segment text between markers similar to RS but keep marker uid.

    requirement_uid form: TPS:#{padded}. If marker looks like '12.0' we keep as '#012.0' for consistency with validator expectations.
    """
    requirements: List[Requirement] = []
    blocks = (doc_json or {}).get('blocks', [])
    # Deduplicate markers by uid + container to avoid multi-cell duplicates in same row
    by_cont = marker_index.by_container()

    # Helper to normalize a TPS numeric id to #DDD.D style (only first two components used for padding logic)
    def canonicalize_tps_uid(raw_uid: str) -> str:
        parts = raw_uid.split('.')
        if not parts:
            return raw_uid
        try:
            first = f"{int(parts[0]):03d}"
        except Exception:
            first = parts[0]
        # Keep second part if numeric, else 0
        second = None
        if len(parts) > 1:
            try:
                second = str(int(parts[1]))
            except Exception:
                second = parts[1]
        else:
            second = '0'
        return f"#{first}.{second}"

    # Build fast lookup of table csv rows
    tables_cache: Dict[str, List[List[str]]] = {}
    if tables_data:
        for tid, info in tables_data.items():
            csv_data = (info or {}).get('csv_data') or ''
            if not csv_data:
                continue
            try:
                rows = list(csv.reader(io.StringIO(csv_data)))
            except Exception:
                rows = [r.split(',') for r in csv_data.splitlines()]
            tables_cache[tid] = rows

    # Collect markers by uid (choose the earliest occurrence per row)
    uid_markers: Dict[str, Marker] = {}
    for m in marker_index.markers:
        if m.kind != 'TPS':
            continue
        # Skip extremely long hierarchical ids (>4 components) as probable noise
        if m.uid.count('.') > 4:
            continue
        key = (m.uid, m.table_id, m.container_index)
        if m.uid not in uid_markers:
            uid_markers[m.uid] = m

    for raw_uid, marker in uid_markers.items():
        canon_uid = canonicalize_tps_uid(raw_uid)
        # Paragraph case
        if marker.container_type == 'paragraph':
            if marker.container_index >= len(blocks):
                continue
            # We need to segment the paragraph around all TPS markers in that paragraph
            paragraph_markers = [m for m in by_cont.get(('paragraph', marker.container_index, None), []) if m.kind == 'TPS']
            paragraph_markers.sort(key=lambda x: x.start or 0)
            block = blocks[marker.container_index]
            text = block.get('text', '') or ''
            for i, pm in enumerate(paragraph_markers):
                start = pm.end or 0
                end = paragraph_markers[i+1].start if i + 1 < len(paragraph_markers) else len(text)
                raw_segment = text[start:end].strip()
                if not raw_segment:
                    continue
                ac_list = extract_numbers_with_units(raw_segment)
                refs = collect_references(raw_segment)
                subj = infer_subject([], raw_segment, 'generator')
                cat = guess_category([], raw_segment)
                canonical_stmt = canonicalize(subj, raw_segment)
                ev = make_evidence_query(subj, canonical_stmt, refs)
                canon_pm = canonicalize_tps_uid(pm.uid)
                requirements.append(Requirement(
                    requirement_uid=f"TPS:{canon_pm}",
                    doc_meta=doc_meta,
                    section_path=[],
                    source_anchor={"type": "paragraph", "index": marker.container_index, "offset": pm.start},
                    normative_strength=find_normative_strength(raw_segment),
                    canonical_statement=canonical_stmt,
                    requirement_raw=raw_segment,
                    acceptance_criteria=ac_list,
                    verification_method=None,
                    references=refs,
                    subject=subj,
                    category=cat,
                    tags=[],
                    evidence_query=ev,
                    source_type='paragraph',
                    source_location={"block_index": marker.container_index},
                    is_stub=False,
                    raw_section_header=None,
                ))
            continue

        # Table cell case
        if marker.container_type == 'table_cell' and marker.table_id in tables_cache:
            rows = tables_cache[marker.table_id]
            row_idx = marker.container_index
            if row_idx >= len(rows):
                continue
            row = rows[row_idx]
            header = rows[0] if rows else []
            # Attempt to map columns
            columns_lower = [ (c or '').strip().lower() for c in header ]
            # Identify requirement text column heuristically
            req_col_idx = None
            for idx_c, name in enumerate(columns_lower):
                if name in ('requirement', 'description', 'text'):
                    req_col_idx = idx_c
                    break
            if req_col_idx is None:
                # fallback: first non-empty cell not containing the id itself
                candidates = [i for i,c in enumerate(row) if c and marker.uid not in c]
                req_col_idx = candidates[0] if candidates else 0
            requirement_raw = (row[req_col_idx] or '').strip()
            # If that cell is just the id, try adjacent cell
            if requirement_raw == marker.uid and req_col_idx + 1 < len(row):
                requirement_raw = (row[req_col_idx+1] or '').strip()
            # Aggregate numeric bounds columns
            ac_list = extract_numbers_with_units(requirement_raw)
            # If row has obvious LSL/Target/USL numeric columns, capture them explicitly
            lsl_idx = target_idx = usl_idx = None
            for idx_c, name in enumerate(columns_lower):
                if name == 'lsl': lsl_idx = idx_c
                elif name == 'target': target_idx = idx_c
                elif name == 'usl': usl_idx = idx_c
            unit = None
            if any(idx is not None for idx in (lsl_idx, target_idx, usl_idx)):
                # Add structured criteria (over and above extracted ones) if parseable
                def add_numeric(value, cmp_symbol):
                    if value is None: return
                    try:
                        v = float(str(value).strip())
                    except Exception:
                        return
                    ac_list.append(AcceptanceCriterion(id=f"{canon_uid}-{cmp_symbol}", text=f"{cmp_symbol} {v}", comparator=cmp_symbol, value=v, unit=unit))
                if lsl_idx is not None and lsl_idx < len(row):
                    add_numeric(row[lsl_idx], '>=')
                if target_idx is not None and target_idx < len(row):
                    add_numeric(row[target_idx], '=')
                if usl_idx is not None and usl_idx < len(row):
                    add_numeric(row[usl_idx], '<=')
            refs = collect_references(" ".join(row))
            subj = infer_subject([], requirement_raw, 'generator')
            cat = guess_category([], requirement_raw)
            canonical_stmt = canonicalize(subj, requirement_raw or canon_uid)
            ev = make_evidence_query(subj, canonical_stmt, refs)
            requirements.append(Requirement(
                requirement_uid=f"TPS:{canon_uid}",
                doc_meta=doc_meta,
                section_path=[],
                source_anchor={"type": "table_cell", "table": marker.table_id, "cell": marker.cell_coords},
                normative_strength=find_normative_strength(requirement_raw),
                canonical_statement=canonical_stmt,
                requirement_raw=requirement_raw or marker.raw,
                acceptance_criteria=ac_list,
                verification_method=None,
                references=refs,
                subject=subj,
                category=cat,
                tags=[],
                evidence_query=ev,
                source_type='table_cell',
                source_location={"table_id": marker.table_id, "cell": marker.cell_coords},
                is_stub=not bool(requirement_raw),
                raw_section_header=None,
            ))
            continue

    return requirements


def build_tps_requirements_from_id_tables(tables_data: Optional[Dict[str, Any]], doc_meta: Dict[str, Any], id_report: Optional[Dict[str, Any]] = None) -> List[Requirement]:
    """Extract TPS requirements specifically from tables that expose an explicit ID column.

    Heuristic logic:
      - A candidate table must have a header row whose one cell case-insensitively equals 'id'.
      - For each subsequent data row, the ID cell must match a hierarchical pattern: N.N or N.N.N (up to 5 levels).
      - Requirement text is taken primarily from a column named (case-insensitive) 'requirement' or 'requirements'.
        If absent, fallback to 'description', then 'documentation', then the longest non-ID, non-empty cell in the row.
      - References/comments column (if present) contributes to references extraction.
      - Only rows with non-empty requirement text are emitted.
    Returns a list of Requirement objects. If no qualifying table rows found, returns empty list.
    """
    if not tables_data:
        return []

    requirements: List[Requirement] = []
    ID_RE = re.compile(r'^\d+(?:\.\d+){1,4}$')  # allow 2-5 hierarchical levels

    def detect_columns(header: List[str]) -> Dict[str, int]:
        mapping: Dict[str, int] = {}
        lower = [(c or '').strip().lower() for c in header]
        for idx, name in enumerate(lower):
            if name in ('id', 'req id', 'requirement id') and 'id' not in mapping:
                mapping['id'] = idx
            elif name in ('requirement', 'requirements') and 'req' not in mapping:
                mapping['req'] = idx
            elif name == 'documentation' and 'documentation' not in mapping:
                mapping['documentation'] = idx
            elif name == 'description' and 'description' not in mapping:
                mapping['description'] = idx
            elif 'reference' in name and 'references' not in mapping:
                mapping['references'] = idx
            elif 'comment' in name and 'comments' not in mapping:
                mapping['comments'] = idx
        return mapping

    for table_id, tinfo in tables_data.items():
        csv_data = (tinfo or {}).get('csv_data') or ''
        if not csv_data:
            continue
        try:
            rows = list(csv.reader(io.StringIO(csv_data)))
        except Exception:
            rows = [r.split(',') for r in csv_data.splitlines()]
        if not rows:
            continue
        header = rows[0]
        cols = detect_columns(header)
        # Dynamic detection if explicit id header missing: pick column with majority hierarchical IDs
        if 'id' not in cols:
            candidate_scores: List[Tuple[int,int]] = []  # (matches, col_index)
            for ci in range(len(header)):
                matches = 0; non_empty = 0
                for r in rows[1:]:
                    if ci >= len(r):
                        continue
                    cell = (r[ci] or '').strip()
                    if not cell:
                        continue
                    non_empty += 1
                    if ID_RE.match(cell):
                        matches += 1
                if non_empty >= 3 and matches >= 2 and matches / max(1, non_empty) >= 0.6:
                    candidate_scores.append((matches, ci))
            if candidate_scores:
                candidate_scores.sort(reverse=True)
                cols['id'] = candidate_scores[0][1]
                if id_report is not None:
                    id_col = cols['id']
                    id_matches = sum(1 for r in rows[1:] if len(r) > id_col and ID_RE.match((r[id_col] or '').strip()))
                    id_report[table_id] = {
                        "detection_method": "pattern",
                        "id_column_index": id_col,
                        "id_column_name": (header[id_col] if id_col < len(header) else None),
                        "matched_ids": id_matches,
                        "total_rows": max(0, len(rows) - 1),
                        "header_row": header,
                    }
        else:
            if id_report is not None:
                id_col = cols['id']
                id_matches = sum(1 for r in rows[1:] if len(r) > id_col and ID_RE.match((r[id_col] or '').strip()))
                id_report[table_id] = {
                    "detection_method": "header",
                    "id_column_index": id_col,
                    "id_column_name": (header[id_col] if id_col < len(header) else None),
                    "matched_ids": id_matches,
                    "total_rows": max(0, len(rows) - 1),
                    "header_row": header,
                }
        if 'id' not in cols:
            continue  # still no ID column
        id_col = cols['id']
        # Ensure at least one hierarchical id present
        data_ids = [(r[id_col] or '').strip() for r in rows[1:] if len(r) > id_col]
        if not any(ID_RE.match(did) for did in data_ids if did):
            continue  # no hierarchical ids
        # Now iterate rows
        for r_index, row in enumerate(rows[1:], start=1):
            if id_col >= len(row):
                continue
            raw_id = (row[id_col] or '').strip()
            if not raw_id or not ID_RE.match(raw_id):
                continue
            # Determine requirement text column priority
            req_text = ''
            if 'req' in cols and cols['req'] < len(row):
                req_text = (row[cols['req']] or '').strip()
            elif 'description' in cols and cols['description'] < len(row):
                req_text = (row[cols['description']] or '').strip()
            elif 'documentation' in cols and cols['documentation'] < len(row):
                req_text = (row[cols['documentation']] or '').strip()
            if not req_text:
                # Fallback: choose the longest non-empty cell excluding id cell
                candidates = [ (len(c or ''), c) for i,c in enumerate(row) if i != id_col and c and c.strip() ]
                if candidates:
                    req_text = max(candidates, key=lambda x: x[0])[1].strip()
            if not req_text:
                continue  # skip empty requirement rows
            # Combine possible reference/comment cells for reference mining
            ref_text_parts: List[str] = []
            for key in ('references', 'comments'):
                if key in cols and cols[key] < len(row):
                    val = (row[cols[key]] or '').strip()
                    if val and val not in ('-', '—'):
                        ref_text_parts.append(val)
            full_row_text = " ".join([c for c in row if c])
            refs = collect_references(" ".join(ref_text_parts) + ' ' + full_row_text)
            # Build canonical statement and acceptance criteria
            ac_list = extract_numbers_with_units(req_text)
            subj = infer_subject([], req_text, 'generator')
            cat = guess_category([], req_text)
            canonical_stmt = canonicalize(subj, req_text)
            ev_query = make_evidence_query(subj, canonical_stmt, refs)
            # Create requirement_uid using raw hierarchical id directly
            requirement_uid = f"TPS:{raw_id}"
            requirements.append(Requirement(
                requirement_uid=requirement_uid,
                doc_meta=doc_meta,
                section_path=[],
                source_anchor={"type": "table_row", "table": table_id, "row": r_index},
                normative_strength=find_normative_strength(req_text),
                canonical_statement=canonical_stmt,
                requirement_raw=req_text,
                acceptance_criteria=ac_list,
                verification_method=None,
                references=refs,
                subject=subj,
                category=cat,
                tags=[],
                evidence_query=ev_query,
                source_type='table_row',
                source_location={"table_id": table_id, "row_index": r_index},
                is_stub=False,
                raw_section_header=None,
            ))

    return requirements


def consolidate_and_filter_tps(requirements: List[Requirement], tables_data: Optional[Dict[str, Any]] = None) -> List[Requirement]:
    """Deduplicate and suppress noisy TPS requirements produced by marker-first extraction.

    Heuristics applied:
      - Drop rows whose requirement_raw is purely numeric/punctuation tokens.
      - Drop rows like 'The generator shall <number>' (measurement artifacts).
      - Drop table-cell sourced entries from obvious measurement tables (header contains only units / numeric ranges).
      - Deduplicate by requirement_uid keeping the longest normative/text-rich instance.
      - Retain any entry with clear normative keyword (shall/must/should) even if short.
    """
    if not requirements:
        return requirements
    norm_kw_re = re.compile(r'\b(shall|must|should|will)\b', re.I)
    numeric_only_re = re.compile(r'^[0-9\s.,:+\-*/()]+$')
    deep_hier_id_re = re.compile(r'^TPS:(\d+(?:\.\d+){3,6})$')  # 4+ components hierarchical id
    gen_shall_num_re = re.compile(r'^the generator shall\s+[0-9 .,:+-]+$', re.I)

    # Build quick lookup of measurement style tables (many numeric headers)
    measurement_tables = set()
    if tables_data:
        for tid, tinfo in tables_data.items():
            hdr = tinfo.get('column_names') or []
            lower = [(h or '').lower() for h in hdr]
            if lower and sum(1 for h in lower if re.search(r'(frequency|acceleration|flow|temperature|density|capacity|conductivity|viscosity|pressure)', h)) >= max(2, len(lower)//2):
                measurement_tables.add(tid)

    filtered: List[Requirement] = []
    for r in requirements:
        raw = (r.requirement_raw or '').strip()
        uid = r.requirement_uid or ''
        drop = False
        reason = ''
        # Always retain ID-table rows (explicit table_row entries from ID-table extractor)
        if r.source_type == 'table_row':
            filtered.append(r)
            continue
        # Retention override: keep plaintext_block sourced deep hierarchical IDs even if short/non-normative
        if r.source_type == 'plaintext_block' and deep_hier_id_re.match(uid):
            filtered.append(r)
            continue
        # New retention override: keep structural docx2python sourced candidates unconditionally
        if r.source_type in ('docx2python_paragraph', 'docx2python_table_row'):
            filtered.append(r)
            continue
        if r.source_type in ('table_cell', 'table_row'):
            loc = r.source_location or {}
            tid = loc.get('table_id') or loc.get('table')
            if tid in measurement_tables and not norm_kw_re.search(raw):
                drop = True; reason = 'measurement_table_non_normative'
        if not drop and numeric_only_re.match(raw):
            drop = True; reason = 'numeric_only'
        if not drop and gen_shall_num_re.match(raw):
            drop = True; reason = 'generator_shall_number_pattern'
        if not drop and not norm_kw_re.search(raw):
            alpha_words = [w for w in re.findall(r'[A-Za-z]+', raw)]
            if len(alpha_words) < 3:
                drop = True; reason = 'too_few_alpha_words'
        if drop:
            # lightweight debug logging (can be filtered later); avoid raising
            try:
                print(f"[TPS_FILTER] Dropping {uid} src={r.source_type} reason={reason} raw_snippet={raw[:60]!r}")
            except Exception:
                pass
            continue
        filtered.append(r)

    # Deduplicate by requirement_uid
    best: Dict[str, Requirement] = {}
    def score(req: Requirement) -> int:
        raw = req.requirement_raw or ''
        s = len(raw)
        if norm_kw_re.search(raw):
            s += 50
        if req.normative_strength:
            s += 20
        return s
    for r in filtered:
        uid = r.requirement_uid
        if uid not in best or score(r) > score(best[uid]):
            best[uid] = r
    return list(best.values())


def build_tps_requirements_from_markdown(md_text: str, doc_meta: Dict[str, Any]) -> List[Requirement]:
    """Fallback parser for hierarchical TPS requirements embedded in markdown when tables were not captured.

    Looks for blocks with pattern:
      <ID> <optional product feature> <requirement sentence starting with The supplier/ The air cooler / The <subject> shall/must ...>
    Or multi-line blocks where ID line is followed by empty/feature line then requirement paragraph.
    Only captures hierarchical IDs with at least three dots (e.g. 4.1.1.1) to avoid section headings (4.1.1).
    """
    if not md_text:
        return []
    lines = [l.rstrip() for l in md_text.splitlines()]
    ID_RE = re.compile(r'^(?P<id>\d+(?:\.\d+){3,6})\b')
    start_verbs = re.compile(r'\b(shall|must|will|should)\b', re.I)
    requirements: List[Requirement] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = ID_RE.match(line)
        if not m:
            i += 1
            continue
        raw_id = m.group('id')
        # Extract remainder after id as potential feature + requirement text
        remainder = line[m.end():].strip(' -:\t')
        feature = ''
        req_text = ''
        # If remainder short and next non-empty line not an ID, treat next line(s) as requirement text
        if remainder and len(remainder.split()) <= 6 and not start_verbs.search(remainder.lower()):
            feature = remainder
        elif remainder:
            req_text = remainder
        # Gather following lines until blank or next ID/heading
        j = i + 1
        collected: List[str] = []
        while j < len(lines):
            nxt = lines[j].strip()
            if not nxt:
                if collected:
                    j += 1
                    break
                else:  # skip leading empties
                    j += 1
                    continue
            if ID_RE.match(nxt):
                break
            if re.match(r'^#{1,6} \d', nxt):
                break
            collected.append(nxt)
            j += 1
            # modest cap to avoid runaway
            if len(collected) > 8:
                break
        if not req_text:
            # choose first collected line that has a verb or normative keyword
            for c in collected:
                if start_verbs.search(c.lower()) or len(c.split()) > 6:
                    req_text = c
                    break
            if not req_text and collected:
                req_text = collected[0]
        if req_text:
            subj = infer_subject([], req_text, 'supplier')
            cat = guess_category([], req_text)
            canonical_stmt = canonicalize(subj, req_text)
            refs = collect_references(req_text)
            ac_list = extract_numbers_with_units(req_text)
            ev_query = make_evidence_query(subj, canonical_stmt, refs)
            requirements.append(Requirement(
                requirement_uid=f"TPS:{raw_id}",
                doc_meta=doc_meta,
                section_path=[],
                source_anchor={'type': 'markdown_line', 'line': i},
                normative_strength=find_normative_strength(req_text),
                canonical_statement=canonical_stmt,
                requirement_raw=req_text,
                acceptance_criteria=ac_list,
                verification_method=None,
                references=refs,
                subject=subj,
                category=cat,
                tags=[feature] if feature else [],
                evidence_query=ev_query,
                source_type='markdown_line',
                source_location={'line': i},
                is_stub=False,
                raw_section_header=None,
            ))
            i = j
        else:
            i += 1
    return requirements


def build_tps_requirements_from_plaintext(raw_text: str, doc_meta: Dict[str, Any]) -> List[Requirement]:
    """Parse hierarchical TPS requirement rows from a raw plaintext export where table-style rows
    collapsed into vertical blocks (checkbox lines followed by ID, feature, requirement paragraph).

    Recognizes IDs with 3-6 dot-separated numeric components (e.g., 4.1.1.1) to avoid section headings.
    Builds Requirement objects with source_type='plaintext_block'.
    """
    if not raw_text:
        return []
    lines = [l.rstrip() for l in raw_text.splitlines()]
    id_re = re.compile(r'^(?P<id>\d+(?:\.\d+){3,6})\s*$')
    check_re = re.compile(r'^[☐☒]{1}$')
    n = len(lines)
    i = 0
    requirements: List[Requirement] = []
    while i < n:
        m = id_re.match(lines[i])
        if not m:
            i += 1
            continue
        req_id = m.group('id')
        # Look ahead for feature (next non-empty line) and requirement paragraph
        j = i + 1
        # Skip blank lines
        while j < n and not lines[j].strip():
            j += 1
        feature = ''
        if j < n and lines[j].strip() and not id_re.match(lines[j]):
            feature = lines[j].strip()
            j += 1
        # Collect paragraph lines until blank + next id or next id directly
        para: List[str] = []
        while j < n:
            line = lines[j]
            if not line.strip():
                # Look ahead to decide stop
                k = j + 1
                while k < n and not lines[k].strip():
                    k += 1
                if k < n and id_re.match(lines[k]):
                    j = k
                    break
                para.append(line)
                j += 1
                continue
            if id_re.match(line):
                break
            para.append(line)
            j += 1
        req_text = ' '.join(p.strip() for p in para if p.strip())
        if not req_text:
            # If no paragraph captured, maybe feature itself holds the requirement
            req_text = feature
        if req_text:
            subj = infer_subject([], req_text, 'supplier')
            cat = guess_category([], req_text)
            canonical_stmt = canonicalize(subj, req_text)
            refs = collect_references(req_text)
            ac_list = extract_numbers_with_units(req_text)
            ev_query = make_evidence_query(subj, canonical_stmt, refs)
            requirements.append(Requirement(
                requirement_uid=f"TPS:{req_id}",
                doc_meta=doc_meta,
                section_path=[req_id.rsplit('.',1)[0]],
                source_anchor={'type': 'plaintext_line', 'line': i},
                normative_strength=find_normative_strength(req_text),
                canonical_statement=canonical_stmt,
                requirement_raw=req_text,
                acceptance_criteria=ac_list,
                verification_method=None,
                references=refs,
                subject=feature or subj,
                category=cat,
                tags=[feature] if feature else [],
                evidence_query=ev_query,
                source_type='plaintext_block',
                source_location={'line': i},
                is_stub=False,
                raw_section_header=None,
            ))
        i = j
    return requirements