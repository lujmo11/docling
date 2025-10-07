from docx import Document
import re
paths=['A012-5599 TPS 4.8 MW Air Cooler IG GEN V05 - CAC.docx','A012-5599 TPS 4.8 MW Air Cooler IG GEN V05 - CAC_normalized.docx']
for path in paths:
    print('---', path)
    try:
        d=Document(path)
    except Exception as e:
        print('load failed', e);continue
    hits=[]
    for ti,t in enumerate(d.tables):
        for ri,r in enumerate(t.rows):
            for ci,c in enumerate(r.cells):
                txt=c.text.strip()
                if re.search(r'\\b4\\.1\\.1\\.\\d+\\b', txt):
                    hits.append((ti,ri,ci, txt[:120].replace('\n',' ')))
    print('hits', len(hits))
    for h in hits[:10]:
        print(h)
