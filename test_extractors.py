import unittest
from extractors import extract_from_rs_text
from extractors import extract_from_tps_tables

class TestExtractors(unittest.TestCase):

    def test_rs_simple_block(self):
        doc_json = {
            "blocks": [
                {"type": "heading", "level": 1, "text": "Electrical requirements"},
                {"type": "paragraph", "text": "#045.0 Enclosure protection shall be at least IP54 according to IEC 60034-5. Verification method: Test."}
            ]
        }
        doc_meta = {"document_id": "RS.docx", "title": "RS"}
        
        reqs = extract_from_rs_text(doc_json, doc_meta)
        
        self.assertEqual(len(reqs), 1)
        req = reqs[0]
        
        self.assertEqual(req.requirement_uid, "RS:#045.0")
        self.assertEqual(req.normative_strength, "MUST")
        # self.assertIn("IEC 60034-5", req.references) # Will be implemented in a future chunk
        self.assertEqual(req.verification_method, "Test")
        self.assertEqual(req.section_path, ["Electrical requirements"])
        self.assertTrue(req.requirement_raw.startswith("Enclosure protection shall be at least IP54"))

    def test_multiple_markers_in_paragraph(self):
        doc_json = {
            "blocks": [
                {"type": "paragraph", "text": "#001.0 First req. #002.0 Second req, must be good."}
            ]
        }
        doc_meta = {"document_id": "RS.docx", "title": "RS"}
        
        reqs = extract_from_rs_text(doc_json, doc_meta)
        
        self.assertEqual(len(reqs), 2)
        self.assertEqual(reqs[0].requirement_uid, "RS:#001.0")
        self.assertEqual(reqs[0].requirement_raw, "First req.")
        self.assertEqual(reqs[1].requirement_uid, "RS:#002.0")
        self.assertEqual(reqs[1].normative_strength, "MUST")
        self.assertEqual(reqs[1].requirement_raw, "Second req, must be good.")

    def test_tps_rows(self):
        tables_data = {
            "table_1": {
                "csv_data": "ID,Subject,Requirement,Unit,LSL,Target,USL\n4.1.2.7,generator,Maximum allowed RMS vibration level,mm/s,,,1.8\n4.1.3.11,generator,Rated nominal stator voltage,V RMS,,780,\n"
            }
        }
        doc_meta = {"document_id": "TPS.docx", "title": "TPS"}

        reqs = extract_from_tps_tables(tables_data, doc_meta)

        # USL constraint row
        vr = [r for r in reqs if r.requirement_uid.startswith("TPS:4.1.2.7")]
        self.assertTrue(any(any(c.comparator == "<=" and c.value == 1.8 and c.unit == "mm_per_s" for c in r.acceptance_criteria) for r in vr))

        # Target voltage row
        rr = [r for r in reqs if r.requirement_uid.startswith("TPS:4.1.3.11")]
        self.assertTrue(any(any(c.comparator == "=" and c.value == 780.0 and c.unit == "V_rms" for c in r.acceptance_criteria) for r in rr))

    def test_tps_two_column_with_ids(self):
        # Simulate a 2-column table like in the real doc: text + RS-style ID
        csv = "Text,ID\n\"Winding temperature limit The generator must be monitored. Verification method: Review.\",#065.0\n\"Bearing temperature limit Bearings temperature warning limit: 90°C. Verification method: Review.\",#066.0\n"
        tables_data = {"table_99": {"csv_data": csv}}
        doc_meta = {"document_id": "TPS.docx", "title": "TPS"}

        reqs = extract_from_tps_tables(tables_data, doc_meta)
        ids = {r.requirement_uid for r in reqs}
        self.assertIn("TPS:065.0", ids)
        self.assertIn("TPS:066.0", ids)
        # Verification method parsed
        vm = {r.requirement_uid: r.verification_method for r in reqs}
        self.assertEqual(vm.get("TPS:065.0"), "Review")
        self.assertEqual(vm.get("TPS:066.0"), "Review")
        # Numeric 90°C extracted
        ac_066 = [r for r in reqs if r.requirement_uid == "TPS:066.0"][0].acceptance_criteria
        self.assertTrue(any(c.value == 90.0 and c.unit == "degC" for c in ac_066))

if __name__ == '__main__':
    unittest.main()
