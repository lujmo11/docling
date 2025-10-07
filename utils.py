import re
from pathlib import Path
from typing import List, Optional
from models import AcceptanceCriterion

NORM_UNITS_MAP = {
    "°C": "degC",
    "C": "degC",
    "kV/µs": "kV/us",
    "kV/μs": "kV/us",
    "µs": "us",
    "μs": "us",
    "V RMS": "V_rms",
    "V RMS)": "V_rms",
    "V RMS.": "V_rms",
    "V RMS,": "V_rms",
    "V RMS;": "V_rms",
    "V RMS/": "V_rms",
    "V RMS]": "V_rms",
    "kV RMS": "kV_rms",
    "V": "V",
    "kV": "kV",
    "kHz": "kHz",
    "Hz": "Hz",
    "rpm": "rpm",
    "mm/s": "mm_per_s",
    "m/s2": "m_per_s2",
    "m/s²": "m_per_s2",
    "mm": "mm",
    "bar": "bar",
    "%": "percent",
    "dB(A)": "dB(A)"
}

COMPARATOR_MAP = {
    "<=": "<=",
    "≤": "<=",
    "<": "<",
    ">=": ">=",
    "≥": ">=",
    ">": ">",
    "=": "=",
    "==": "=",
}

def normalize_unit(u: str) -> str:
    """Normalizes a unit string using the NORM_UNITS_MAP."""
    u = (u or "").strip()
    return NORM_UNITS_MAP.get(u, u)

def extract_numbers_with_units(text: str) -> List[AcceptanceCriterion]:
    """Extracts numeric values with units from a string."""
    pattern = re.compile(
        r'(?P<cmp>≤|>=|≥|<=|<|>|=|==)?\s*'
        r'(?P<val>\d+(?:\.\d+)?)\s*'
        r'(?P<unit>kV/µs|kV/μs|kV/us|kV RMS|V RMS|°C|C|V|kV|kHz|Hz|rpm|mm/s|m/s²|m/s2|mm|bar|%|dB\(A\))?'
    )
    crits = []
    for m in pattern.finditer(text):
        cmp_raw = m.group("cmp")
        val = float(m.group("val"))
        unit_raw = m.group("unit")
        cmp_ = COMPARATOR_MAP.get(cmp_raw, "=") if cmp_raw else "="
        unit_norm = normalize_unit(unit_raw) if unit_raw else None
        crits.append(AcceptanceCriterion(id=f"numeric-{val}{unit_norm or ''}", text=m.group(0), comparator=cmp_, value=val, unit=unit_norm))
    return crits

def find_normative_strength(text: str) -> Optional[str]:
    """Finds the normative strength of a requirement statement."""
    text_lower = text.lower()
    if "shall" in text_lower or "must" in text_lower:
        return "MUST"
    if "should" in text_lower:
        return "SHOULD"
    if "may" in text_lower:
        return "MAY"
    return None

class SectionTracker:
    """Maintains a stack of section headings to track the current document path."""
    def __init__(self):
        self._stack: List[tuple[int, str]] = []

    def update_and_get_path(self, block: dict) -> List[str]:
        if block.get("type") == "heading":
            level = block.get("level", 1)
            text = block.get("text", "").strip()
            if text:
                while self._stack and self._stack[-1][0] >= level:
                    self._stack.pop()
                self._stack.append((level, text))
        return [text for level, text in self._stack]

