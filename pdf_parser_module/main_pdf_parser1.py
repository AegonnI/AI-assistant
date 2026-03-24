from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from .main_pdf_parser import extract_text_from_pdf


def extract_pdf_simple(input_path: str, output_dir: str) -> Dict[str, Any]:
    """
    Input:
      - input_path: путь к PDF, например "input/document.pdf"
      - output_dir: папка для результатов, например "output/"

    Output:
      {
        "success": bool,
        "text": str,
        "output_file": str,
        "json_file": str,
        "error": Optional[str],
      }
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    base_name = Path(input_path).stem
    txt_path = out_dir / f"{base_name}.txt"
    json_path = out_dir / f"{base_name}.json"

    try:
        text = extract_text_from_pdf(input_path)

        txt_path.write_text(text, encoding="utf-8")

        json_payload = {
            "source_pdf": str(input_path),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "text": text,
        }
        json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "success": True,
            "text": text,
            "output_file": str(txt_path),
            "json_file": str(json_path),
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "text": "",
            "output_file": "",
            "json_file": "",
            "error": str(e),
        }


def main_result_parsing(input_path: str, output_dir: str) -> str:
    """
    Возвращает Json_str — путь к выходному JSON файлу для следующего блока.
    """
    result = extract_pdf_simple(input_path=input_path, output_dir=output_dir)
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "Ошибка парсинга PDF")
    return str(result["json_file"])
