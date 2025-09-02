#!/usr/bin/env python3
"""
Quick test to verify references and categories are working in the extractors
"""

from extractors import extract_from_rs_text

# Test RS extractor with references and categories
doc_json = {
    "blocks": [
        {"type": "heading", "level": 1, "text": "Electrical requirements"},
        {"type": "paragraph", "text": "#045.0 Enclosure protection shall be at least IP54 according to IEC 60034-5. Verification method: Test."}
    ]
}
doc_meta = {"document_id": "RS.docx", "title": "RS"}

reqs = extract_from_rs_text(doc_json, doc_meta)

if reqs:
    req = reqs[0]
    print("Requirement UID:", req.requirement_uid)
    print("Original text before VM removal:", req.requirement_raw)
    print("References:", req.references)
    print("Category:", req.category)
    print("Canonical statement:", req.canonical_statement)
    print("Verification method:", req.verification_method)
    
    # Check if references were extracted
    if req.references and "IEC 60034-5" in req.references:
        print("✓ References extraction working!")
    else:
        print("✗ References not extracted correctly")
        
    # Check if category was classified
    if req.category == "environmental":
        print("✓ Category classification working!")
    else:
        print("✗ Category not classified correctly, got:", req.category)
else:
    print("No requirements extracted")