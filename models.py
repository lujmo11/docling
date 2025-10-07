import dataclasses
from typing import List, Optional

@dataclasses.dataclass
class AcceptanceCriterion:
    """Represents a single acceptance criterion for a requirement."""
    id: str
    text: str
    comparator: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    dimension: Optional[str] = None
    
from typing import List, Optional, Dict, Any

@dataclasses.dataclass
class Requirement:
    """Represents a single requirement, with optional acceptance criteria."""
    requirement_uid: str
    doc_meta: Dict[str, Any]
    section_path: List[str]
    source_anchor: Dict[str, Any]
    normative_strength: Optional[str]
    canonical_statement: str
    requirement_raw: str
    acceptance_criteria: List[AcceptanceCriterion]
    verification_method: Optional[str]
    references: List[str]
    subject: str
    category: Optional[str]
    tags: List[str]
    evidence_query: str
    conflicts: List[str] = dataclasses.field(default_factory=list)
    dependencies: List[str] = dataclasses.field(default_factory=list)
    page_range: Optional[List[int]] = None
    parent_id: Optional[str] = None
    confidence: Optional[float] = None
    id: Optional[str] = None
    text: Optional[str] = None
    source: Optional[str] = None
    # New enriched provenance / structure fields (marker-first refactor)
    source_type: Optional[str] = None              # e.g. 'paragraph', 'table_cell', 'table_row'
    source_location: Optional[Dict[str, Any]] = None  # arbitrary location payload (table id, row/col indices, page)
    is_stub: bool = False                          # true if created from marker only (no extracted text yet)
    raw_section_header: Optional[str] = None        # nearest raw heading text captured at extraction time
