import re
from pathlib import Path
from typing import List, Dict, Iterable

try:
    # Prefer pdfminer.six if installed (robust text layout)
    from pdfminer.high_level import extract_text as _pdf_extract_text  # type: ignore
except Exception:  # pragma: no cover
    _pdf_extract_text = None  # type: ignore

__all__ = [
    "parse_statement_pdf",
    "parse_statement_text",
    "STATEMENT_FIELDS",
    "excel_preserve_numeric_string",
    "parse_amount_header_text",
    "enrich_amounts_from_text",
]

# Canonical output columns / field labels mapping
STATEMENT_FIELDS = [
    "ID",
    "MedarbejderID",
    "Navn på rejsende",
    "Afrejsedato",
    "Hjemrejsedato",
    "Rute",
    "Rutekoder",
    "Billetnummer",
    "Projektnummer",
    "Rejsebureau momsbeløb",
    "Beløb DKK",
]

# Precompile patterns for field lines (Danish labels followed by colon)
FIELD_PATTERNS = {
    "MedarbejderID": re.compile(r"^MedarbejderID\s*:\s*(?P<val>.*)$", re.IGNORECASE),
    "Navn på rejsende": re.compile(r"^Navn på rejsende\s*:\s*(?P<val>.*)$", re.IGNORECASE),
    "Afrejsedato": re.compile(r"^Afrejsedato\s*:\s*(?P<val>.*)$", re.IGNORECASE),
    "Hjemrejsedato": re.compile(r"^Hjemrejsedato\s*:\s*(?P<val>.*)$", re.IGNORECASE),
    "Rute": re.compile(r"^Rute\s*:\s*(?P<val>.*)$", re.IGNORECASE),
    "Rutekoder": re.compile(r"^Rutekoder\s*:\s*(?P<val>.*)$", re.IGNORECASE),
    "Billetnummer": re.compile(r"^Billetnummer\s*:\s*(?P<val>.*)$", re.IGNORECASE),
    "Projektnummer": re.compile(r"^Projektnummer\s*:\s*(?P<val>.*)$", re.IGNORECASE),
    "Rejsebureau momsbeløb": re.compile(r"^Rejsebureau momsbeløb\s*:\s*(?P<val>.*)$", re.IGNORECASE),
}

# Heuristic (refined): Egencia style IDs observed like 'DKSC140289938' (prefix letters then digits).
# We tighten the pattern to reduce false positives where ordinary value lines (e.g. hotel names)
# were previously mis-identified as headers, producing spurious rows in the CSV.
# Pattern: 3-6 uppercase letters followed by 5+ digits. Anything after is free text.
ID_LINE_RE = re.compile(r"^(?P<id>[A-Z]{3,6}[0-9]{5,})\b.*$")


def _iter_lines(text: str) -> Iterable[str]:
    for raw in text.splitlines():
        # Normalize stray CR and trim right-side spaces only; keep left for potential leading IDs
        yield raw.rstrip()


