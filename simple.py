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
from extractors import extract_from_rs_text, extract_from_tps_tables

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


def convert_docx(source: str, out_dir: str, extract_reqs: bool = True) -> dict:
    """Convert document using docling API with multi-format export and table extraction."""
    logger = logging.getLogger("simple")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    doc_filename = Path(source).stem

    logger.debug("Creating DocumentConverter instance")
    try:
        conv = DocumentConverter()
    except Exception as e:
        logger.exception("Failed to instantiate DocumentConverter: %s", e)
        raise

    logger.info("Converting source: %s", source)
    try:
        result = conv.convert(source)
    except Exception as e:
        logger.exception("Conversion raised an exception for %s: %s", source, e)
        raise

    doc = getattr(result, "document", None)
    if doc is None:
        logger.error("No document returned from converter for %s", source)
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
        else:
            logger.info("No tables found in document")

    except Exception as e:
        logger.exception("Failed to export document: %s", e)
        raise

    if extract_reqs:
        try:
            logger.info("Starting requirements extraction...")
            req_output_files = extract_requirements(out)
            output_files.update(req_output_files)
            logger.info("Finished requirements extraction.")
        except Exception as e:
            logger.error("Requirement extraction failed: %s", e, exc_info=True)
            # Do not re-raise; allow main conversion to continue

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
                    "requirements.jsonl",
                    "requirements.csv",
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

    return output_files


def extract_requirements(out_dir: Path) -> dict:
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

    requirements: list[Requirement] = []

    # RS free text extractor
    try:
        rs_reqs = extract_from_rs_text(doc_json, doc_meta)
        requirements.extend(rs_reqs)
        logger.info("RS extractor produced %d requirements", len(rs_reqs))
    except Exception as e:
        logger.warning("RS extraction failed: %s", e, exc_info=True)

    # TPS table extractor
    try:
        if tables_data:
            tps_reqs = extract_from_tps_tables(tables_data, doc_meta)
            requirements.extend(tps_reqs)
            logger.info("TPS extractor produced %d requirements", len(tps_reqs))
    except Exception as e:
        logger.warning("TPS extraction failed: %s", e, exc_info=True)

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
	parser.add_argument("--log-level", default="INFO", help="Set log level (DEBUG, INFO, WARNING, ERROR)")
	parser.add_argument("--log-file", default=None, help="Optional log file path")
	parser.add_argument("--out-dir", default=None, help="Output directory for all files (default: source_name_output)")
	parser.add_argument("--no-extract-reqs", action="store_false", dest="extract_reqs", help="Disable requirements extraction step")
	args = parser.parse_args(argv)

	level = getattr(logging, args.log_level.upper(), logging.INFO)
	logfile = Path(args.log_file) if args.log_file else None
	setup_logging(level=level, logfile=logfile)

	logger = logging.getLogger("simple")
	source_path = Path(args.source) if args.source else None

	if source_path:
		# Determine output directory
		if args.out_dir:
			out_dir = args.out_dir
		else:
			out_dir = f"{source_path.stem}_output"
		
		try:
			output_files = convert_docx(str(source_path), out_dir, extract_reqs=args.extract_reqs)
			logger.info("All files written to directory: %s", out_dir)
			for format_name, file_path in output_files.items():
				logger.info("  %s: %s", format_name, file_path)
			return 0
		except Exception as e:
			logger.error("Conversion failed: %s", e)
			return 2

	# default behavior when no source provided: try example file next to script
	default_path = Path(__file__).parent / "sample.txt"
	if default_path.exists():
		logger.info("No source provided, using default sample file: %s", default_path)
		out_dir = args.out_dir or f"{default_path.stem}_output"
		try:
			output_files = convert_docx(str(default_path), out_dir, extract_reqs=args.extract_reqs)
			logger.info("All files written to directory: %s", out_dir)
			for format_name, file_path in output_files.items():
				logger.info("  %s: %s", format_name, file_path)
			return 0
		except Exception as e:
			logger.error("Conversion failed: %s", e)
			return 2

	logger.error("No source provided and default sample file not found (%s)", default_path)
	return 1


if __name__ == "__main__":
	raise SystemExit(main())


