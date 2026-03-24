"""
Извлечение числовых показателей из текста PDF (баланс, ОПУ, ОДДС).
Ищет типичные русскоязычные подписи строк и числа в той же строке или соседних.
"""
from __future__ import annotations

import io
import re
from typing import Any, BinaryIO, Dict, List, Optional, Tuple

import pdfplumber

# Ключ: поле FinancialFacts (см. financial_transform); значения — подстроки для поиска в строке (нижний регистр)
KEYWORD_MAP: Dict[str, List[str]] = {
    "revenue": [
        "выручка",
        "revenue",
        "выручка от реализации",
    ],
    "net_profit": [
        "чистая прибыль",
        "прибыль за год",
        "net profit",
    ],
    "profit_from_sales": [
        "операционная прибыль",
        "прибыль от продаж",
        "прибыль от основной",
        "operating profit",
    ],
    "total_assets": [
        "итого активы",
        "всего активов",
        "total assets",
        "активы всего",
    ],
    "equity": [
        "капитал и резервы",
        "собственный капитал",
        "итого капитал",
        "total equity",
    ],
    "current_assets": [
        "оборотные активы",
        "current assets",
    ],
    "current_liabilities": [
        "краткосрочные обязательства",
        "краткосрочные пассивы",
        "current liabilities",
    ],
    "inventories": [
        "запасы",
        "inventories",
    ],
    "cash_and_short_term_investments": [
        "денежные средства",
        "денежные средства и их эквиваленты",
        "краткосрочные финансовые вложения",
    ],
    "total_liabilities": [
        "итого обязательства",
        "итого пассивы",
        "total liabilities",
    ],
    "accounts_receivable": [
        "дебиторская задолженность",
        "accounts receivable",
    ],
    "capex": [
        "приобретение основных средств",
        "приобретение внеоборотных активов",
        "покупка основных средств",
        "capex",
    ],
}

# Порядок важности: более длинные фразы раньше
for _k, phrases in KEYWORD_MAP.items():
    phrases.sort(key=len, reverse=True)


def _normalize_number(raw: str) -> Optional[float]:
    s = raw.strip().replace("\xa0", " ").replace(" ", "")
    s = s.replace(",", ".")
    if not s or s in "-—":
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    if s.endswith("%"):
        s = s[:-1]
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


def _find_numbers_in_line(line: str) -> List[float]:
    # Числа вида 1 243 808 или 1243808,42; скобки для отрицательных в отчётах
    pattern = re.compile(
        r"\(?\s*[\d\s]{1,20}(?:[,.]\d+)?\s*\)?",
        re.UNICODE,
    )
    out: List[float] = []
    for m in pattern.finditer(line):
        chunk = m.group(0)
        if len(chunk.replace(" ", "").replace("(", "").replace(")", "")) < 1:
            continue
        n = _normalize_number(chunk)
        if n is not None and abs(n) > 1e-9:
            out.append(n)
    return out


def _line_matches_keyword(low: str, phrases: List[str]) -> bool:
    return any(p in low for p in phrases)


def extract_lines_from_pdf(source: BinaryIO | bytes) -> List[str]:
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    lines: List[str] = []
    with pdfplumber.open(source) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for ln in text.splitlines():
                t = ln.strip()
                if t:
                    lines.append(t)
    return lines


def parse_pdf_lines(lines: List[str]) -> Dict[str, Optional[float]]:
    """
    Возвращает словарь полей -> первое найденное число по ключевым словам.
    При нескольких совпадениях берётся последнее (часто итог внизу таблицы).
    """
    found: Dict[str, Optional[float]] = {k: None for k in KEYWORD_MAP}

    for line in lines:
        low = line.lower()
        nums = _find_numbers_in_line(line)
        if not nums:
            continue
        # Берём последнее крупное число в строке (в отчётах справа итог)
        value = nums[-1]

        for field, phrases in KEYWORD_MAP.items():
            if _line_matches_keyword(low, phrases):
                found[field] = value

    return found


def parse_financial_pdf(source: BinaryIO | bytes) -> Dict[str, Any]:
    """
    Полный разбор PDF: сырые поля + отладочный список строк (по желанию обрезать в UI).
    """
    lines = extract_lines_from_pdf(source)
    raw = parse_pdf_lines(lines)
    return {
        "raw_fields": raw,
        "line_count": len(lines),
        "preview_lines": lines[:80],
    }
