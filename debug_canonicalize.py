#!/usr/bin/env python3

from utils import canonicalize

text = "Enclosure protection shall be at least IP54 according to IEC 60034-5"
print("Input text:", repr(text))
print("Result:", repr(canonicalize("generator", text)))

# Check what the function sees
text_lower = text.lower()
print("Text starts with 'the generator':", text_lower.startswith("the generator"))
print("Text starts with 'generator ':", text_lower.startswith("generator "))
print("Text starts with 'the ':", text_lower.startswith("the "))