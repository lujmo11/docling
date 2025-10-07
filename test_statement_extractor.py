import pytest

from statement_extractor import parse_statement_text, excel_preserve_numeric_string, enrich_amounts_from_text

SAMPLE_TEXT = """DKSC140289938 EGENCIA DK TAC-FLY LOT POLISH AIRLINES
MedarbejderID:
Navn på rejsende:
Afrejsedato:
Hjemrejsedato:
Rute:
Rutekoder:
Billetnummer:
Projektnummer:
Rejsebureau momsbeløb:

NA
MAJDA/MARIUSZ MR
2025-07-10
2025-07-10
CPHWAWWAWKTW
CPH;WAW;WAW;KTW;
0802748097709
18633
-74,25
IntercityHotel Berlin Airport
Courtyard by Marriott Gdynia W

DKSC999999999 EGENCIA DK TAC-HOTEL SOME HOTEL PROVIDER
MedarbejderID:
Navn på rejsende:
Afrejsedato:
Hjemrejsedato:
Rute:
Rutekoder:
Billetnummer:
Projektnummer:
Rejsebureau momsbeløb:

NA2
DOE/JOHN MR
2025-08-01
2025-08-05
CPHLHR
CPH;LHR;
0802000000000
P1234
-10,00
Idraettens Hus(Brondby)
Cornmill Hotel(Hull)
"""


def test_multiline_route_aggregation():
    rows = parse_statement_text(SAMPLE_TEXT)
    assert len(rows) == 2, rows
    r1, r2 = rows
    # Ensure hotel/location lines appended to Rute not separate records
    assert "IntercityHotel Berlin Airport" in r1['Rute']
    assert "Courtyard by Marriott Gdynia W" in r1['Rute']
    assert "Idraettens Hus(Brondby)" in r2['Rute']
    assert "Cornmill Hotel(Hull)" in r2['Rute']
    # Tax normalization (comma to dot)
    assert r1['Rejsebureau momsbeløb'] == '-74.25'
    assert r2['Rejsebureau momsbeløb'] == '-10.00'
    # Amounts now blank prior to external enrichment
    assert r1['Beløb DKK'] == ''
    assert r2['Beløb DKK'] == ''


def test_excel_preserve_helper():
    # Apostrophe mode
    assert excel_preserve_numeric_string('0742748087132', mode='apostrophe').startswith("'0742748087132")
    assert excel_preserve_numeric_string('1234567890', mode='apostrophe').startswith("'1234567890")
    # Formula mode
    assert excel_preserve_numeric_string('0742748087132', mode='formula').startswith('="0742748087132')
    # Already preserved
    assert excel_preserve_numeric_string("'0123", mode='apostrophe') == "'0123"
    # Short numeric without leading zero remains unchanged
    assert excel_preserve_numeric_string('12345', mode='apostrophe') == '12345'
    # Non-digit value unchanged
    assert excel_preserve_numeric_string('ABC123', mode='apostrophe') == 'ABC123'


def test_enrich_amounts_from_text():
    base_rows = [
        {"ID": "DKSC140289889 EGENCIA DK TAC-HOTEL Bastion Hotel Haarl", "Beløb DKK": ""},
        {"ID": "DKSC140289938 EGENCIA DK TAC-FLY LOT POLISH AIRLINES", "Beløb DKK": ""},
    ]
    amount_text = """DKSC140289889 EGENCIA DK TAC-HOTEL Bastion Hotel Haarl -919.00
DKSC140289938 EGENCIA DK TAC-FLY LOT POLISH AIRLINES -3151.25"""
    enrich_amounts_from_text(base_rows, amount_text)
    assert base_rows[0]['Beløb DKK'] == '-919.00'
    assert base_rows[1]['Beløb DKK'] == '-3151.25'