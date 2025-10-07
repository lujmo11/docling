import sys, re, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from statement_extractor import parse_statement_pdf  # noqa: E402

try:
    from pdfminer.high_level import extract_text
except Exception:
    print("pdfminer.six required", file=sys.stderr)
    sys.exit(1)

TARGET_IDS = [
    "DKSC140289878",
    "DKSC140289887",
    "DKSC140289889",
    "DKSC140289936",
    "DKSC140289938",
    "DKSC140289943",
    "DKSI144013930",
]

amount_re = re.compile(r"-?\d{1,3}(?:\d{3})*(?:[.,]\d{2})$|-?\d+[.,]\d{2}$")

def main(pdf_path: str):
    text = extract_text(pdf_path)
    lines = text.splitlines()
    id_set = set(TARGET_IDS)
    for idx, line in enumerate(lines):
        for tid in TARGET_IDS:
            if tid in line:
                # show context window
                start = max(0, idx-3)
                end = min(len(lines), idx+6)
                print("==== ID", tid, "lines", start, "-", end)
                for j in range(start, end):
                    mark = '>' if j == idx else ' '
                    amt = ''
                    if amount_re.search(lines[j].strip()):
                        amt = '  [AMOUNT?]'
                    print(f"{mark}{j:05d}: {lines[j]!r}{amt}")
                print()
    # Quick scan: amounts that appear on same line as header
    inline_candidates = {}
    for tid in TARGET_IDS:
        for idx, line in enumerate(lines):
            if line.strip().startswith(tid):
                parts = line.strip().split()
                last = parts[-1]
                if amount_re.match(last):
                    inline_candidates[tid] = last
                break
    print("Inline header candidates:", inline_candidates)

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python tools/debug_amounts.py <statement.pdf>")
        sys.exit(1)
    main(sys.argv[1])