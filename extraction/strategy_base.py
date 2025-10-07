from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Type, Optional

from models import Requirement

@dataclass
class DocumentProfile:
    doc_type: str  # 'RS' | 'TPS' | 'UNKNOWN'
    confidence: float
    features: Dict[str, Any]


class BaseExtractionStrategy(ABC):
    def __init__(self, profile: DocumentProfile, doc_json: Dict[str, Any], tables_data: Dict[str, Any], doc_meta: Dict[str, Any]):
        self.profile = profile
        self.doc_json = doc_json
        self.tables_data = tables_data
        self.doc_meta = doc_meta

    def prepare(self) -> None:
        """Optional pre-processing step."""
        return None

    @abstractmethod
    def extract_requirements(self) -> List[Requirement]:
        ...

    def postprocess(self, requirements: List[Requirement]) -> List[Requirement]:
        return requirements

    @property
    def name(self) -> str:
        return self.__class__.__name__


class ExtractionStrategyRegistry:
    _registry: Dict[str, Type[BaseExtractionStrategy]] = {}

    @classmethod
    def register(cls, key: str, strategy_cls: Type[BaseExtractionStrategy]):
        cls._registry[key.upper()] = strategy_cls

    @classmethod
    def get(cls, key: str) -> Optional[Type[BaseExtractionStrategy]]:
        return cls._registry.get(key.upper())

    @classmethod
    def available_types(cls) -> List[str]:
        return list(cls._registry.keys())