def parse_statement_text(text: str) -> List[Dict[str, str]]:
    """Parse Egencia style statement.

    Pattern observed:
      HEADER (ID + description)
      Label lines (each ends with ':')
      (possibly blank line)
      Value lines in same order as labels
      Optional trailing numeric tax value if label present but value list shorter by one.

    We iterate linearly and build records accordingly; this avoids mis-grouping across blocks.
    """
    lines = [l.rstrip() for l in text.splitlines()]
    records: List[Dict[str,str]] = []
    i = 0
    n = len(lines)
    label_key_map = {k:k for k in FIELD_PATTERNS.keys()}
    # Pre-build simple label detection (exact line match like 'MedarbejderID:')
    simple_labels = {f+':': f for f in FIELD_PATTERNS.keys()}
    last_record: Dict[str,str] | None = None
    # Amount detection heuristics removed; enrichment file provides amounts.
    while i < n:
        raw_line = lines[i].rstrip('\n')
        raw = raw_line.strip().replace('\u00a0',' ')
        if not raw:
            i += 1
            continue
        m = ID_LINE_RE.match(raw)
        if m:
            # Relaxed header validation: accept if we find at least one inline label within next lines
            look = i + 1
            found_inline_label = False
            scanned = 0
            while look < n and scanned < 12:
                probe = lines[look].strip()
                if any(pat.match(probe) for pat in FIELD_PATTERNS.values()):
                    found_inline_label = True
                    break
                if ID_LINE_RE.match(probe):
                    break
                look += 1
                scanned += 1
            if not found_inline_label:
                # treat as continuation of previous Rute
                if last_record is not None:
                    if last_record.get('Rute'):
                        last_record['Rute'] += ' ' + raw
                    else:
                        last_record['Rute'] = raw
                i += 1
                continue
            # Genuine header
            # Remove trailing amount token (space + number) from header; external enrichment supplies amount
            header = raw
            m_amt = re.search(r'(.*)\s-?\d+[.,]\d{2}$', header)
            if m_amt:
                header = m_amt.group(1)
            # Reset per-record amount probe
            probe_amount = None
            j = i + 1
            label_order: List[str] = []
            values: List[str] = []
            # (Standalone amount probe removed.)
            while j < n:
                t = lines[j].strip()
                if not t:
                    j += 1
                    break
                # Support inline label:value lines in the same block
                inline_matched = False
                for fname, pat in FIELD_PATTERNS.items():
                    mline = pat.match(t)
                    if mline:
                        if fname not in label_order:
                            label_order.append(fname)
                        # Store inline value immediately by appending to values list
                        values_inline_val = mline.group('val').strip()
                        # Normalize tax decimal comma
                        if fname == 'Rejsebureau momsbeløb':
                            values_inline_val = values_inline_val.replace(',', '.')
                        # Ensure position alignment: append placeholder if needed
                        # We'll simply append; later assignment enumerates label_order sequentially.
                        values.append(values_inline_val)
                        inline_matched = True
                        j += 1
                        break
                if inline_matched:
                    continue
                if t in simple_labels:
                    label_order.append(simple_labels[t])
                    j += 1
                    continue
                if ID_LINE_RE.match(t):
                    break
                break
            k = j
            while k < n:
                t = lines[k].strip()
                if not t:
                    k += 1
                    continue
                if ID_LINE_RE.match(t) and values:
                    break
                if len(values) >= len(label_order)+1:
                    if ID_LINE_RE.match(t):
                        break
                # Skip further value collection if this is another label line (already captured inline)
                if any(pat.match(t) for pat in FIELD_PATTERNS.values()):
                    break
                values.append(t)
                k += 1
                if len(values) >= len(label_order) and k < n and ID_LINE_RE.match(lines[k].strip()):
                    break
            if len(label_order) < 2:
                # Safety: abandon if not enough labels after all (shouldn't happen here)
                if last_record is not None:
                    if last_record.get('Rute'):
                        last_record['Rute'] += ' ' + header
                    else:
                        last_record['Rute'] = header
                i += 1
                continue
            rec = {field: "" for field in STATEMENT_FIELDS}
            rec['ID'] = header.strip()
            for idx_label, field in enumerate(label_order):
                if idx_label < len(values):
                    val = values[idx_label]
                    if field == 'Rejsebureau momsbeløb':
                        val = val.replace(',', '.')
                    rec[field] = val
            if 'Rejsebureau momsbeløb' in label_order:
                try:
                    if not rec['Rejsebureau momsbeløb']:
                        extra_candidate = None
                        if len(values) > len(label_order):
                            extra_candidate = values[-1]
                        if extra_candidate and re.match(r'^-?\d+[.,]\d{2}$', extra_candidate):
                            rec['Rejsebureau momsbeløb'] = extra_candidate.replace(',', '.')
                        elif not rec['Rejsebureau momsbeløb']:
                            for vv in reversed(values):
                                if re.match(r'^-?\d+[.,]\d{2}$', vv):
                                    rec['Rejsebureau momsbeløb'] = vv.replace(',', '.')
                                    break
                except ValueError:
                    pass
            # Multi-line Rute enrichment: any trailing non-numeric, non-header lines beyond mapped labels
            if rec.get('Rute'):
                extras = []
                for extra in values[len(label_order):]:
                    if re.match(r'^-?\d+[.,]\d{2}$', extra):
                        # numeric already considered (tax or misaligned amount)
                        continue
                    if ID_LINE_RE.match(extra):
                        continue
                    if extra in (f+':' for f in FIELD_PATTERNS.keys()):
                        continue
                    extras.append(extra)
                if extras:
                    rec['Rute'] = (rec['Rute'] + ' ' + ' '.join(extras)).strip()
            # Internal Beløb DKK heuristics removed: value will be populated only via external enrichment.
            for kf, vv in list(rec.items()):
                rec[kf] = re.sub(r'\s+', ' ', vv).strip()
            records.append(rec)
            last_record = rec
            i = k
            continue
        else:
            # Non-header stray line: attach to last record Rute if plausible (avoid duplicating values for other fields)
            if last_record is not None:
                # Skip if label-like or pure amount
                if not raw.endswith(':') and not FIELD_PATTERNS['MedarbejderID'].match(raw):
                    if not re.match(r'^-?\d+[.,]\d{2}$', raw):
                        if last_record.get('Rute'):
                            last_record['Rute'] += ' ' + raw
                        else:
                            last_record['Rute'] = raw
            i += 1
            continue
    return records


