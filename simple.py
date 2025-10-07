import argparse
import logging
import sys
from pathlib import Path
from typing import Optional
import datetime
import json
import shutil
import os
import string
import re

# For table normalization and file outputs
import pandas as pd

from models import Requirement, AcceptanceCriterion
from writers import write_requirements_jsonl, write_requirements_csv
from extractors import extract_from_rs_text, extract_from_tps_tables, extract_rs_markers_from_tables
from segmentation import build_requirements_from_markers, build_tps_requirements_from_markers, build_tps_requirements_from_id_tables, consolidate_and_filter_tps, build_tps_requirements_from_markdown, build_tps_requirements_from_plaintext
from extraction.strategy_base import ExtractionStrategyRegistry, DocumentProfile
from extraction.classifier import classify_document
from marker_index import build_marker_index
from extraction.rs_strategy import RSExtractionStrategy
from extraction.tps_strategy import TPSExtractionStrategy
from extraction.fallback_strategy import FallbackStrategy
from pandoc_normalizer import normalize_docx_with_pandoc, is_normalized_file
from requirements_validator import validate_requirements_extraction, print_validation_report, save_validation_results
from utils import build_output_subdir, ensure_output_base
from statement_extractor import (
    parse_statement_pdf,
    STATEMENT_FIELDS,
    parse_statement_text,
    excel_preserve_numeric_string,
    enrich_amounts_from_text,
)

try:
    from docling.document_converter import DocumentConverter
    # Try to import new API components, fall back gracefully
    try:
        from docling.datamodel.base_models import DoclingDocument
        from docling.datamodel.document import ExportType
        HAS_NEW_API = True
    except ImportError:
        HAS_NEW_API = False
        print("Note: Using legacy docling API. Some features may be limited.", file=sys.stderr)
except ImportError:
    print("Error: The 'docling' package is not installed. Please install it using 'pip install docling'", file=sys.stderr)
    sys.exit(1)


def setup_logging(level: int = logging.INFO, logfile: Optional[Path] = None) -> None:
	handlers = [logging.StreamHandler(sys.stdout)]
	if logfile:
		handlers.append(logging.FileHandler(logfile, encoding="utf-8"))

	logging.basicConfig(
		level=level,
		format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
		handlers=handlers,
	)


