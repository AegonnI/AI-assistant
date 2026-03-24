from __future__ import annotations

from pathlib import Path
import io


def extract_text_from_pdf(input_path: str) -> str:
    """
    Основной PDF-парсер: извлекает полный текст документа.
    """
    pdf_path = Path(input_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF файл не найден: {input_path}")

    errors: list[str] = []

    # 1) Пытаемся через pypdf
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        parts: list[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        text = "\n".join(parts).strip()
        if text:
            return text
        errors.append("pypdf: пустой текст")
    except Exception as e:
        errors.append(f"pypdf: {e}")

    # 2) Fallback через pdfplumber
    try:
        import pdfplumber

        parts = []
        with pdf_path.open("rb") as f:
            data = f.read()
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        text = "\n".join(parts).strip()
        if text:
            return text
        errors.append("pdfplumber: пустой текст")
    except Exception as e:
        errors.append(f"pdfplumber: {e}")

    raise RuntimeError("Не удалось извлечь текст из PDF. " + " | ".join(errors))
