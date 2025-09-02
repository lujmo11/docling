import unittest
import tempfile
import json
from pathlib import Path

from models import Requirement, AcceptanceCriterion
from writers import write_requirements_jsonl, write_requirements_csv

class TestRequirementWriters(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_path = Path(self.test_dir.name)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_write_jsonl_and_csv(self):
        """Test writing a standard list of requirements with expanded schema."""
        requirements = [
            Requirement(
                requirement_uid="RS:#045.0",
                doc_meta={"document_id": "RS.docx", "title": "RS"},
                section_path=["Electrical requirements", "Enclosure protection"],
                source_anchor={"type": "text", "ref": "#045.0"},
                normative_strength="MUST",
                canonical_statement="The generator shall be IP54 or higher.",
                requirement_raw="Enclosure protection shall be at least IP54.",
                acceptance_criteria=[
                    AcceptanceCriterion(id="AC-1", text="IP54 or higher", comparator=">=", value=54.0, unit=None, dimension="IP_code"),
                ],
                verification_method="Test",
                references=["IEC 60034-5"],
                subject="generator",
                category="electrical",
                tags=["IP54"],
                evidence_query="generator enclosure IP54 IEC 60034-5",
                conflicts=[],
                dependencies=[],
                page_range=None,
                parent_id=None,
                confidence=0.95,
            ),
            Requirement(
                requirement_uid="RS:#066.0",
                doc_meta={"document_id": "RS.docx", "title": "RS"},
                section_path=["Thermal"],
                source_anchor={"type": "text", "ref": "#066.0"},
                normative_strength="MUST",
                canonical_statement="The generator shall limit bearing temperature to 90 degC.",
                requirement_raw="Bearing temperature limit 90 °C.",
                acceptance_criteria=[
                    AcceptanceCriterion(id="AC-2", text="90 °C", comparator="=", value=90.0, unit="degC", dimension=None),
                ],
                verification_method="Analysis",
                references=[],
                subject="generator",
                category="mechanical",
                tags=["temperature"],
                evidence_query="generator bearing temperature 90 C",
                conflicts=[],
                dependencies=[],
                page_range=None,
                parent_id=None,
                confidence=0.9,
            ),
        ]

        # Test JSONL
        jsonl_path = self.test_path / "reqs.jsonl"
        write_requirements_jsonl(requirements, jsonl_path)
        
        with jsonl_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 2)
            data1 = json.loads(lines[0])
            self.assertEqual(data1['requirement_uid'], 'RS:#045.0')
            self.assertEqual(data1['acceptance_criteria'][0]['text'], 'IP54 or higher')
            data2 = json.loads(lines[1])
            self.assertEqual(data2['requirement_uid'], 'RS:#066.0')

        # Test CSV
        csv_path = self.test_path / "reqs.csv"
        write_requirements_csv(requirements, csv_path)
        
        with csv_path.open("r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn('requirement_uid,section_path,normative_strength,canonical_statement,requirement_raw', content.splitlines()[0])
            self.assertIn('RS:#045.0', content)

    def test_empty_list(self):
        """Test that writing an empty list produces empty files (with headers for CSV)."""
        requirements = []

        # Test JSONL
        jsonl_path = self.test_path / "empty.jsonl"
        write_requirements_jsonl(requirements, jsonl_path)
        self.assertEqual(jsonl_path.read_text(), "")

        # Test CSV
        csv_path = self.test_path / "empty.csv"
        write_requirements_csv(requirements, csv_path)
        header = csv_path.read_text(encoding='utf-8').strip()
        self.assertTrue(header.startswith("requirement_uid,section_path,normative_strength"))

if __name__ == '__main__':
    unittest.main()
