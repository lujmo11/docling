import re
from typing import List, Dict, Any
import io
import pandas as pd
from models import Requirement
from utils import SectionTracker, find_normative_strength, extract_numbers_with_units, canonicalize, infer_subject, collect_references, guess_category, make_evidence_query

def extract_from_rs_text(doc_json: Dict[str, Any], doc_meta: Dict[str, Any]) -> List[Requirement]:
    """
    Extracts requirements from RS-style text blocks.
    """
    requirements = []
    section_tracker = SectionTracker()

    for block in doc_json.get("blocks", []):
        section_path = section_tracker.update_and_get_path(block)
        if block.get("type") != "paragraph":
            continue

        text = block.get("text", "")
        # Regex to find requirement markers like #xxx.x, robust to spaces
        markers = list(re.finditer(r'#\s*(\d+\s*\.\s*\d+)', text))

        for i, match in enumerate(markers):
            marker_id = match.group(1).replace(" ", "")
            start_pos = match.end()
            
            # The requirement text is from the current marker to the start of the next, or the end of the block
            end_pos = markers[i+1].start() if i + 1 < len(markers) else len(text)
            req_text_raw = text[start_pos:end_pos].strip()

            # Extract verification method
            verification_method = None
            vm_match = re.search(r'Verification method:\s*(.*?)\.', req_text_raw, re.IGNORECASE)
            if vm_match:
                verification_method = vm_match.group(1).strip()
                # Remove only the verification method part from the raw text, keep everything before it
                req_text_raw = req_text_raw[:vm_match.start()].strip()

            # Use functions from previous and future chunks
            normative_strength = find_normative_strength(req_text_raw)
            acceptance_criteria = extract_numbers_with_units(req_text_raw)
            references = collect_references(req_text_raw)
            subject = infer_subject(section_path, req_text_raw, "generator")
            category = guess_category(section_path, req_text_raw)
            canonical_statement = canonicalize(subject, req_text_raw)
            evidence_query = make_evidence_query(subject, canonical_statement, references)

            req = Requirement(
                requirement_uid=f"RS:#{marker_id}",
                doc_meta=doc_meta,
                section_path=section_path,
                source_anchor={"type": "text", "ref": f"#{marker_id}"},
                normative_strength=normative_strength,
                canonical_statement=canonical_statement,
                requirement_raw=req_text_raw,
                acceptance_criteria=acceptance_criteria,
                verification_method=verification_method,
                references=references,
                subject=subject,
                category=category,
                tags=[], # Placeholder
                evidence_query=evidence_query,
            )
            requirements.append(req)
            
    return requirements


def extract_rs_markers_from_tables(tables_data: Dict[str, Any], doc_meta: Dict[str, Any]) -> List[Requirement]:
    """Scan table CSV text for RS style markers (#123.4) and create minimal Requirement entries.

    This supplements textual RS extraction when markers were embedded in 2-col tables that were
    previously treated as TPS style. Avoid duplicates by tracking seen IDs.
    """
    requirements: List[Requirement] = []
    seen: set[str] = set()
    marker_re = re.compile(r'#\s*(\d+\s*\.\s*\d+)')
    for table_id, table in (tables_data or {}).items():
        csv_text = table.get("csv_data") or ""
        if not csv_text:
            continue
        # Quick skip if no '#'
        if '#' not in csv_text:
            continue
        for match in marker_re.finditer(csv_text):
            marker_id = match.group(1).replace(" ", "")
            uid = f"RS:#{marker_id}"
            if uid in seen:
                continue
            seen.add(uid)
            req = Requirement(
                requirement_uid=uid,
                doc_meta=doc_meta,
                section_path=[],
                source_anchor={"type": "table", "ref": table_id, "pos": match.start()},
                normative_strength=None,
                canonical_statement=f"Requirement #{marker_id}",
                requirement_raw=f"#{marker_id}",
                acceptance_criteria=[],
                verification_method=None,
                references=[],
                subject="generator",
                category=None,
                tags=[],
                evidence_query=f"requirement {marker_id}",
            )
            requirements.append(req)
    return requirements