def canonicalize(subject: str, raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return f"The {subject} shall comply with unspecified requirements."
    subject_lower = subject.lower()
    raw_lower = raw.lower()
    if (raw_lower.startswith(f"the {subject_lower}") or 
        raw_lower.startswith(f"{subject_lower} ")):
        return raw
    if raw_lower.startswith("the "):
        return raw
    if " shall " in raw_lower or " must " in raw_lower:
        return raw
    first_char = raw[0].lower() if raw else ""
    rest = raw[1:] if len(raw) > 1 else ""
    return f"The {subject} shall {first_char}{rest}"

def infer_subject(section_path: List[str], raw_text: str, default: str = "generator") -> str:
    return default

def collect_references(text: str) -> List[str]:
    references = []
    iec_pattern = r'\bIEC\s+\d+(?:-\d+)*(?::\d{4})?\b'
    references.extend(re.findall(iec_pattern, text, re.IGNORECASE))
    iso_pattern = r'\bISO\s+\d+(?:-\d+)*(?::\d{4})?\b'
    references.extend(re.findall(iso_pattern, text, re.IGNORECASE))
    din_pattern = r'\bDIN\s+\d+(?:-\d+)*\b'
    references.extend(re.findall(din_pattern, text, re.IGNORECASE))
    ul_pattern = r'\bUL\s+\d+(?:-\d+)*\b'
    references.extend(re.findall(ul_pattern, text, re.IGNORECASE))
    csa_pattern = r'\bCSA\s+[A-Z]+-\d+(?:-\d+)*\b'
    references.extend(re.findall(csa_pattern, text, re.IGNORECASE))
    seen = set()
    unique_refs = []
    for ref in references:
        if ref not in seen:
            seen.add(ref)
            unique_refs.append(ref)
    return unique_refs

def guess_category(section_path: List[str], raw_text: str) -> Optional[str]:
    combined_text = " ".join(section_path + [raw_text]).lower()
    environmental_keywords = [
        "ip54", "ip55", "ip56", "enclosure protection", "ingress protection",
        "humidity", "altitude", "environmental", "climate", "weather", 
        "corrosion", "coating", "sealing", "ingress", "operating temperature",
        "ambient temperature", "storage temperature"
    ]
    electrical_keywords = [
        "voltage", "current", "power", "electrical", "insulation", "conductor", 
        "winding", "stator", "rotor", "terminal", "connection", "earthing", 
        "grounding", "isolation", "dielectric", "breakdown", "surge", "overvoltage"
    ]
    mechanical_keywords = [
        "vibration", "mechanical", "shaft", "bearing", "housing", "mounting",
        "coupling", "alignment", "balancing", "deflection", "forces", "torque",
        "speed", "rpm", "rotation", "clearance", "tolerance", "dimension"
    ]
    control_keywords = [
        "encoder", "sensor monitoring", "control system", "feedback", "signal",
        "instrumentation", "measurement", "alarm", "trip", "pt100", 
        "thermocouple", "pressure sensor", "flow sensor"
    ]
    safety_keywords = [
        "safety", "emergency", "stop", "shutdown", "interlock", 
        "guard", "barrier", "hazard", "risk", "fail-safe", "redundancy"
    ]
    if any(keyword in combined_text for keyword in environmental_keywords):
        return "environmental"
    elif any(keyword in combined_text for keyword in electrical_keywords):
        return "electrical"
    elif any(keyword in combined_text for keyword in mechanical_keywords):
        return "mechanical"
    elif any(keyword in combined_text for keyword in control_keywords):
        return "control"
    elif any(keyword in combined_text for keyword in safety_keywords):
        return "safety"
    return None

def make_evidence_query(subject: str, canonical: str, refs: List[str]) -> str:
    if not canonical.strip():
        return f"{subject} requirement"
    stopwords = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", 
        "of", "with", "by", "shall", "must", "should", "may", "will", "be", 
        "is", "are", "was", "were", "have", "has", "had", "do", "does", "did"
    }
    tokens = re.findall(r'\b\w+\b', canonical.lower())
    content_tokens = [t for t in tokens if t not in stopwords and len(t) > 2]
    scored_tokens = []
    for token in content_tokens:
        score = 0
        if re.match(r'\d+', token) or token in ["ip54", "ip55", "ip56", "kv", "rpm", "hz", "degc"]:
            score += 3
        if any(keyword in token for keyword in ["protection", "enclosure", "voltage", "current", 
                                               "vibration", "bearing", "stator", "rotor", "winding"]):
            score += 2
        if subject.lower() in token or token in subject.lower():
            score += 2
        score += 1
        scored_tokens.append((score, token))
    scored_tokens.sort(key=lambda x: (-x[0], x[1]))
    selected_tokens = [token for score, token in scored_tokens[:6]]
    numeric_criteria = extract_numbers_with_units(canonical)
    numeric_parts = []
    for criterion in numeric_criteria[:2]:
        comp = criterion.comparator
        val = criterion.value
        unit = criterion.unit or ""
        numeric_parts.append(f"{comp} {val} {unit}".strip())
    query_parts = [subject]
    query_parts.extend(selected_tokens[:4])
    query_parts.extend(numeric_parts)
    if refs:
        query_parts.extend(refs[:2])
    query = " ".join(query_parts)
    query = re.sub(r'\s+', ' ', query)
    query = query.strip()
    if len(query) > 120:
        safe_parts = [subject] + selected_tokens[:3]
        if refs:
            safe_parts.append(refs[0])
        query = " ".join(safe_parts)
    return query

# --- Centralized output directory utilities ---

def get_repo_root() -> Path:
    """Return repository root (directory containing this file).

    This is a simple heuristic sufficient for this project layout.
    """
    return Path(__file__).parent

def ensure_output_base() -> Path:
    """Ensure the central 'output' directory exists and return it.

    Used to aggregate all generated artifacts instead of scattering
    `*_output` folders in the repository root.
    """
    root = get_repo_root()
    out_base = root / 'output'
    out_base.mkdir(parents=True, exist_ok=True)
    return out_base

def build_output_subdir(base_name: str) -> Path:
    """Return a unique subdirectory inside central output for a document.

    Mirrors previous pattern of `<name>_output` while nesting under
    the root 'output' directory. If directory exists, add `_runN` suffix.
    """
    out_base = ensure_output_base()
    sanitized = re.sub(r'[\\/]+', '-', base_name).strip()
    candidate = out_base / f"{sanitized}_output"
    if not candidate.exists():
        return candidate
    suffix = 1
    while True:
        run_candidate = out_base / f"{sanitized}_output_run{suffix}"
        if not run_candidate.exists():
            return run_candidate
        suffix += 1
