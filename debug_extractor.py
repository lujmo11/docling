#!/usr/bin/env python3

import re

# Simulate what happens in the extractor
text = "#045.0 Enclosure protection shall be at least IP54 according to IEC 60034-5. Verification method: Test."

# Find marker
markers = list(re.finditer(r'#\s*(\d+(?:[\.-]\d+)?)', text))
if markers:
    marker = markers[0]
    marker_id = marker.group(1).replace(" ", "")
    print("Marker ID:", marker_id)
    
    # Extract requirement text
    start_pos = marker.end()
    end_pos = len(text)  # No next marker
    req_text_raw = text[start_pos:end_pos].strip()
    print("Initial req_text_raw:", repr(req_text_raw))
    
    # Extract verification method
    vm_match = re.search(r'Verification method:\s*(.*?)\.', req_text_raw, re.IGNORECASE)
    if vm_match:
        verification_method = vm_match.group(1).strip()
        print("Verification method:", verification_method)
        req_text_raw = req_text_raw[:vm_match.start()].strip()
        print("After VM removal:", repr(req_text_raw))

from utils import collect_references, guess_category

print("References:", collect_references(req_text_raw))
print("Category:", guess_category(["Electrical requirements"], req_text_raw))