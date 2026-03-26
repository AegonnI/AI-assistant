from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path

INPUT = Path("input/IFRS_12m2023_summary.pdf")
OUT_DIR = Path("output")
MAX_PAGES = 10

OUT_DIR.mkdir(parents=True, exist_ok=True)
base = INPUT.stem
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
txt_path = OUT_DIR / f"{base}_first{MAX_PAGES}_{timestamp}.txt"
json_path = OUT_DIR / f"{base}_first{MAX_PAGES}_{timestamp}.json"

text = ""

# Try pypdf first
try:
    from pypdf import PdfReader
    reader = PdfReader(str(INPUT))
    parts = []
    pages = reader.pages[:MAX_PAGES]
    for p in pages:
        parts.append(p.extract_text() or "")
    text = "\n".join(parts).strip()
    if not text:
        raise ValueError("pypdf returned empty text")
except Exception:
    # fallback to pdfplumber
    try:
        import pdfplumber
        with INPUT.open("rb") as f:
            data = f.read()
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            parts = []
            for p in pdf.pages[:MAX_PAGES]:
                parts.append(p.extract_text() or "")
        text = "\n".join(parts).strip()
    except Exception as e:
        print(f"Failed to extract text: {e}")
        raise

# Write outputs
txt_path.write_text(text, encoding="utf-8")
payload = {
    "source_pdf": str(INPUT),
    "created_at": datetime.now().isoformat(timespec="seconds"),
    "pages_used": MAX_PAGES,
    "text": text,
}
json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

print(json_path)
