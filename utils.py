import re
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
    # Pattern groups: comparator? value unit?
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
        
        # Default comparator is '=' if not specified
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
        """
        Updates the heading stack based on the current block and returns the current section path.
        """
        if block.get("type") == "heading":
            level = block.get("level", 1)
            text = block.get("text", "").strip()

            if text:
                # Pop from stack until we find a level less than the current one
                while self._stack and self._stack[-1][0] >= level:
                    self._stack.pop()
                
                self._stack.append((level, text))

        return [text for level, text in self._stack]

def canonicalize(subject: str, raw: str) -> str:
    """
    Convert raw text into an unambiguous checkable statement.
    
    Args:
        subject: The subject of the requirement (e.g., "generator")
        raw: The raw requirement text
        
    Returns:
        Canonicalized statement suitable for LLM matching
    """
    raw = raw.strip()
    if not raw:
        return f"The {subject} shall comply with unspecified requirements."
    
    # Check if raw already starts with the subject (case-insensitive)
    subject_lower = subject.lower()
    raw_lower = raw.lower()
    
    # If it already starts with "the [subject]" or just "[subject]", leave it as-is
    if (raw_lower.startswith(f"the {subject_lower}") or 
        raw_lower.startswith(f"{subject_lower} ")):
        return raw
    
    # If it starts with "the" but not "the [subject]", leave it as-is
    if raw_lower.startswith("the "):
        return raw
        
    # If it already contains "shall" or "must", it's likely already a proper requirement statement
    if " shall " in raw_lower or " must " in raw_lower:
        return raw
    
    # Otherwise, prepend "The {subject} shall " and lowercase the first char of raw
    first_char = raw[0].lower() if raw else ""
    rest = raw[1:] if len(raw) > 1 else ""
    
    return f"The {subject} shall {first_char}{rest}"

def infer_subject(section_path: List[str], raw_text: str, default: str = "generator") -> str:
    """
    Simple subject inference with fallback to default.
    
    Args:
        section_path: Current document section path
        raw_text: Raw requirement text
        default: Default subject to use
        
    Returns:
        Inferred subject string
    """
    # For now, just return the default - this can be enhanced later
    # with keyword-based inference from section_path and raw_text
    return default

def collect_references(text: str) -> List[str]:
    """
    Collect standard references (IEC/ISO/DIN/UL/CSA) from text.
    
    Args:
        text: Text to search for references
        
    Returns:
        List of found reference strings
    """
    references = []
    
    # Pattern for IEC standards: IEC followed by numbers, optionally with part numbers and years
    iec_pattern = r'\bIEC\s+\d+(?:-\d+)*(?::\d{4})?\b'
    references.extend(re.findall(iec_pattern, text, re.IGNORECASE))
    
    # Pattern for ISO standards: ISO followed by numbers, optionally with part numbers and years  
    iso_pattern = r'\bISO\s+\d+(?:-\d+)*(?::\d{4})?\b'
    references.extend(re.findall(iso_pattern, text, re.IGNORECASE))
    
    # Pattern for DIN standards: DIN followed by numbers
    din_pattern = r'\bDIN\s+\d+(?:-\d+)*\b'
    references.extend(re.findall(din_pattern, text, re.IGNORECASE))
    
    # Pattern for UL standards: UL followed by numbers, optionally with part numbers
    ul_pattern = r'\bUL\s+\d+(?:-\d+)*\b'
    references.extend(re.findall(ul_pattern, text, re.IGNORECASE))
    
    # Pattern for CSA standards: CSA followed by identifier
    csa_pattern = r'\bCSA\s+[A-Z]+-\d+(?:-\d+)*\b'
    references.extend(re.findall(csa_pattern, text, re.IGNORECASE))
    
    # Remove duplicates while preserving order
    seen = set()
    unique_refs = []
    for ref in references:
        if ref not in seen:
            seen.add(ref)
            unique_refs.append(ref)
    
    return unique_refs

def guess_category(section_path: List[str], raw_text: str) -> Optional[str]:
    """
    Guess the category of a requirement based on section path and content.
    
    Args:
        section_path: Current document section path
        raw_text: Raw requirement text
        
    Returns:
        Guessed category string or None if no clear category
    """
    # Combine section path and raw text for keyword matching
    combined_text = " ".join(section_path + [raw_text]).lower()
    
    # Environmental category keywords (check first due to specificity)
    environmental_keywords = [
        "ip54", "ip55", "ip56", "enclosure protection", "ingress protection",
        "humidity", "altitude", "environmental", "climate", "weather", 
        "corrosion", "coating", "sealing", "ingress", "operating temperature",
        "ambient temperature", "storage temperature"
    ]
    
    # Electrical category keywords
    electrical_keywords = [
        "voltage", "current", "power", "electrical", "insulation", "conductor", 
        "winding", "stator", "rotor", "terminal", "connection", "earthing", 
        "grounding", "isolation", "dielectric", "breakdown", "surge", "overvoltage"
    ]
    
    # Mechanical category keywords  
    mechanical_keywords = [
        "vibration", "mechanical", "shaft", "bearing", "housing", "mounting",
        "coupling", "alignment", "balancing", "deflection", "forces", "torque",
        "speed", "rpm", "rotation", "clearance", "tolerance", "dimension"
    ]
    
    # Control/instrumentation category keywords (more specific patterns)
    control_keywords = [
        "encoder", "sensor monitoring", "control system", "feedback", "signal",
        "instrumentation", "measurement", "alarm", "trip", "pt100", 
        "thermocouple", "pressure sensor", "flow sensor"
    ]
    
    # Safety category keywords
    safety_keywords = [
        "safety", "emergency", "stop", "shutdown", "interlock", 
        "guard", "barrier", "hazard", "risk", "fail-safe", "redundancy"
    ]
    
    # Check for matches in order of specificity (environmental first)
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