def convert_docx(source: str, out_dir: str, extract_reqs: bool = True, use_pandoc_normalization: bool = False, force_type: str | None = None, marker_first: bool = True, compare_tables_pre_post: bool = False) -> dict:
    """Convert document using docling API with multi-format export and table extraction.
    
    Args:
        source: Path to the DOCX file to convert
        out_dir: Output directory for all generated files
        extract_reqs: Whether to extract requirements from the document
        use_pandoc_normalization: Whether to normalize the DOCX with Pandoc before processing
        
    Returns:
        Dictionary mapping output format names to file paths
    """
    logger = logging.getLogger("simple")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    
    source_path = Path(source)
    actual_source = source_path
    
    # Persist source metadata for downstream helpers (e.g., plaintext fallback)
    try:
        meta_path = out / "source_meta.json"
        meta_payload = {"source_path": str(source_path), "source_name": source_path.name, "source_stem": source_path.stem}
        meta_path.write_text(json.dumps(meta_payload, indent=2), encoding="utf-8")
    except Exception:
        logging.getLogger("simple").debug("Could not write source_meta.json", exc_info=True)

    # Step 1: (Optional) structural pre-extraction for TPS DOCX using docx2python to preserve numbering
    structural_reqs = []
    structural_doc_meta = None

    if source_path.suffix.lower() == '.docx':
        # Heuristic: attempt early classification by filename hint / forced type
        forced_tps = (force_type == 'TPS') or ('TPS' in source_path.name.upper())
        if forced_tps:
            try:
                from docx_structural import extract_docx_structural_requirements  # lazy import
                struct_candidates = extract_docx_structural_requirements(str(source_path))
                # Always store (even empty) so downstream debugging can inspect attempt
                structural_reqs = struct_candidates or []
                try:
                    structural_json_path = out / "structural_docx_requirements.json"
                    structural_payload = {
                        "source_file": source_path.name,
                        "generated_at_utc": datetime.datetime.utcnow().isoformat() + "Z",
                        "candidate_count": len(struct_candidates),
                        "candidates": struct_candidates,
                    }
                    structural_json_path.write_text(json.dumps(structural_payload, indent=2, ensure_ascii=False), encoding='utf-8')
                    logging.getLogger("simple").info(
                        "Structural docx2python scan: %d candidates (written to %s)",
                        len(struct_candidates), structural_json_path)
                except Exception:
                    logging.getLogger("simple").warning("Could not write structural_docx_requirements.json", exc_info=True)
            except Exception as e:
                logging.getLogger("simple").debug("Structural DOCX parse skipped (%s)", e, exc_info=True)

    # Optional: capture pre-normalization tables snapshot for comparison
    pre_tables_snapshot = None
    if compare_tables_pre_post and source_path.suffix.lower() == '.docx':
        try:
            tmp_out = out / "__pre_tables__"
            tmp_out.mkdir(parents=True, exist_ok=True)
            conv_tmp = DocumentConverter()
            res_pre = conv_tmp.convert(str(source_path))
            doc_pre = getattr(res_pre, "document", None)
            pre_tables = {}
            if doc_pre and hasattr(doc_pre, "tables"):
                for i, table in enumerate(getattr(doc_pre, "tables", [])):
                    try:
                        df = table.export_to_dataframe()
                        pre_tables[f"table_{i+1}"] = {
                            "table_id": f"table_{i+1}",
                            "rows": len(df),
                            "columns": len(df.columns),
                            "column_names": list(df.columns),
                            "csv_data": df.to_csv(index=False),
                        }
                    except Exception:
                        pass
            pre_tables_snapshot = pre_tables
        except Exception:
            logging.getLogger("simple").debug("Could not capture pre-normalization tables", exc_info=True)

    # Step 2: Pandoc normalization if requested
    if use_pandoc_normalization and source_path.suffix.lower() == '.docx':
        if not is_normalized_file(source_path):
            logger.info("Normalizing DOCX with Pandoc before Docling processing...")
            try:
                # Save intermediate markdown and normalized doc into the output directory for debugging
                normalized_path = normalize_docx_with_pandoc(source_path, save_intermediate=True, output_dir=out)
                actual_source = normalized_path
                logger.info(f"Using normalized file for processing: {normalized_path}")
            except Exception as e:
                logger.warning(f"Pandoc normalization failed, proceeding with original file: {e}")
                actual_source = source_path
        else:
            logger.info("File appears to already be normalized, using as-is")
            actual_source = source_path
    
    doc_filename = actual_source.stem

    # Plaintext direct path (skip docling)
    if actual_source.suffix.lower() in {'.txt'}:
        logger.info("Plaintext source detected; building minimal artifacts without docling")
        raw_text = actual_source.read_text(encoding='utf-8', errors='ignore')
        # Minimal markdown = same content
        md_path = out / 'document.md'
        md_path.write_text(raw_text, encoding='utf-8')
        # Minimal JSON blocks: split paragraphs by blank lines
        paragraphs = [p.strip() for p in raw_text.split('\n\n') if p.strip()]
        blocks = []
        for p in paragraphs:
            # treat lines starting with digits pattern N. or N.N. as headings else paragraph
            if re.match(r'^\d+(?:\.\d+)*\s+.+', p) and len(p.split()) < 25:
                blocks.append({'type': 'heading', 'level': 1, 'text': p.split('\n')[0][:200]})
            else:
                blocks.append({'type': 'paragraph', 'text': p[:2000]})
        json_path = out / 'document.json'
        json_path.write_text(json.dumps({'blocks': blocks}, indent=2), encoding='utf-8')
        # Write a placeholder tables_data.json (empty)
        (out / 'tables_data.json').write_text(json.dumps({}, indent=2), encoding='utf-8')
        logger.info("Wrote minimal plaintext artifacts (markdown, json, tables_data)")
        output_files = {"markdown": str(md_path), "json": str(json_path), "output_dir": str(out)}
        if extract_reqs:
            try:
                req_out = extract_requirements(out, force_type=force_type or 'TPS', marker_first=marker_first)
                output_files.update(req_out)
            except Exception as e:
                logger.error("Plaintext requirements extraction failed: %s", e)
        return output_files

    logger.debug("Creating DocumentConverter instance")
    try:
        conv = DocumentConverter()
    except Exception as e:
        logger.exception("Failed to instantiate DocumentConverter: %s", e)
        raise

    logger.info("Converting source: %s", actual_source)
    try:
        result = conv.convert(str(actual_source))
    except Exception as e:
        logger.exception("Conversion raised an exception for %s: %s", actual_source, e)
        raise

    doc = getattr(result, "document", None)
    if doc is None:
        logger.error("No document returned from converter for %s", actual_source)
        raise ValueError("No document returned from converter")

    output_files = {}

    try:
        # Try new API first, fall back to legacy methods
        use_new_api = HAS_NEW_API and hasattr(result, 'render')
        
        if use_new_api:
            try:
                # 1) Lossless JSON (full fidelity)
                json_str = result.render(ExportType.JSON)
                json_path = out / "document.json"
                json_path.write_text(json_str, encoding="utf-8")
                output_files["json"] = str(json_path)
                logger.info("Wrote JSON to %s", json_path)

                # 2) DocTags (LLM-friendly, compact structural text)
                doctags_str = result.render(ExportType.DOC_TAGS)
                doctags_path = out / "document.doctags.txt"
                doctags_path.write_text(doctags_str, encoding="utf-8")
                output_files["doctags"] = str(doctags_path)
                logger.info("Wrote DocTags to %s", doctags_path)

                # 3) Markdown (readable; good for quick review)
                md_str = result.render(ExportType.MARKDOWN)
                md_path = out / "document.md"
                md_path.write_text(md_str, encoding="utf-8")
                output_files["markdown"] = str(md_path)
                logger.info("Wrote Markdown to %s", md_path)
            except Exception as e:
                logger.warning("New API render failed, falling back to legacy: %s", e)
                use_new_api = False

        # Legacy API fallback
        if not use_new_api:
            # Markdown export
            if hasattr(doc, "export_to_markdown"):
                md_str = doc.export_to_markdown()
            else:
                md_str = str(doc)
            md_path = out / "document.md"
            md_path.write_text(md_str, encoding="utf-8")
            output_files["markdown"] = str(md_path)
            logger.info("Wrote Markdown to %s", md_path)

            # JSON export (best effort)
            try:
                if hasattr(doc, "model_dump_json"):
                    json_str = doc.model_dump_json(indent=2)
                elif hasattr(doc, "json"):
                    json_str = doc.json(indent=2)
                elif hasattr(doc, "model_dump"):
                    json_str = json.dumps(doc.model_dump(), indent=2, default=str)
                else:
                    json_str = json.dumps({"document": str(doc)}, indent=2)
                
                json_path = out / "document.json"
                json_path.write_text(json_str, encoding="utf-8")
                output_files["json"] = str(json_path)
                logger.info("Wrote JSON to %s", json_path)
            except Exception as e:
                logger.warning("Failed to export JSON: %s", e)

        # 4) Tables: extract and include in main outputs
        tables = getattr(doc, "tables", [])
        if tables:
            logger.info("Found %d tables, processing table data for inclusion in main outputs.", len(tables))
            
            # Create a summary of all tables for easy access
            tables_summary = []
            table_details = {}
            
            for i, table in enumerate(tables):
                try:
                    # Use the built-in method to get a DataFrame
                    table_df: pd.DataFrame = table.export_to_dataframe()
                    table_id = f"table_{i+1}"
                    
                    # Create table summary info
                    table_info = {
                        "table_id": table_id,
                        "rows": len(table_df),
                        "columns": len(table_df.columns),
                        "column_names": list(table_df.columns),
                        "csv_data": table_df.to_csv(index=False),
                    }
                    
                    # Add HTML representation if available
                    if hasattr(table, "export_to_html"):
                        table_info["html_data"] = table.export_to_html(doc=doc)
                    
                    tables_summary.append({
                        "table_id": table_id,
                        "rows": table_info["rows"],
                        "columns": table_info["columns"],
                        "column_names": table_info["column_names"]
                    })
                    
                    table_details[table_id] = table_info
                    logger.info(f"Processed table {i+1}: {table_info['rows']} rows, {table_info['columns']} columns")

                except Exception as e:
                    logger.warning(f"Could not process table {i}: {e}")
            
            # Save tables summary as a separate CSV for quick reference
            if tables_summary:
                summary_df = pd.DataFrame(tables_summary)
                tables_info_path = out / "tables_info.csv"
                summary_df.to_csv(tables_info_path, index=False)
                output_files["tables_info"] = str(tables_info_path)
                logger.info(f"Wrote table summary to {tables_info_path}")
                
                # Also save detailed table data as JSON
                tables_json_path = out / "tables_data.json"
                with tables_json_path.open("w", encoding="utf-8") as f:
                    json.dump(table_details, f, indent=2, ensure_ascii=False)
                output_files["tables_data"] = str(tables_json_path)
                logger.info(f"Wrote detailed table data to {tables_json_path}")

                # If requested, save pre/post comparison snapshots
                if compare_tables_pre_post and pre_tables_snapshot is not None:
                    try:
                        with (out / "tables_data.pre.json").open("w", encoding="utf-8") as fpre:
                            json.dump(pre_tables_snapshot, fpre, indent=2, ensure_ascii=False)
                        with (out / "tables_data.post.json").open("w", encoding="utf-8") as fpost:
                            json.dump(table_details, fpost, indent=2, ensure_ascii=False)
                        output_files["tables_data_pre"] = str(out / "tables_data.pre.json")
                        output_files["tables_data_post"] = str(out / "tables_data.post.json")
                        logger.info("Wrote pre/post tables snapshots for comparison")
                    except Exception:
                        logger.debug("Could not write pre/post table snapshots", exc_info=True)
        else:
            logger.info("No tables found in document")

    except Exception as e:
        logger.exception("Failed to export document: %s", e)
        raise
    if extract_reqs:
        try:
            logger.info("Starting requirements extraction (strategy-based)...")
            req_output_files = extract_requirements(out, force_type=force_type, marker_first=marker_first)

            # If we gathered structural TPS requirements earlier, merge them here before writing artifacts
            if structural_reqs and (force_type == 'TPS' or 'TPS' in Path(source).name.upper()):
                try:
                    # Load existing requirements JSONL, append new ones avoiding duplicates
                    req_jsonl_path = Path(req_output_files.get("requirements_jsonl", out / "requirements.jsonl"))
                    existing_lines = []
                    if req_jsonl_path.exists():
                        existing_lines = req_jsonl_path.read_text(encoding='utf-8').splitlines()
                    existing_uids = set()
                    for line in existing_lines:
                        try:
                            obj = json.loads(line)
                            existing_uids.add(obj.get('requirement_uid'))
                        except Exception:
                            continue
                    added = 0
                    new_objs = []
                    for cand in structural_reqs:
                        uid = cand.get('requirement_uid')
                        if not uid or uid in existing_uids:
                            continue
                        # Construct minimal requirement record consistent with models.Requirement output schema
                        new_obj = {
                            "requirement_uid": uid,
                            "doc_meta": {"document_id": Path(out).name.rstrip('_output'), "title": Path(out).name.rstrip('_output'), "document_type": "TPS", "classification_confidence": 1.0},
                            "section_path": [uid.split(':',1)[1].rsplit('.',1)[0]] if '.' in uid.split(':',1)[1] else [],
                            "source_anchor": cand.get('source_anchor', {}),
                            "normative_strength": None,
                            "canonical_statement": cand.get('canonical_statement') or cand.get('raw',''),
                            "requirement_raw": cand.get('raw') or cand.get('canonical_statement',''),
                            "acceptance_criteria": [],
                            "verification_method": None,
                            "references": [],
                            "subject": cand.get('subject') or uid,
                            "category": None,
                            "tags": [cand.get('subject')] if cand.get('subject') else [],
                            "evidence_query": (cand.get('subject') or '').lower(),
                            "conflicts": [],
                            "dependencies": [],
                            "page_range": None,
                            "parent_id": None,
                            "confidence": None,
                            "id": None,
                            "text": None,
                            "source": None,
                            "source_type": cand.get('source_type'),
                            "source_location": cand.get('source_anchor'),
                            "is_stub": False,
                            "raw_section_header": None
                        }
                        new_objs.append(new_obj)
                        existing_uids.add(uid)
                        added += 1
                    if added:
                        logging.getLogger("simple").info("Merging %d structural DOCX requirements (docx2python) into JSONL", added)
                        # Rewrite JSONL with existing + new (sorted)
                        all_objs = [json.loads(l) for l in existing_lines if l.strip()]
                        all_objs.extend(new_objs)
                        # Simple deterministic sort: by requirement_uid
                        all_objs.sort(key=lambda o: o.get('requirement_uid',''))
                        with req_jsonl_path.open('w', encoding='utf-8') as f:
                            for obj in all_objs:
                                f.write(json.dumps(obj, ensure_ascii=False) + '\n')
                        # Also update CSV (append naive)
                        req_csv_path = Path(req_output_files.get('requirements_csv', out / 'requirements.csv'))
                        try:
                            import csv
                            # Rebuild CSV from JSONL for simplicity
                            import io
                            fieldnames = sorted({k for obj in all_objs for k in obj.keys()})
                            with req_csv_path.open('w', newline='', encoding='utf-8') as cf:
                                writer = csv.DictWriter(cf, fieldnames=fieldnames)
                                writer.writeheader()
                                for obj in all_objs:
                                    writer.writerow(obj)
                        except Exception:
                            logging.getLogger("simple").warning("Could not update requirements.csv after structural merge", exc_info=True)
                except Exception:
                    logging.getLogger("simple").warning("Structural requirements merge failed", exc_info=True)
            output_files.update(req_output_files)
            logger.info("Finished requirements extraction.")
        except Exception as e:
            logger.error("Requirement extraction failed: %s", e, exc_info=True)

    logger.info("Conversion successful for %s", source)
    # --- try to rename output folder based on front-page info (TPS -> TPS, RS -> RS) ---
    try:
        def sanitize_for_filename(s: str) -> str:
            if not s:
                return ""
            invalid = '<>:"/\\|?*\n\r\t'
            table = str.maketrans({c: " " for c in invalid})
            out_s = s.translate(table)
            out_s = "".join(ch for ch in out_s if ch in string.printable)
            out_s = " ".join(out_s.split())
            return out_s.strip()

        def find_doc_frontpage_info(out_path: Path) -> dict:
            info = {"type": None, "id": None, "desc": None}
            doc_json_path = out_path / "document.json"
            tables_json_path = out_path / "tables_data.json"
            md_path = out_path / "document.md"
            text_lines = []
            # First, try to extract Document/Description from tables_data.json (common front page pattern)
            try:
                if tables_json_path.exists():
                    tbl_raw = json.loads(tables_json_path.read_text(encoding="utf-8"))
                    # look for table entries that include 'Document:' and 'Description:' cells
                    for t in tbl_raw.values():
                        csv = t.get("csv_data", "")
                        if not csv:
                            continue
                        # simple search for labels
                        if "Document:" in csv or "Description:" in csv:
                            # Handle multiline cells with Document:\nA012-5599 VER 05 format
                            # First try to extract from quoted cells that span multiple lines
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
                            # If we found something, break
                            if info.get("id") or info.get("desc"):
                                break
            except Exception:
                pass
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
                # fallback to folder name hints
                nm = str(out.name).upper()
                if nm.startswith("TPS"):
                    info["type"] = "TPS"
                elif nm.startswith("RS"):
                    info["type"] = "RS"

            # If not already set by tables, try regex on joined text for doc id
            if not info.get("id"):
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

        def normalize_docid(raw: str) -> str:
            if not raw:
                return ""
            # Normalize variations like 01014242V05, 0101-4242V05, 0101-4242 V05 -> '0101-4242 V05'
            m = re.search(r'(\d{4})[-\s]?(\d{4})(?:\D*([Vv]\s*\d{1,3}))?', raw)
            if not m:
                return raw.strip()
            part1 = m.group(1)
            part2 = m.group(2)
            v = m.group(3) or ''
            v = v.replace(' ', '') if v else ''
            if v:
                return f"{part1}-{part2} {v.upper()}"
            return f"{part1}-{part2}"


        def assemble_pretty_name(info: dict, fallback: str) -> str:
            typ = (info.get("type") or "").upper()
            docid = info.get("id") or ""
            desc = info.get("desc") or ""
            # normalize docid
            docid = normalize_docid(docid)
            # shorten and clean description
            desc = desc.replace("/", "/").replace("&", "&")
            desc = " ".join(desc.split())[:120]
            # Remove problematic punctuation from description but keep slashes and ampersands
            desc = re.sub(r'[<>:\\"\|\?\*\n\r\t]', ' ', desc)
            desc = desc.strip(" -_.,")
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

        # Determine base name from output directory
        base_name = out.name
        if base_name.endswith("_output"):
            base_name = base_name[:-7]
        
        pretty_info = find_doc_frontpage_info(out)
        pretty_base = assemble_pretty_name(pretty_info, base_name)
        if pretty_base and pretty_base != base_name:
            parent = out.parent
            candidate = parent / f"{pretty_base}_output"
            suffix = 1
            while candidate.exists():
                candidate = parent / f"{pretty_base}_output_run{suffix}"
                suffix += 1
            shutil.move(str(out), str(candidate))
            # update output_files values to new folder
            for k, v in list(output_files.items()):
                try:
                    p = Path(v)
                    output_files[k] = str(candidate / p.name)
                except Exception:
                    pass

            # Also rename common artifact files inside the folder to include the pretty base as prefix
            try:
                prefixes = [pretty_base]
                files_to_prefix = [
                    "document.md",
                    "document.json",
                    "document.doctags.txt",
                    "tables_info.csv",
                    "tables_data.json",
                    "tables_data.pre.json",
                    "tables_data.post.json",
                    "requirements.jsonl",
                    "requirements.csv",
                    "structural_docx_requirements.json",
                    "source_meta.json",
                ]
                for fname in files_to_prefix:
                    src = candidate / fname
                    if not src.exists():
                        continue
                    # skip if already prefixed
                    if src.name.startswith(pretty_base):
                        continue
                    new_name = f"{pretty_base} - {fname}"
                    dst = candidate / new_name
                    # avoid overwriting existing file
                    if dst.exists():
                        # append run suffix
                        i = 1
                        while (candidate / f"{pretty_base} - {i} - {fname}").exists():
                            i += 1
                        dst = candidate / f"{pretty_base} - {i} - {fname}"
                    src.rename(dst)
                    # update output_files mapping if it referenced the old name
                    for k, v in list(output_files.items()):
                        try:
                            pv = Path(v)
                            if pv == src:
                                output_files[k] = str(dst)
                        except Exception:
                            pass
            except Exception:
                logger.debug("Failed to prefix internal files", exc_info=True)
            out = candidate
            logger.info("Renamed output folder to %s", str(candidate))
    except Exception:
        logger.debug("Could not apply pretty name to output folder", exc_info=True)

    # Include final output directory path for downstream processes
    output_files.setdefault("output_dir", str(out))
    # Fallback: ensure structural_docx_requirements.json exists (even empty) for DOCX TPS force_type cases
    try:
        if (force_type == 'TPS' or (source_path.suffix.lower()=='.docx' and 'TPS' in source_path.name.upper())):
            struct_json = Path(output_files["output_dir"]) / "structural_docx_requirements.json"
            if not struct_json.exists():
                payload = {
                    "source_file": source_path.name,
                    "generated_at_utc": datetime.datetime.utcnow().isoformat()+"Z",
                    "candidate_count": len(structural_reqs) if 'structural_reqs' in locals() else 0,
                    "candidates": structural_reqs if 'structural_reqs' in locals() else [],
                    "note": "Created fallback (no structural candidates captured in primary pass)"
                }
                struct_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
                logging.getLogger("simple").info("Created fallback structural_docx_requirements.json (candidates=%d)", payload["candidate_count"])
    except Exception:
        logging.getLogger("simple").debug("Could not ensure structural_docx_requirements.json", exc_info=True)
    return output_files


