from __future__ import annotations
from typing import List
import re
from models import Requirement, AcceptanceCriterion
from .strategy_base import BaseExtractionStrategy

class FallbackStrategy(BaseExtractionStrategy):
    def extract_requirements(self) -> List[Requirement]:
        # Extremely conservative: scan markdown-like reconstructed text in doc_json for #NNN.
        self.doc_meta.setdefault("document_type", "UNKNOWN")
        reqs: List[Requirement] = []
        blocks = self.doc_json.get("blocks", [])
        for b in blocks:
            if not isinstance(b, dict):
                continue
            txt = (b.get("text") or "").strip()
            if not txt:
                continue
            for m in re.finditer(r'#(\d+)\.(\d+)', txt):
                num = f"{int(m.group(1))}.{m.group(2)}"
                raw = txt[m.end():].strip()
                if not raw:
                    continue
                reqs.append(Requirement(
                    requirement_uid=f"GEN:#{num}",
                    doc_meta=self.doc_meta,
                    section_path=[],
                    source_anchor={"type": "text", "ref": f"#{num}"},
                    normative_strength=None,
                    canonical_statement=raw,
                    requirement_raw=raw,
                    acceptance_criteria=[],
                    verification_method=None,
                    references=[],
                    subject="generic",
                    category=None,
                    tags=[],
                    evidence_query=None,
                ))
        return reqs
