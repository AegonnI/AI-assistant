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


def _extract_years_from_line(line: str) -> List[int]:
    """Возвращает список годов из строки, например 2023, 2022."""
    years = re.findall(r"\b(20[0-9]{2})\b", line)
    return [int(y) for y in years]


def _is_year_header_line(line: str, years: List[int], nums: List[float]) -> bool:
    """Проверка, что строка — заголовок столбцов годов, а не строка данных."""
    if len(years) < 2:
        return False
    # Если в строке найдено несколько лет и количество чисел очень близко к количеству лет,
    # считаем, что это строчка заголовка колонки.
    if len(nums) == len(years) or len(nums) - len(years) <= 1:
        return True
    # Если строка явно содержит слова «год» / «г.» — тоже заголовок.
    low = line.lower()
    if 'год' in low or 'г.' in low:
        return True
    return False


def _choose_year_aligned_value(nums: List[float], years: List[int]) -> Optional[float]:
    if not nums:
        return None

    if not years:
        return nums[0]

    # Убираем из строки годовые числа, если они попали в массив значений (2023, 2022 и т.п.).
    filtered = [n for n in nums if int(n) not in years]
    if filtered:
        nums = filtered

    if not nums:
        return None

    latest_year = max(years)
    if latest_year in years:
        idx = years.index(latest_year)
    else:
        idx = 0

    if idx < len(nums):
        return nums[idx]

    # Фоллбек
    return nums[0]


def _split_table_columns(line: str) -> List[str]:
    # Разбиваем по двум и более пробелам / табам (табличное представление)
    cols = re.split(r"\s{2,}|\t", line.strip())
    return [c.strip() for c in cols if c.strip()]


def _choose_value_from_columns(line: str, current_years: List[int]) -> Optional[float]:
    cols = _split_table_columns(line)
    if len(cols) < 2:
        return None

    # Ищем числа для каждой колонки (обычно первая колонка - описание)
    nums_per_col = []
    for col in cols:
        nums = _find_numbers_in_line(col)
        nums_per_col.append(nums[0] if nums else None)

    # Удаляем колонку с названием строки, если там нет числа
    if nums_per_col and nums_per_col[0] is None:
        nums_per_col = nums_per_col[1:]

    nums_filtered = [n for n in nums_per_col if n is not None]
    if not nums_filtered:
        return None

    if current_years and len(current_years) <= len(nums_per_col):
        latest_year = max(current_years)
        if latest_year in current_years:
            idx = current_years.index(latest_year)
            if idx < len(nums_per_col) and nums_per_col[idx] is not None:
                return nums_per_col[idx]

    # Фолбэк: последнее численное значение в строке
    return nums_filtered[-1]


def parse_pdf_lines(lines: List[str]) -> Dict[str, Optional[float]]:
    """
    Возвращает словарь полей -> число по ключевым словам.

    Базовый алгоритм теперь учитывает контекст годовых столбцов в таблицах:
    - если встречена строка с годами (2023, 2022, ...), используется её порядок.
    - когда в строке несколько чисел, выбирается число из столбца последнего года.
    - без контекста года берётся последнее число в строке (наиболее вероятно актуальное).
    """
    found: Dict[str, Optional[float]] = {k: None for k in KEYWORD_MAP}
    current_years: List[int] = []

    for line in lines:
        low = line.lower().strip()

        if not low:
            continue

        detected_years = _extract_years_from_line(line)
        is_year_header = bool(detected_years and _is_year_header_line(line, detected_years, _find_numbers_in_line(line)))

        if is_year_header:
            current_years = [y for y in detected_years if y not in current_years]
            continue

        if 'страница' in low or 'page' in low:
            # Сбрасываем годовой контекст при переходе на новую страницу
            current_years = []

        chosen_value = None

        # Стратегия 1: извлечь по колонкам, если табличная строка
        chosen_value = _choose_value_from_columns(line, current_years)

        # Стратегия 2: если не получилось, выбрать из чисел строки (по текущему году)
        if chosen_value is None:
            nums = _find_numbers_in_line(line)
            if nums:
                chosen_value = _choose_year_aligned_value(nums, current_years)

        if chosen_value is None:
            continue

        for field, phrases in KEYWORD_MAP.items():
            if _line_matches_keyword(low, phrases):
                found[field] = chosen_value

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