def extract_requirements(out_dir: Path, force_type: str | None = None, marker_first: bool = True) -> dict:
    """Extracts requirements from generated doc artifacts and writes JSONL/CSV."""
    logger = logging.getLogger("simple")

    doc_json_path = out_dir / "document.json"
    tables_json_path = out_dir / "tables_data.json"

    # Build minimal doc_meta from out_dir name
    base_name = Path(out_dir).name
    if base_name.endswith("_output"):
        base_name = base_name[:-7]
    doc_meta = {"document_id": base_name, "title": base_name}

    # Load docling JSON if present
    doc_json = {"blocks": []}
    try:
        if doc_json_path.exists():
            raw = json.loads(doc_json_path.read_text(encoding="utf-8"))
            # Some exports may nest content; prefer a top-level with blocks
            if isinstance(raw, dict) and "blocks" in raw:
                doc_json = raw
            elif isinstance(raw, dict) and "document" in raw and isinstance(raw["document"], dict):
                if "blocks" in raw["document"]:
                    doc_json = raw["document"]
            # Fallback: synthesize blocks from docling 'texts' list if no blocks were found
            if (not doc_json.get("blocks")) and isinstance(raw, dict) and "texts" in raw and isinstance(raw["texts"], list):
                blocks = []
                for t in raw["texts"]:
                    if not isinstance(t, dict):
                        continue
                    label = (t.get("label") or "").lower()
                    text = t.get("text") or ""
                    if not text:
                        continue
                    if label in ("heading", "header"):
                        # Try to infer level from name like 'header-0' in groups or default 1
                        blocks.append({"type": "heading", "level": 1, "text": text})
                    elif label in ("paragraph", "list", "inline"):
                        blocks.append({"type": "paragraph", "text": text})
                doc_json = {"blocks": blocks}
    except Exception as e:
        logger.warning("Could not parse document.json for extraction: %s", e)

    # Load tables data if present
    tables_data = {}
    try:
        if tables_json_path.exists():
            tables_data = json.loads(tables_json_path.read_text(encoding="utf-8"))
            # Our TPS extractor expects a dict of table_id -> { csv_data: ... }
            # The saved structure already matches this shape.
    except Exception as e:
        logger.warning("Could not parse tables_data.json for extraction: %s", e)

    # Register strategies (idempotent)
    ExtractionStrategyRegistry.register("RS", RSExtractionStrategy)
    ExtractionStrategyRegistry.register("TPS", TPSExtractionStrategy)
    ExtractionStrategyRegistry.register("UNKNOWN", FallbackStrategy)

    # Build marker index pre-pass (used for improved classification and later segmentation)
    marker_idx = build_marker_index(doc_json, tables_data)
    logger.info("Marker index built: RS markers=%d TPS markers=%d total=%d", marker_idx.rs_count(), marker_idx.tps_count(), len(marker_idx.markers))

    if force_type:
        profile = DocumentProfile(doc_type=force_type, confidence=1.0, features={"forced": True})
    else:
        profile = classify_document(doc_json, tables_data, filename=base_name, marker_index=marker_idx)
    logger.info(f"Document classified as {profile.doc_type} (confidence={profile.confidence}) features={profile.features}")
    doc_meta.setdefault("document_type", profile.doc_type)
    doc_meta.setdefault("classification_confidence", profile.confidence)

    requirements = []
    if marker_first and profile.doc_type == 'RS':
        # Use marker-driven segmentation for RS docs
        logger.info("Using marker-first segmentation pathway for RS document")
        try:
            requirements = build_requirements_from_markers(marker_idx, doc_json, doc_meta, tables_data)
            logger.info("Marker segmentation produced %d preliminary RS requirements (including stubs)", len(requirements))
        except Exception:
            logger.exception("Marker-first segmentation failed; falling back to legacy strategy")
            marker_first = False
    elif marker_first and profile.doc_type == 'TPS':
        logger.info("Attempting ID-table based TPS extraction prior to marker-first")
        extra_strategy = False
        try:
            # Load optional pre-normalization tables snapshot if present
            pre_tables_path = out_dir / "tables_data.pre.json"
            pre_tables_data = None
            if pre_tables_path.exists():
                try:
                    pre_tables_data = json.loads(pre_tables_path.read_text(encoding="utf-8"))
                except Exception:
                    logger.debug("Could not parse tables_data.pre.json", exc_info=True)

            # Run ID-table extraction on post (current) tables and optionally on pre tables
            id_report_post = {}
            post_id_reqs = build_tps_requirements_from_id_tables(tables_data, doc_meta, id_report_post)

            id_report_pre = {}
            pre_id_reqs = []
            if pre_tables_data:
                pre_id_reqs = build_tps_requirements_from_id_tables(pre_tables_data, doc_meta, id_report_pre)

            # Merge unique by requirement_uid, preferring post version if duplicate
            merged_by_uid = {}
            for r in pre_id_reqs:
                merged_by_uid[r.requirement_uid] = r
            for r in post_id_reqs:
                merged_by_uid[r.requirement_uid] = r
            merged_list = list(merged_by_uid.values())

            if merged_list:
                logger.info(
                    "ID-table extraction produced pre=%d post=%d -> unique=%d",
                    len(pre_id_reqs), len(post_id_reqs), len(merged_list)
                )
                requirements.extend(merged_list)
                # Save combined ID detection report for transparency
                try:
                    report_payload = {
                        "pre": id_report_pre,
                        "post": id_report_post,
                        "summary": {
                            "pre_count": len(pre_id_reqs),
                            "post_count": len(post_id_reqs),
                            "unique_count": len(merged_list)
                        }
                    }
                    report_path = out_dir / "table_id_detection_report.json"
                    with report_path.open("w", encoding="utf-8") as rf:
                        json.dump(report_payload, rf, indent=2, ensure_ascii=False)
                    logger.info("Wrote table ID detection report to %s", report_path)
                except Exception:
                    logger.debug("Could not write table_id_detection_report.json", exc_info=True)
            else:
                logger.info("No ID-table style TPS requirements found (pre/post)")
        except Exception:
            logger.exception("ID-table extraction failed; continuing")
        # Plaintext fallback (if original source was .txt saved alongside outputs)
        try:
            # Heuristic: look for sibling txt with same base name (pretty-named folder) or use original input path
            parent = out_dir.parent
            base_txt = f"{base_name}.txt"
            txt_path = parent / base_txt
            raw_text = None
            if txt_path.exists():
                raw_text = txt_path.read_text(encoding='utf-8', errors='ignore')
            else:
                # Try original source path from source_meta.json
                try:
                    meta = json.loads((out_dir / "source_meta.json").read_text(encoding='utf-8'))
                    src_stem = meta.get("source_stem")
                    src_path = Path(meta.get("source_path", ""))
                    if src_stem and src_path and src_path.exists():
                        cand = src_path.with_suffix('.txt')
                        if cand.exists():
                            raw_text = cand.read_text(encoding='utf-8', errors='ignore')
                except Exception:
                    logger.debug("Could not read source_meta.json for plaintext fallback", exc_info=True)
            if raw_text:
                pt_reqs = build_tps_requirements_from_plaintext(raw_text, doc_meta)
                existing_uids = {r.requirement_uid for r in requirements}
                new_pt = [r for r in pt_reqs if r.requirement_uid not in existing_uids]
                if new_pt:
                    logger.info("Plaintext fallback extracted %d TPS requirements", len(new_pt))
                    requirements.extend(new_pt)
        except Exception:
            logger.exception("Plaintext fallback TPS extraction failed")
        # Markdown fallback hierarchical parser (4.1.1.1 style) before marker-first
        try:
            md_path = out_dir / "document.md"
            if md_path.exists():
                md_text = md_path.read_text(encoding='utf-8')
                md_reqs = build_tps_requirements_from_markdown(md_text, doc_meta)
                existing_uids = {r.requirement_uid for r in requirements}
                new_md = [r for r in md_reqs if r.requirement_uid not in existing_uids]
                if new_md:
                    logger.info("Markdown fallback extracted %d hierarchical TPS requirements", len(new_md))
                    requirements.extend(new_md)
        except Exception:
            logger.exception("Markdown fallback TPS extraction failed")
        # Proceed with marker-first for remaining content
        try:
            tps_reqs = build_tps_requirements_from_markers(marker_idx, doc_json, doc_meta, tables_data)
            # Merge, avoiding UIDs already present from ID tables
            existing_uids = {r.requirement_uid for r in requirements}
            added = 0
            for r in tps_reqs:
                if r.requirement_uid not in existing_uids:
                    requirements.append(r)
                    added += 1
            logger.info("TPS marker-first segmentation produced %d new + %d existing = %d total", added, len(requirements)-added, len(requirements))
            # Consolidate & filter noise
            pre_cons = len(requirements)
            requirements = consolidate_and_filter_tps(requirements, tables_data)
            logger.info("Consolidated TPS requirements: %d -> %d after filtering", pre_cons, len(requirements))
            if len(requirements) < 10 and marker_idx.tps_count() > 50:
                logger.info("Combined TPS extraction still sparse (%d); enabling strategy augmentation", len(requirements))
                extra_strategy = True
        except Exception:
            logger.exception("TPS marker-first segmentation failed after ID-table phase; falling back to legacy strategy")
            marker_first = False
    else:
        extra_strategy = False
    # For non-RS documents we always run the registered strategy path
    # Only disable marker_first if RS path failed; for TPS we keep marker_first True to allow merge logic later
    if profile.doc_type == 'RS' and not marker_first:
        marker_first = False

    if not marker_first:
        strategy_cls = ExtractionStrategyRegistry.get(profile.doc_type) or FallbackStrategy
        strategy = strategy_cls(profile, doc_json, tables_data, doc_meta)
        try:
            strategy.prepare()
            requirements = strategy.extract_requirements()
            requirements = strategy.postprocess(requirements)
            logger.info("Strategy %s produced %d requirements", strategy.name, len(requirements))
        except Exception as e:
            logger.error("Strategy %s failed: %s", strategy_cls.__name__, e, exc_info=True)
            requirements = []
    elif profile.doc_type == 'TPS' and marker_first and 'extra_strategy' in locals() and extra_strategy:
        # We already have marker-first requirements in 'requirements'; run strategy and merge
        try:
            strategy_cls = ExtractionStrategyRegistry.get(profile.doc_type) or FallbackStrategy
            strategy = strategy_cls(profile, doc_json, tables_data, doc_meta)
            strategy.prepare()
            strat_reqs = strategy.extract_requirements()
            strat_reqs = strategy.postprocess(strat_reqs)
            existing_uids = {r.requirement_uid for r in requirements}
            added = 0
            for r in strat_reqs:
                if r.requirement_uid not in existing_uids:
                    requirements.append(r)
                    added += 1
            logger.info("Merged %d additional strategy TPS requirements (post marker-first)", added)
        except Exception:
            logger.warning("Could not merge strategy-based TPS requirements after marker-first", exc_info=True)

    # If we ran TPS marker-first and decided to also run strategy (extra_strategy), merge strategy results now
    # (Old merge branch removed; handled earlier)

    # Hybrid safety net: if classified TPS but we see many RS markers in text and few TPS requirements extracted, run RS extractor too.
    if profile.doc_type == "TPS":
        text_block_text = "\n".join([b.get("text", "") for b in doc_json.get("blocks", []) if isinstance(b, dict) and b.get("type") == "paragraph"])[:200000]
        rs_marker_matches = re.findall(r'#\s*\d+\s*\.\s*\d+', text_block_text)
        if len(rs_marker_matches) >= 15:
            tps_count = len(requirements)
            logger.info("Hybrid check: found %d RS-style markers in text while TPS produced %d requirements; running RS extractor additionally", len(rs_marker_matches), tps_count)
            try:
                rs_reqs = extract_from_rs_text(doc_json, {**doc_meta, "document_type": "RS"})
                # Also pick markers inside tables not converted to paragraphs
                from pathlib import Path as _P  # local import to avoid polluting global namespace
                try:
                    tables_path = out_dir / "tables_data.json"
                    tables_data_local = {}
                    if tables_path.exists():
                        tables_data_local = json.loads(tables_path.read_text(encoding="utf-8"))
                    rs_table_reqs = extract_rs_markers_from_tables(tables_data_local, {**doc_meta, "document_type": "RS"})
                    if rs_table_reqs:
                        rs_reqs.extend(rs_table_reqs)
                except Exception:
                    logger.debug("Could not perform RS table marker scan", exc_info=True)
                # Avoid UID collisions; if both sets present, keep distinct prefixes (RS:# vs TPS:)
                # Merge only if RS adds new content
                existing_uids = {r.requirement_uid for r in requirements}
                new_rs = [r for r in rs_reqs if r.requirement_uid not in existing_uids]
                if new_rs:
                    requirements.extend(new_rs)
                    logger.info("Hybrid extraction added %d RS textual requirements", len(new_rs))
            except Exception:
                logger.warning("Hybrid RS extraction failed", exc_info=True)

        # Even if paragraph markers missing, attempt detection of RS markers inside tables to decide on remap
        try:
            tables_path = out_dir / "tables_data.json"
            if tables_path.exists():
                tables_data_local = json.loads(tables_path.read_text(encoding="utf-8"))
            else:
                tables_data_local = {}
            table_csv_concat = "\n".join(t.get("csv_data", "") for t in tables_data_local.values())
            table_rs_markers = re.findall(r'#\s*\d+\s*\.\s*\d+', table_csv_concat)
            # Heuristic: if many RS markers exist and most TPS requirement_uids look numeric, remap to RS
            if len(table_rs_markers) >= 40:
                numeric_tps = [r for r in requirements if re.fullmatch(r'TPS:(\d{2,4}(?:\.\d+)?)', r.requirement_uid)]
                if numeric_tps and (len(numeric_tps) / max(1, len(requirements))) >= 0.4:
                    logger.info("Remapping %d TPS numeric IDs to RS:# form based on %d RS markers in tables", len(numeric_tps), len(table_rs_markers))
                    seen_rs = {r.requirement_uid for r in requirements}
                    converted = 0
                    for r in numeric_tps:
                        num_part = r.requirement_uid.split(':',1)[1]
                        # ensure decimal #x.y pattern (#057.0) -> keep as is
                        if '.' not in num_part:
                            num_part = f"{num_part}.0"
                        rs_uid = f"RS:#{num_part}"
                        if rs_uid in seen_rs:
                            continue
                        r.requirement_uid = rs_uid
                        converted += 1
                    logger.info("Converted %d TPS IDs to RS format", converted)
                    # Update doc_meta type to RS
                    doc_meta["document_type"] = "RS"
        except Exception:
            logger.debug("RS remap heuristic failed", exc_info=True)

    # If document truly seems RS but misclassified (RS markers overwhelm tables), re-label for downstream users
    if profile.doc_type == "TPS" and sum(1 for r in requirements if r.requirement_uid.startswith("RS:")) > sum(1 for r in requirements if r.requirement_uid.startswith("TPS:")):
        logger.info("Re-labeling document_type to RS due to majority RS-style requirements after hybrid extraction")
        doc_meta["document_type"] = "RS"

    output_files = {}

    # Write JSONL
    jsonl_path = out_dir / "requirements.jsonl"
    write_requirements_jsonl(requirements, jsonl_path)
    output_files["requirements_jsonl"] = str(jsonl_path)
    logger.info("Wrote requirements to %s", jsonl_path)

    # Write CSV
    csv_path = out_dir / "requirements.csv"
    write_requirements_csv(requirements, csv_path)
    output_files["requirements_csv"] = str(csv_path)
    logger.info("Wrote requirements to %s", csv_path)

    return output_files



