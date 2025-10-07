from __future__ import annotations
from typing import List
from models import Requirement
from .strategy_base import BaseExtractionStrategy
from extractors import extract_from_tps_tables

class TPSExtractionStrategy(BaseExtractionStrategy):
    def extract_requirements(self) -> List[Requirement]:
        self.doc_meta.setdefault("document_type", "TPS")
        return extract_from_tps_tables(self.tables_data, self.doc_meta)
