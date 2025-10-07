from statement_extractor import parse_statement_pdf
rows = parse_statement_pdf('statement/Egencia faktura_DC_2843513_202508012306.pdf')
print('Total rows:', len(rows))
for r in rows[:10]:
    print('ID:', r['ID'])
    for k,v in r.items():
        if k!='ID' and v:
            print('  ', k, ':', v)
    print('---')