def extract_from_tps_tables(tables_data: Dict[str, Any], doc_meta: Dict[str, Any]) -> List[Requirement]:
    """Extracts requirements from TPS-style tables.

    tables_data: dict where each value has a key 'csv_data' with CSV string.
    """
    requirements: List[Requirement] = []

    def norm_unit(u: str) -> str:
        from utils import normalize_unit
        return normalize_unit(u) if u else u

    for table_id, table in tables_data.items():
        csv_text = table.get("csv_data")
        if not csv_text:
            continue
        try:
            df = pd.read_csv(io.StringIO(csv_text))
        except Exception:
            continue

        # Normalize column names
        cols = {str(c).strip(): c for c in df.columns}
        get = lambda name: cols.get(name, None)

        # Case A: Structured spec table with bounds
        id_col = get("ID")
        subj_col = get("Subject")
        req_col = get("Requirement")
        unit_col = get("Unit")
        lsl_col = get("LSL")
        target_col = get("Target")
        usl_col = get("USL")

        # Case B: Two-column tables where col0 is free text and col1 contains IDs like #057.0
        is_two_col_with_ids = False
        if len(df.columns) == 2 and not req_col and not lsl_col and not target_col and not usl_col:
            # Heuristic: check if second column cells look like '#ddd.d'
            second = df.iloc[:, 1].astype(str).str.strip()
            if (second.str.match(r"^#\s*\d+(?:[\.-]\d+)?\s*$").fillna(False).any()):
                is_two_col_with_ids = True
                
        # Case C: Parameter-Value tables (common in technical specifications)
        is_parameter_value_table = False
        if len(df.columns) == 2 and not is_two_col_with_ids:
            # Check if first column contains parameter names and second column contains values
            # Common headers for parameter-value tables
            param_headers = ['parameter', 'description', 'test method', 'direction', 'temperature', 'pressure']
            value_headers = ['value', 'setting', 'specification', 'requirement', 'result']
            
            col0_lower = str(df.columns[0]).lower()
            col1_lower = str(df.columns[1]).lower()
            
            # Check if column headers match parameter-value pattern
            if any(ph in col0_lower for ph in param_headers) or any(vh in col1_lower for vh in value_headers):
                is_parameter_value_table = True
            # Even if headers don't match, check if it looks like a parameter-value table
            # by seeing if the first column contains text and second column often contains numbers
            elif df.shape[0] > 1:
                col0_all_text = df.iloc[:, 0].astype(str).str.strip().str.len() > 0
                col1_has_numbers = df.iloc[:, 1].astype(str).str.contains(r'\d').fillna(False)
                if col0_all_text.all() and col1_has_numbers.any():
                    is_parameter_value_table = True

        for idx, row in df.iterrows():
            from models import AcceptanceCriterion
            ac_list = []
            subject = "generator"
            verification_method = None

            if is_two_col_with_ids:
                raw_text = str(row.iloc[0]).strip() if not pd.isna(row.iloc[0]) else ""
                id_cell = str(row.iloc[1]).strip() if not pd.isna(row.iloc[1]) else ""
                m = re.search(r"#\s*(\d+(?:[\.-]\d+)?)", id_cell)
                if not raw_text and not m:
                    continue
                row_id = m.group(1).replace(" ", "") if m else f"{table_id}:{idx+1}"
                # Parse verification method if present inline
                vm = re.search(r"Verification method:\s*(.*?)\.?\s*$", raw_text, re.IGNORECASE)
                if vm:
                    verification_method = vm.group(1).strip()
                    raw_text = raw_text[:vm.start()].strip()
                # Extract numeric criteria from text
                ac_list = extract_numbers_with_units(raw_text)
                subject = infer_subject([], raw_text, "generator")
                canonical_statement = canonicalize(subject, raw_text)
            elif is_parameter_value_table:
                # Extract key and value from the parameter-value table
                param_name = str(row.iloc[0]).strip() if not pd.isna(row.iloc[0]) else ""
                param_value = str(row.iloc[1]).strip() if not pd.isna(row.iloc[1]) else ""
                
                if not param_name or not param_value:
                    continue  # Skip empty rows
                
                row_id = f"{table_id}:{idx+1}"
                
                # Use parameter name as the subject
                subject = param_name.lower()
                if subject.endswith(":"):
                    subject = subject[:-1].strip()
                
                # The raw text is the parameter and its value
                raw_text = f"{param_name}: {param_value}"
                
                # Extract numeric criteria from the value
                ac_list = extract_numbers_with_units(param_value)
                
                # If no acceptance criteria were found but the value has numbers, add a default one
                if not ac_list and re.search(r'\d', param_value):
                    # Try to parse unit from the value text
                    unit_match = re.search(r'\d+(?:\.\d+)?\s*([a-zA-Z°%]+(?:/[a-zA-Z]+)?)', param_value)
                    unit = unit_match.group(1) if unit_match else None
                    unit = norm_unit(unit) if unit else None
                    
                    # Try to extract the first number
                    num_match = re.search(r'(\d+(?:\.\d+)?)', param_value)
                    if num_match:
                        value = float(num_match.group(1))
                        ac_list.append(AcceptanceCriterion(id=f"{row_id}-eq", text=f"= {value} {unit or ''}".strip(), 
                                                           comparator="=", value=value, unit=unit))
                
                # Create canonical statement
                canonical_statement = f"The {subject} shall be {param_value}"
            else:
                row_id = str(row[id_col]).strip() if id_col in df.columns and not pd.isna(row[id_col]) else f"{table_id}:{idx+1}"
                subject = (str(row[subj_col]).strip() if subj_col in df.columns and not pd.isna(row[subj_col]) else "generator")
                raw_text = (str(row[req_col]).strip() if req_col in df.columns and not pd.isna(row[req_col]) else "").strip()
                unit = (str(row[unit_col]).strip() if unit_col in df.columns and not pd.isna(row[unit_col]) else None)
                unit = norm_unit(unit) if unit else None

                # Numeric bounds
                def add_numeric(cmp_symbol: str, value):
                    if pd.isna(value):
                        return
                    try:
                        v = float(value)
                    except Exception:
                        return
                    ac_list.append(AcceptanceCriterion(id=f"{row_id}-{cmp_symbol}", text=f"{cmp_symbol} {v} {unit or ''}".strip(), comparator=cmp_symbol, value=v, unit=unit))

                if lsl_col in df.columns:
                    add_numeric(">=", row[lsl_col])
                if target_col in df.columns:
                    add_numeric("=", row[target_col])
                if usl_col in df.columns:
                    add_numeric("<=", row[usl_col])

                canonical_statement = canonicalize(subject, raw_text or f"{unit or 'specification'}")

            # Skip rows without meaningful content
            if not raw_text and not ac_list:
                continue

            req = Requirement(
                requirement_uid=f"TPS:{row_id}",
                doc_meta=doc_meta,
                section_path=[],
                source_anchor={"type": "table", "ref": table_id, "row": int(idx) + 1},
                normative_strength=find_normative_strength(raw_text) if is_two_col_with_ids else None,
                canonical_statement=canonical_statement,
                requirement_raw=raw_text,
                acceptance_criteria=ac_list,
                verification_method=verification_method,
                references=collect_references(raw_text),
                subject=subject,
                category=guess_category([], raw_text),
                tags=[],
                evidence_query=make_evidence_query(subject, canonical_statement, collect_references(raw_text)),
            )
            requirements.append(req)

    return requirements
