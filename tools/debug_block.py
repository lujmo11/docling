import re, sys, os
sys.path.append(os.getcwd())
from pdfminer.high_level import extract_text
from statement_extractor import ID_LINE_RE

def norm(s: str) -> str:
    return s.replace('\u00a0',' ')

text = extract_text('statement/Egencia faktura_DC_2843513_202508012306.pdf')
lines = [norm(l) for l in text.splitlines()]
blocks = []
cur = []
for raw in lines:
    s = raw.strip()
    if not s:
        continue
    if ID_LINE_RE.match(s):
        if cur:
            blocks.append(cur)
        cur = [raw]
    elif cur:
        cur.append(raw)
if cur:
    blocks.append(cur)
for bi,b in enumerate(blocks):
    if 'DKSC140289938' in b[0]:
        print('BLOCK HEADER:', b[0])
        for i,l in enumerate(b):
            print(f"{i:02d}: {l!r}")
        print('--- following next 12 global lines after block end ---')
        # show global context after last line of this block
        last_line = b[-1]
        # find index in original lines list
        idx_global = lines.index(b[-1])
        for j in range(idx_global+1, min(len(lines), idx_global+15)):
            print(f"G+{j-idx_global:02d}: {lines[j]!r}")
        break
