#!/usr/bin/env python3
"""Quick debug script to test front-page parsing"""
import json
import re
from pathlib import Path

# Test the current Air Cooler parsing
tables_path = Path("TPS - A012-5599 VER 05 - confidential confidential_output") / "TPS - A012-5599 VER 05 - confidential confidential - tables_data.json"
if not tables_path.exists():
    # Try alternate paths
    for p in Path(".").glob("*Air Cooler*output*/tables_data.json"):
        tables_path = p
        break

if tables_path.exists():
    print(f"Reading: {tables_path}")
    tbl_raw = json.loads(tables_path.read_text(encoding="utf-8"))
    for tid, t in tbl_raw.items():
        csv = t.get("csv_data", "")
        print(f"\n=== Table {tid} ===")
        print("CSV data:", repr(csv[:200]))
        
        if "Document:" in csv or "Description:" in csv:
            print("Found Document/Description table!")
            
            # Test regex extraction
            doc_match = re.search(r'"Document:\s*\n([^"]+)"', csv)
            if doc_match:
                print(f"Document ID: '{doc_match.group(1).strip()}'")
            
            desc_match = re.search(r'"Description:\s*\n([^"]+)"', csv)
            if desc_match:
                print(f"Description: '{desc_match.group(1).strip()}'")
            
            # Test line-by-line
            for line in csv.splitlines():
                if "Document:" in line:
                    print(f"Document line: {repr(line)}")
                if "Description:" in line:
                    print(f"Description line: {repr(line)}")
else:
    print("Tables data file not found!")