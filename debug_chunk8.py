#!/usr/bin/env python3

from utils import collect_references, guess_category, canonicalize

text = "Enclosure protection shall be at least IP54 according to IEC 60034-5."

print("Testing collect_references:")
refs = collect_references(text)
print("References found:", refs)

print("\nTesting guess_category:")
category = guess_category(["Electrical requirements"], text)
print("Category:", category)

print("\nTesting canonicalize:")
canonical = canonicalize("generator", text)
print("Canonical:", canonical)