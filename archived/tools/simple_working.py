import argparse
import logging
import sys
from pathlib import Path
from typing import Optional
import datetime
import json

# For table normalization and file outputs
import pandas as pd

try:
    from docling.document_converter import DocumentConverter
except ImportError:
    print("Error: The 'docling' package is not installed. Please install it using 'pip install docling'", file=sys.stderr)
    sys.exit(1)

try:
    from pandoc_normalizer import normalize_docx_with_pandoc, is_normalized_file
    PANDOC_AVAILABLE = True
except ImportError:
    PANDOC_AVAILABLE = False


def setup_logging(level: int = logging.INFO, logfile: Optional[Path] = None) -> None:
    handlers = [logging.StreamHandler(sys.stdout)]
    if logfile:
        handlers.append(logging.FileHandler(logfile, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        handlers=handlers,
    )


def convert_docx(source: str, out_dir: str, use_pandoc_normalization: bool = False) -> dict:
    """Convert document using current docling API with multi-format export and table extraction."""
    logger = logging.getLogger("simple")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    
    source_path = Path(source)
    actual_source = source_path
    
    # Step 1: Pandoc normalization if requested
    if use_pandoc_normalization and PANDOC_AVAILABLE and source_path.suffix.lower() == '.docx':
        if not is_normalized_file(source_path):
            logger.info("Normalizing DOCX with Pandoc before Docling processing...")
            try:
                normalized_path = normalize_docx_with_pandoc(source_path)
                actual_source = normalized_path
                logger.info(f"Using normalized file for processing: {normalized_path}")
            except Exception as e:
                logger.warning(f"Pandoc normalization failed, proceeding with original file: {e}")
                actual_source = source_path
        else:
            logger.info("File appears to already be normalized, using as-is")
            actual_source = source_path
    elif use_pandoc_normalization and not PANDOC_AVAILABLE:
        logger.warning("Pandoc normalization requested but pandoc_normalizer not available")

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

        # Simple text export (fallback)
        try:
            text_str = str(doc)
            text_path = out / "document.txt"
            text_path.write_text(text_str, encoding="utf-8")
            output_files["text"] = str(text_path)
            logger.info("Wrote text to %s", text_path)
        except Exception as e:
            logger.warning("Failed to export text: %s", e)

        # Tables: basic extraction if available
        tables = getattr(doc, "tables", [])
        if tables:
            logger.info("Found %d tables in document", len(tables))
            table_data = []
            for idx, table in enumerate(tables, 1):
                table_info = {
                    "table_index": idx,
                    "table_str": str(table),
                    "table_type": type(table).__name__
                }
                table_data.append(table_info)
            
            if table_data:
                df = pd.DataFrame(table_data)
                csv_path = out / "tables_info.csv"
                df.to_csv(csv_path, index=False)
                output_files["tables_info"] = str(csv_path)
                logger.info("Wrote table info to %s", csv_path)
        else:
            logger.info("No tables found in document")

    except Exception as e:
        logger.exception("Failed to export document: %s", e)
        raise

    logger.info("Conversion successful for %s", source)
    return output_files


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Advanced docling conversion script with multi-format export")
    parser.add_argument("source", nargs="?", default=None, help="Path or URL to convert")
    parser.add_argument("--log-level", default="INFO", help="Set log level (DEBUG, INFO, WARNING, ERROR)")
    parser.add_argument("--log-file", default=None, help="Optional log file path")
    parser.add_argument("--out-dir", default=None, help="Output directory for all files (default: source_name_output)")
    parser.add_argument("--normalize", action="store_true", help="Normalize DOCX with Pandoc before processing")
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
            output_files = convert_docx(str(source_path), out_dir, use_pandoc_normalization=args.normalize)
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
            output_files = convert_docx(str(default_path), out_dir, use_pandoc_normalization=args.normalize)
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