def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Advanced docling conversion script with multi-format export")
    parser.add_argument("source", nargs="?", default=None, help="Path or URL to convert")
    parser.add_argument("--bank-statement", dest="bank_statement", default=None, help="Path to PDF bank/expense statement to extract Egencia style transactions (bypasses docling flow)")
    parser.add_argument("--statement-text", dest="statement_text", default=None, help="Optional path to a pre-extracted plaintext version of the statement (skip PDF text extraction)")
    parser.add_argument("--statement-amount-text", dest="statement_amount_text", default=None, help="Optional path to a simple copy/paste header lines text containing trailing amounts to enrich Beløb DKK")
    parser.add_argument("--out-csv", dest="out_csv", default=None, help="Output CSV path for bank statement rows (default: output/statement_<name>.csv)")
    parser.add_argument("--excel-preserve", action="store_true", help="Prefix long digit-only fields with apostrophe to preserve leading zeros in Excel")
    parser.add_argument("--log-level", default="INFO", help="Set log level (DEBUG, INFO, WARNING, ERROR)")
    parser.add_argument("--log-file", default=None, help="Optional log file path")
    parser.add_argument("--out-dir", default=None, help="Output directory for all files (default: source_name_output)")
    parser.add_argument("--no-extract-reqs", action="store_false", dest="extract_reqs", help="Disable requirements extraction step")
    parser.add_argument("--normalize", action="store_true", help="(optional) Explicitly enable Pandoc normalization (default: enabled)")
    parser.add_argument("--no-normalize", action="store_true", help="Disable Pandoc normalization")
    parser.add_argument("--validate-requirements", action="store_true", default=True, help="Validate requirements extraction (default: enabled)")
    parser.add_argument("--no-validate-requirements", action="store_false", dest="validate_requirements", help="Skip requirements validation")
    parser.add_argument("--force-type", choices=["RS","TPS","UNKNOWN"], help="Force document type (skip classification)")
    parser.add_argument("--no-marker-first", action="store_true", help="Disable marker-first segmentation and force strategy-based extraction path")
    parser.add_argument("--compare-tables-pre-post", action="store_true", help="Export pre/post Pandoc tables snapshots for side-by-side comparison")
    args = parser.parse_args(argv)

    # Early path: dedicated bank statement extraction (PDF -> CSV)
    if args.bank_statement:
        level = getattr(logging, args.log_level.upper(), logging.INFO)
        logfile = Path(args.log_file) if args.log_file else None
        setup_logging(level=level, logfile=logfile)
        logger = logging.getLogger("statement")
        stmt_path = Path(args.bank_statement)
        if not stmt_path.exists():
            logger.error("Bank statement file not found: %s", stmt_path)
            return 1
        try:
            if args.statement_text:
                txt_path = Path(args.statement_text)
                if not txt_path.exists():
                    logger.error("Provided --statement-text path does not exist: %s", txt_path)
                    return 1
                raw_text = txt_path.read_text(encoding='utf-8', errors='ignore')
                rows = parse_statement_text(raw_text)
            else:
                rows = parse_statement_pdf(stmt_path)
            # External amount enrichment (exclusive source)
            if args.statement_amount_text:
                amt_path = Path(args.statement_amount_text)
                if amt_path.exists():
                    try:
                        enrich_amounts_from_text(rows, amt_path.read_text(encoding='utf-8', errors='ignore'))
                        applied = sum(1 for r in rows if r.get('Beløb DKK'))
                        logger.info("Applied amounts for %d records from external text", applied)
                        missing = [r.get('ID','') for r in rows if not r.get('Beløb DKK')]
                        if applied > 50 and missing:
                            sample = ', '.join(missing[:10])
                            logger.warning("%d records still missing Beløb DKK (showing up to 10 IDs): %s", len(missing), sample)
                    except Exception as e:
                        logger.warning("Could not enrich amounts from %s: %s", amt_path, e)
        except Exception as e:
            logger.error("Failed parsing statement: %s", e, exc_info=True)
            return 2
        # Build output csv path
        if args.out_csv:
            out_csv_path = Path(args.out_csv)
            out_csv_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            # default under central output dir
            base_dir = ensure_output_base()
            out_csv_path = base_dir / f"statement_{stmt_path.stem}.csv"
        # Write CSV
        import csv
        # Use UTF-8 with BOM for better Excel handling of Danish characters
        with out_csv_path.open('w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=STATEMENT_FIELDS)
            writer.writeheader()
            preserve_fields = {"Billetnummer"}
            for rec in rows:
                out_row = {}
                for k in STATEMENT_FIELDS:
                    v = rec.get(k, '')
                    if args.excel_preserve and k in preserve_fields:
                        if isinstance(v, str) and v.isdigit():
                            v = f'="{v}"'
                        else:
                            v = excel_preserve_numeric_string(v, mode="apostrophe")
                    out_row[k] = v
                if args.excel_preserve and out_row.get('Billetnummer','').startswith("'"):
                    logger.debug("Preserved Billetnummer=%s", out_row['Billetnummer'])
                writer.writerow(out_row)
        logger.info("Extracted %d transactions -> %s", len(rows), out_csv_path)
        return 0

    # Handle normalization flags
    use_normalization = True
    if args.normalize and args.no_normalize:
        parser.error("Cannot specify both --normalize and --no-normalize")
    elif args.normalize:
        use_normalization = True
    elif args.no_normalize:
        use_normalization = False
    # Default: normalization is enabled unless explicitly disabled

    level = getattr(logging, args.log_level.upper(), logging.INFO)
    logfile = Path(args.log_file) if args.log_file else None
    setup_logging(level=level, logfile=logfile)

    logger = logging.getLogger("simple")
    source_path = Path(args.source) if args.source else None

    if source_path:
        # Determine output directory (centralized under ./output unless explicitly provided)
        if args.out_dir:
            out_dir = args.out_dir
        else:
            out_dir = str(build_output_subdir(source_path.stem))

        try:
            output_files = convert_docx(
                str(source_path),
                out_dir,
                extract_reqs=args.extract_reqs,
                use_pandoc_normalization=use_normalization,
                force_type=args.force_type,
                marker_first=(not args.no_marker_first),
                compare_tables_pre_post=args.compare_tables_pre_post
            )
            logger.info("All files written to directory: %s", out_dir)
            final_out_dir = Path(output_files.get("output_dir", out_dir))
            for format_name, file_path in output_files.items():
                logger.info("  %s: %s", format_name, file_path)

            # Validate requirements extraction if enabled
            if args.validate_requirements and args.extract_reqs and source_path.suffix.lower() == '.docx':
                logger.info("Starting requirements validation...")
                try:
                    validation_results = validate_requirements_extraction(source_path, final_out_dir)
                    print_validation_report(validation_results)
                    try:
                        save_validation_results(validation_results, final_out_dir)
                        logger.info("Saved requirements validation artifacts")
                    except Exception as e2:
                        logger.warning("Could not save validation artifacts: %s", e2)
                except Exception as e:
                    logger.error("Requirements validation failed: %s", e)
                # Don't fail the entire process if validation fails

            return 0
        except Exception as e:
            logger.error("Conversion failed: %s", e)
            return 2

    # default behavior when no source provided: try example file next to script
    default_path = Path(__file__).parent / "sample.txt"
    if default_path.exists():
        logger.info("No source provided, using default sample file: %s", default_path)
        out_dir = args.out_dir or str(build_output_subdir(default_path.stem))
        try:
            output_files = convert_docx(
                str(default_path),
                out_dir,
                extract_reqs=args.extract_reqs,
                use_pandoc_normalization=use_normalization,
                force_type=args.force_type,
                marker_first=(not args.no_marker_first),
                compare_tables_pre_post=args.compare_tables_pre_post
            )
            logger.info("All files written to directory: %s", out_dir)
            final_out_dir = Path(output_files.get("output_dir", out_dir))
            for format_name, file_path in output_files.items():
                logger.info("  %s: %s", format_name, file_path)

            # Validate requirements extraction if enabled
            if args.validate_requirements and args.extract_reqs and default_path.suffix.lower() == '.docx':
                logger.info("Starting requirements validation...")
                try:
                    validation_results = validate_requirements_extraction(default_path, final_out_dir)
                    print_validation_report(validation_results)
                    try:
                        save_validation_results(validation_results, final_out_dir)
                        logger.info("Saved requirements validation artifacts")
                    except Exception as e2:
                        logger.warning("Could not save validation artifacts: %s", e2)
                except Exception as e:
                    logger.error("Requirements validation failed: %s", e)
                # Don't fail the entire process if validation fails

            return 0
        except Exception as e:
            logger.error("Conversion failed: %s", e)
            return 2

    logger.error("No source provided and default sample file not found (%s)", default_path)
    return 1


if __name__ == "__main__":
	raise SystemExit(main())


