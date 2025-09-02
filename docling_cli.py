#!/usr/bin/env python3
"""CLI to convert documents to Markdown using the installed docling package.

Usage:
  python docling_cli.py <path-or-url> [--out-dir OUT] [--stdout]

This uses the public API:
https://docling-project.github.io/docling/reference/document_converter/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List, Optional


def iter_sources(path: str) -> Iterable[str]:
    p = Path(path)
    if p.exists():
        if p.is_dir():
            for child in sorted(p.iterdir()):
                if child.is_file():
                    yield str(child)
        else:
            yield str(p)
    else:
        # treat as URL or non-existing path (let DocumentConverter handle it)
        yield path


def write_markdown(md: str, src: str, out_dir: Optional[Path]) -> Path:
    src_path = Path(src)
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / (src_path.stem + ".md")
    else:
        if src_path.exists():
            out_path = src_path.with_suffix(".md")
        else:
            # fallback to writing in cwd using safe name
            safe_name = src_path.name or "output"
            out_path = Path.cwd() / (safe_name + ".md")

    out_path.write_text(md, encoding="utf-8")
    return out_path


def convert_one(converter, source: str) -> Optional[str]:
    try:
        res = converter.convert(source)
    except Exception as exc:
        print(f"Conversion failed for {source}: {exc}", file=sys.stderr)
        return None

    doc = getattr(res, "document", None)
    if doc is None:
        print(f"No document produced for {source}", file=sys.stderr)
        return None

    if hasattr(doc, "export_to_markdown"):
        return doc.export_to_markdown()
    return str(doc)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="docling-cli",
        description="Convert documents (file path or URL) to Markdown using Docling",
    )
    parser.add_argument("source", help="Path to file, directory, or URL to convert")
    parser.add_argument("--out-dir", help="Write all output .md files to this directory")
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print markdown for the first converted document to stdout instead of writing files",
    )
    args = parser.parse_args(argv)

    try:
        from docling.document_converter import DocumentConverter as _DocumentConverter
    except ImportError:
        print(
            "Error: The 'docling' package is not installed. Please install it using 'pip install docling'",
            file=sys.stderr,
        )
        return 1

    converter = _DocumentConverter()

    out_dir = Path(args.out_dir) if args.out_dir else None

    first_printed = False
    any_converted = False

    for src in iter_sources(args.source):
        md = convert_one(converter, src)
        if md is None:
            continue
        any_converted = True

        if args.stdout and not first_printed:
            print(md)
            first_printed = True
            break

        written = write_markdown(md, src, out_dir)
        print(f"Wrote: {written}")

    if not any_converted:
        print("No documents converted.", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
