from __future__ import annotations
from typing import List
from models import Requirement
from .strategy_base import BaseExtractionStrategy
from extractors import extract_from_rs_text

class RSExtractionStrategy(BaseExtractionStrategy):
    def extract_requirements(self) -> List[Requirement]:
        # Ensure doc_meta carries type
        self.doc_meta.setdefault("document_type", "RS")
        return extract_from_rs_text(self.doc_json, self.doc_meta)