def excel_preserve_numeric_string(val: str, min_len: int = 10, mode: str = "formula") -> str:
    """Return a representation safe for Excel to avoid scientific notation / leading-zero loss.

    Args:
        val: Original string value.
        min_len: Minimum length at which pure digits should be preserved.
        mode: 'formula' -> returns ="<digits>" (Excel treats as text, displays without leading '=')
              'apostrophe' -> prefixes apostrophe (visible) for fallback.

    We treat any all-digit string meeting length or leading-zero criteria. If already protected
    (starts with =" or apostrophe) we return unchanged.
    """
    if not isinstance(val, str):
        return val
    v = val.strip()
    if not v:
        return v
    if v.startswith("='") or v.startswith("=") and v.endswith(""):
        return v
    if v.startswith("=") and v.startswith('="'):
        return v
    if v.startswith("'"):
        return v
    if v.isdigit() and (len(v) >= min_len or v.startswith('0')):
        if mode == 'apostrophe':
            return "'" + v
        # formula mode
        return f'="{v}"'
    return v


AMOUNT_SUFFIX_RE = re.compile(r"^(?P<header>.+?)\s+(-?\d+[.,]\d{2})\s*$")


def parse_amount_header_text(text: str) -> dict:
    """Parse a simple copy/paste plaintext where each transaction header line ends with amount.

    Returns mapping of detected ID -> amount string (normalized with dot).
    """
    mapping = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = AMOUNT_SUFFIX_RE.match(line)
        if not m:
            continue
        amount = m.group(2) if m.lastindex and m.lastindex >= 2 else line.rsplit(' ',1)[-1]
        amount_norm = amount.replace(',', '.')
        # Extract ID token (first contiguous uppercase+digits segment length>=8)
        parts = line.split()
        if not parts:
            continue
        id_token = None
        for p in parts:
            if re.match(r'^[A-Z]{3,6}[0-9]{5,}$', p):
                id_token = p
                break
        if id_token:
            mapping[id_token] = amount_norm
    return mapping


def enrich_amounts_from_text(rows: list[dict], amount_text: str) -> None:
    mapping = parse_amount_header_text(amount_text)
    for rec in rows:
        full_id = rec.get('ID','')
        # Leading token (up to first space) is the canonical ID key
        key = full_id.split()[0] if full_id else ''
        if key in mapping:
            rec['Beløb DKK'] = mapping[key]


def parse_statement_pdf(pdf_path: str | Path) -> List[Dict[str, str]]:
    path = Path(pdf_path)
    if not path.exists():  # pragma: no cover
        raise FileNotFoundError(path)
    if _pdf_extract_text is None:
        raise RuntimeError("pdfminer.six not installed; please pip install pdfminer.six to enable PDF parsing")
    text = _pdf_extract_text(str(path))
    return parse_statement_text(text)

if __name__ == "__main__":  # simple manual debug
    import sys, json
    if len(sys.argv) != 2:
        print("Usage: python statement_extractor.py <statement.pdf>")
        raise SystemExit(1)
    rows = parse_statement_pdf(sys.argv[1])
    print(json.dumps(rows, indent=2, ensure_ascii=False))
