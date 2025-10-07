#!/usr/bin/env python3

# Direct test of the functions
from utils import collect_references, guess_category, canonicalize

test_text = "Enclosure protection shall be at least IP54 according to IEC 60034-5."
print("Direct function tests:")
print("References:", collect_references(test_text))
print("Category:", guess_category(["Electrical requirements"], test_text))
print("Canonical:", canonicalize("generator", test_text))

# Let's check if there are any namespace issues
print("\nFunction locations:")
print("collect_references:", collect_references)
print("guess_category:", guess_category)
print("canonicalize:", canonicalize)