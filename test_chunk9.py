#!/usr/bin/env python3
"""
Quick test to validate Chunk 9 evidence query generation in action.
"""

from extractors import extract_from_rs_text

# Test RS extractor with evidence queries
doc_json = {
    "blocks": [
        {"type": "heading", "level": 1, "text": "Electrical requirements"},
        {"type": "paragraph", "text": "#045.0 Enclosure protection shall be at least IP54 according to IEC 60034-5. Verification method: Test."},
        {"type": "paragraph", "text": "#046.1 Vibration levels shall not exceed 2.5 mm/s RMS during operation per ISO 10816."},
        {"type": "paragraph", "text": "#047.2 Operating voltage shall be 400V ±10% at 50Hz frequency."}
    ]
}
doc_meta = {"document_id": "RS.docx", "title": "RS"}

reqs = extract_from_rs_text(doc_json, doc_meta)

print("=== Chunk 9 Evidence Query Validation ===\n")

for i, req in enumerate(reqs):
    print(f"Requirement {i+1}: {req.requirement_uid}")
    print(f"  Raw: {req.requirement_raw}")
    print(f"  Canonical: {req.canonical_statement}")
    print(f"  References: {req.references}")
    print(f"  Category: {req.category}")
    print(f"  Evidence Query: '{req.evidence_query}'")
    print()

print("=== Validation Checks ===")
for i, req in enumerate(reqs):
    checks = []
    
    # Check 1: Query contains subject
    if req.subject.lower() in req.evidence_query.lower():
        checks.append("✓ Contains subject")
    else:
        checks.append("✗ Missing subject")
    
    # Check 2: Query has reasonable length
    if 10 <= len(req.evidence_query) <= 120:
        checks.append("✓ Reasonable length")
    else:
        checks.append(f"✗ Length issue ({len(req.evidence_query)} chars)")
    
    # Check 3: Contains references if available
    if req.references:
        if any(ref in req.evidence_query for ref in req.references):
            checks.append("✓ Contains references")
        else:
            checks.append("✗ Missing references")
    else:
        checks.append("- No references to check")
    
    # Check 4: Contains key content tokens
    raw_lower = req.requirement_raw.lower()
    query_lower = req.evidence_query.lower()
    key_words = ["protection", "vibration", "voltage", "frequency"]
    found_key = any(word in raw_lower and word in query_lower for word in key_words)
    if found_key:
        checks.append("✓ Contains key terms")
    else:
        checks.append("- Key terms check")
    
    print(f"Req {i+1} ({req.requirement_uid}): {' | '.join(checks)}")

print("\n✅ Chunk 9 validation completed!")