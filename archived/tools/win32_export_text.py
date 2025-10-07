import os
import sys
import json
from pathlib import Path

try:
    import win32com.client  # type: ignore
except ImportError:
    print(json.dumps({"ok": False, "error": "pywin32 not installed"}))
    sys.exit(1)

DOCX_NAME = "A012-5599 TPS 4.8 MW Air Cooler IG GEN V05 - CAC.docx"
OUTPUT_NAME = "tps_win32_full.txt"

DOCX_PATH = Path(DOCX_NAME).absolute()
OUTPUT_PATH = Path(OUTPUT_NAME).absolute()

result = {"ok": True, "docx": str(DOCX_PATH), "output": str(OUTPUT_PATH)}

word = None
_doc = None
try:
    if not DOCX_PATH.exists():
        raise FileNotFoundError(f"Missing DOCX {DOCX_PATH}")
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    _doc = word.Documents.Open(str(DOCX_PATH))
    text_content = _doc.Content.Text
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(text_content)
    result["bytes"] = OUTPUT_PATH.stat().st_size
except Exception as e:
    result = {"ok": False, "error": str(e)}
finally:
    if _doc is not None:
        _doc.Close(False)
    if word is not None:
        word.Quit()

print(json.dumps(result, indent=2))
