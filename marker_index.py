import re
import csv, io
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Iterable

RS_MARKER_RE = re.compile(r'#\s*(\d+)\s*\.\s*(\d+)')
# TPS style hierarchical IDs like 4.1.2.7 or 5.3 etc (at least one dot, starts digit)
TPS_ID_RE = re.compile(r'\b(\d+(?:\.\d+){1,5})\b')

@dataclass
class Marker:
    uid: str                 # Canonical id string (e.g., '#045.0' or '4.1.2.7')
    kind: str                # 'RS' | 'TPS' | 'UNKNOWN'
    raw: str                 # Raw matched text
    container_type: str      # 'paragraph' | 'table_cell' | 'table_row'
    container_index: int     # index of paragraph block or table row number (0-based)
    table_id: Optional[str] = None
    cell_coords: Optional[tuple] = None  # (row, col) if available
    start: Optional[int] = None          # char offset in container text
    end: Optional[int] = None            # char end offset

class MarkerIndex:
    """Unified discovery of requirement-like markers across text blocks and tables.

    This pass is intentionally lightweight: it records the existence and rough
    location of markers without constructing Requirement objects. Later stages
    will segment multi-marker containers and enrich content.
    """
    def __init__(self):
        self.markers: List[Marker] = []
        self._seen = set()  # avoid duplicate (kind, uid, container_type, container_index, table_id)

    # --- Block / Paragraph scanning -------------------------------------------------
    def scan_blocks(self, doc_json: Dict[str, Any]):
        blocks = (doc_json or {}).get('blocks', [])
        for i, blk in enumerate(blocks):
            if not isinstance(blk, dict):
                continue
            if blk.get('type') != 'paragraph':
                continue
            text = blk.get('text', '') or ''
            # RS markers
            for m in RS_MARKER_RE.finditer(text):
                whole = m.group(0)
                a, b = m.group(1), m.group(2)
                uid = f"#{int(a):03d}.{int(b)}"  # zero-pad first part to 3 for stability (#045.0)
                key = ('RS', uid, 'paragraph', i, None, m.start())
                if key in self._seen:
                    continue
                self._seen.add(key)
                self.markers.append(Marker(uid=uid, kind='RS', raw=whole, container_type='paragraph', container_index=i, start=m.start(), end=m.end()))
            # TPS style numeric IDs (only if not preceded by '#')
            for m in TPS_ID_RE.finditer(text):
                # Skip if pattern is part of RS (preceded by '#')
                if m.start() > 0 and text[m.start()-1] == '#':
                    continue
                uid = m.group(1)
                key = ('TPS', uid, 'paragraph', i, None, m.start())
                if key in self._seen:
                    continue
                self._seen.add(key)
                self.markers.append(Marker(uid=uid, kind='TPS', raw=m.group(0), container_type='paragraph', container_index=i, start=m.start(), end=m.end()))

    # --- Table scanning -------------------------------------------------------------
    def scan_tables(self, tables_data: Dict[str, Any]):
        for table_id, tinfo in (tables_data or {}).items():
            csv_data = (tinfo or {}).get('csv_data') or ''
            if not csv_data:
                continue
            # Parse CSV with python csv module to respect quoted multiline cells
            try:
                reader = csv.reader(io.StringIO(csv_data))
                rows = list(reader)
            except Exception:
                rows = [r.split(',') for r in csv_data.splitlines()]
            for r_index, row in enumerate(rows):
                cells = [ (c or '').strip() for c in row ]
                for c_index, cell in enumerate(cells):
                    # RS markers
                    for m in RS_MARKER_RE.finditer(cell):
                        a, b = m.group(1), m.group(2)
                        uid = f"#{int(a):03d}.{int(b)}"
                        key = ('RS', uid, 'table_cell', r_index, table_id, c_index)
                        if key in self._seen:
                            continue
                        self._seen.add(key)
                        self.markers.append(Marker(uid=uid, kind='RS', raw=m.group(0), container_type='table_cell', container_index=r_index, table_id=table_id, cell_coords=(r_index, c_index), start=m.start(), end=m.end()))
                    # TPS style IDs (avoid those with '#')
                    for m in TPS_ID_RE.finditer(cell):
                        uid = m.group(1)
                        if '#' in cell[max(0,m.start()-2):m.start()+1]:  # quick guard
                            continue
                        key = ('TPS', uid, 'table_cell', r_index, table_id, c_index)
                        if key in self._seen:
                            continue
                        self._seen.add(key)
                        self.markers.append(Marker(uid=uid, kind='TPS', raw=m.group(0), container_type='table_cell', container_index=r_index, table_id=table_id, cell_coords=(r_index, c_index), start=m.start(), end=m.end()))

    # --- Utilities ------------------------------------------------------------------
    def rs_count(self) -> int:
        return sum(1 for m in self.markers if m.kind == 'RS')

    def tps_count(self) -> int:
        return sum(1 for m in self.markers if m.kind == 'TPS')

    def by_container(self):
        buckets: Dict[tuple, List[Marker]] = {}
        for m in self.markers:
            key = (m.container_type, m.container_index, m.table_id)
            buckets.setdefault(key, []).append(m)
        return buckets

    def sort(self):
        self.markers.sort(key=lambda m: (m.container_type, m.table_id or '', m.container_index, m.start or 0))
        return self


def build_marker_index(doc_json: Dict[str, Any], tables_data: Dict[str, Any]) -> MarkerIndex:
    idx = MarkerIndex()
    idx.scan_blocks(doc_json)
    idx.scan_tables(tables_data)
    idx.sort()
    return idx
