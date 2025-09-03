import unittest
from utils import normalize_unit, extract_numbers_with_units, find_normative_strength, SectionTracker, canonicalize, infer_subject, collect_references, guess_category, make_evidence_query

class TestUtils(unittest.TestCase):

    def test_normalize_units(self):
        self.assertEqual(normalize_unit("°C"), "degC")
        self.assertEqual(normalize_unit("kV/µs"), "kV/us")
        self.assertEqual(normalize_unit("mm/s"), "mm_per_s")
        self.assertEqual(normalize_unit("V RMS"), "V_rms")

    def test_extract_numbers_with_units(self):
        test_cases = {
            "≤ 3.5 kV/µs": ("<=", 3.5, "kV/us"),
            "2000 V": ("=", 2000.0, "V"),
            "1.8 mm/s": ("=", 1.8, "mm_per_s"),
            "780 V RMS": ("=", 780.0, "V_rms"),
            "90 °C": ("=", 90.0, "degC"),
            "102 dB(A)": ("=", 102.0, "dB(A)"),
        }

        for text, expected in test_cases.items():
            with self.subTest(text=text):
                crits = extract_numbers_with_units(text)
                self.assertEqual(len(crits), 1)
                crit = crits[0]
                self.assertEqual(crit.comparator, expected[0])
                self.assertEqual(crit.value, expected[1])
                self.assertEqual(crit.unit, expected[2])

    def test_extract_no_numbers(self):
        self.assertEqual(extract_numbers_with_units("Some text with no numbers."), [])

    def test_find_normative_strength(self):
        self.assertEqual(find_normative_strength("The machine shall be IP54."), "MUST")
        self.assertEqual(find_normative_strength("The machine must be IP54."), "MUST")
        self.assertEqual(find_normative_strength("The machine SHOULD be painted."), "SHOULD")
        self.assertEqual(find_normative_strength("Operator may do X."), "MAY")
        self.assertIsNone(find_normative_strength("Informative text"))
        self.assertEqual(find_normative_strength("This is a test that SHALL pass."), "MUST")

    def test_section_tracker(self):
        tracker = SectionTracker()
        
        # H1
        path = tracker.update_and_get_path({"type": "heading", "level": 1, "text": "Electrical requirements"})
        self.assertEqual(path, ["Electrical requirements"])

        # H2
        path = tracker.update_and_get_path({"type": "heading", "level": 2, "text": "Rated voltage"})
        self.assertEqual(path, ["Electrical requirements", "Rated voltage"])

        # Paragraph (path should not change)
        path = tracker.update_and_get_path({"type": "paragraph", "text": "Some text..."})
        self.assertEqual(path, ["Electrical requirements", "Rated voltage"])

        # H4 (skip a level)
        path = tracker.update_and_get_path({"type": "heading", "level": 4, "text": "Sub-detail"})
        self.assertEqual(path, ["Electrical requirements", "Rated voltage", "Sub-detail"])

        # Back to H2 (should pop H4)
        path = tracker.update_and_get_path({"type": "heading", "level": 2, "text": "Current rating"})
        self.assertEqual(path, ["Electrical requirements", "Current rating"])

        # Malformed heading (should not crash and path remains)
        path = tracker.update_and_get_path({"type": "heading"})
        self.assertEqual(path, ["Electrical requirements", "Current rating"])

        # Another H1 (should reset stack)
        path = tracker.update_and_get_path({"type": "heading", "level": 1, "text": "Mechanical requirements"})
        self.assertEqual(path, ["Mechanical requirements"])

    def test_canonicalize(self):
        # Test cases from the plan
        self.assertEqual(
            canonicalize("generator", "be IP54 or higher."),
            "The generator shall be IP54 or higher."
        )
        
        # Text starting with subject should remain unchanged
        self.assertEqual(
            canonicalize("generator", "Generator protection shall be adequate."),
            "Generator protection shall be adequate."
        )
        
        # Text starting with "the [subject]" should remain unchanged
        self.assertEqual(
            canonicalize("generator", "The generator must be reliable."),
            "The generator must be reliable."
        )
        
        # Text starting with "the" but not "the [subject]" should remain unchanged
        self.assertEqual(
            canonicalize("generator", "The system shall operate correctly."),
            "The system shall operate correctly."
        )
        
        # Empty text should get default statement
        self.assertEqual(
            canonicalize("generator", ""),
            "The generator shall comply with unspecified requirements."
        )
        
        # Mixed case handling
        self.assertEqual(
            canonicalize("generator", "Meet all safety requirements."),
            "The generator shall meet all safety requirements."
        )

    def test_infer_subject(self):
        # Simple test - should default to "generator"
        self.assertEqual(infer_subject([], "some text"), "generator")
        self.assertEqual(infer_subject(["Electrical"], "voltage text"), "generator")
        
        # Test custom default
        self.assertEqual(infer_subject([], "some text", "motor"), "motor")

    def test_collect_references(self):
        # Test cases from the plan
        test_cases = [
            ("according to IEC 60034-5", ["IEC 60034-5"]),
            ("per IEC 60034-14:2004 standard", ["IEC 60034-14:2004"]),
            ("ISO 1940-1:2003 requirements", ["ISO 1940-1:2003"]),
            ("DIN 42955 specification", ["DIN 42955"]),
            ("UL 1004-1 compliance", ["UL 1004-1"]),
            ("CSA SPE-1000-13 standard", ["CSA SPE-1000-13"]),
            ("Multiple standards: IEC 60034-5 and ISO 1940-1:2003", ["IEC 60034-5", "ISO 1940-1:2003"]),
            ("No standards mentioned here", []),
            ("Case insensitive iec 60034-5", ["iec 60034-5"]),
        ]
        
        for text, expected in test_cases:
            with self.subTest(text=text):
                result = collect_references(text)
                self.assertEqual(result, expected)

    def test_guess_category(self):
        # Test cases from the plan and additional coverage
        test_cases = [
            # Electrical
            (["Electrical requirements"], "voltage limits", "electrical"),
            ([], "insulation breakdown voltage", "electrical"),
            ([], "stator winding resistance", "electrical"),
            
            # Mechanical  
            (["Mechanical"], "vibration levels", "mechanical"),
            ([], "shaft deflection limits", "mechanical"),
            ([], "bearing temperature", "mechanical"),
            
            # Control
            ([], "encoder resolution", "control"),
            ([], "sensor monitoring system", "control"),
            ([], "control system feedback", "control"),
            
            # Environmental
            ([], "IP54 enclosure protection", "environmental"),
            ([], "operating temperature range", "environmental"),
            ([], "humidity protection", "environmental"),
            
            # Safety
            ([], "emergency stop requirements", "safety"),
            ([], "safety interlock system", "safety"),
            
            # No clear category
            ([], "general documentation", None),
            ([], "unrelated text", None),
        ]
        
        for section_path, raw_text, expected in test_cases:
            with self.subTest(section_path=section_path, raw_text=raw_text):
                result = guess_category(section_path, raw_text)
                self.assertEqual(result, expected)

    def test_make_evidence_query(self):
        """Test evidence query generation."""
        # Test with references and numeric criteria
        subject = "generator"
        canonical = "Enclosure protection shall be at least IP54 according to IEC 60034-5."
        refs = ["IEC 60034-5"]
        
        query = make_evidence_query(subject, canonical, refs)
        
        # Check that query contains essential components
        self.assertIn("generator", query.lower())
        self.assertIn("protection", query.lower())
        self.assertIn("enclosure", query.lower())
        self.assertIn("IEC 60034-5", query)
        
        # Test with multiple references (should limit to 2)
        refs_many = ["IEC 60034-5", "ISO 12345", "DIN 67890", "UL 9999"]
        query_many = make_evidence_query(subject, canonical, refs_many)
        
        # Should contain at most 2 references
        ref_count = sum(1 for ref in refs_many if ref in query_many)
        self.assertLessEqual(ref_count, 2)
        
        # Test with numeric criteria
        canonical_numeric = "Vibration shall be <= 2.5 mm/s during operation."
        query_numeric = make_evidence_query("bearing", canonical_numeric, [])
        
        self.assertIn("bearing", query_numeric.lower())
        self.assertIn("vibration", query_numeric.lower())
        # Should include numeric constraint somehow
        self.assertTrue(any(char.isdigit() for char in query_numeric))
        
        # Test with empty canonical (edge case)
        query_empty = make_evidence_query("generator", "", [])
        self.assertIn("generator", query_empty.lower())
        self.assertIn("requirement", query_empty.lower())
        
        # Test query length constraint
        long_canonical = "This is a very long requirement statement with many words that should be truncated to keep the query concise and focused on the most important terms for evidence matching."
        query_long = make_evidence_query("system", long_canonical, ["REF1", "REF2"])
        self.assertLessEqual(len(query_long), 125)  # Should be reasonably short
        
        # Test that subject is always included
        test_subjects = ["generator", "motor", "bearing", "encoder"]
        for subj in test_subjects:
            q = make_evidence_query(subj, "Some requirement text", [])
            self.assertIn(subj, q.lower())

if __name__ == '__main__':
    unittest.main()
