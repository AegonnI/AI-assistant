"""
Сквозной сценарий: PDF → факты → метрики → структура для UI и рекомендаций.
Подключение в app.py: вызвать run_pipeline_on_uploaded_pdf(bytes, name).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .coefficients_module import MetricResult, compute_metrics, metrics_to_coefficients_dict
from .financial_parser import parse_financial_pdf, parse_pdf_lines
from .financial_transform import collect_warnings, raw_dict_to_facts


def _serialize_metric(m: MetricResult) -> Dict[str, Any]:
    return {
        "key": m.key,
        "title": m.title,
        "formula": m.formula,
        "value": m.value,
        "display": m.display,
        "unit": m.unit,
        "status": m.status.value,
        "hint": m.hint,
    }


def _lines_from_parser_result(parser_result: dict) -> List[str]:
    """Преобразует результат `extract_pdf_simple` в упорядоченный список строк для разбора."""
    lines: List[str] = []

    # 1. Используем структурированные блоки, если есть.
    # Это лучшая возможность сохранить табличный порядок и избежать смешения столбцов.
    pages = parser_result.get('pages') or parser_result.get('structured') or []
    for page in pages:
        if isinstance(page, dict):
            for block in page.get('blocks', []):
                content = str(block.get('content', '')).strip()
                if not content:
                    continue
                for ln in content.splitlines():
                    t = ln.strip()
                    if t:
                        lines.append(t)
        else:
            for ln in str(page).splitlines():
                t = ln.strip()
                if t:
                    lines.append(t)

    if lines:
        return lines

    # 2. fallback: plain_text (если структурированной информации нет)
    plain_text = (parser_result.get('plain_text') or parser_result.get('text') or '').strip()
    if plain_text:
        for ln in plain_text.splitlines():
            t = ln.strip()
            if t:
                lines.append(t)

    return lines


def _count_non_none_fields(raw_fields: Dict[str, Optional[float]]) -> int:
    return sum(1 for v in raw_fields.values() if v is not None)


def run_pipeline_on_uploaded_pdf(file_bytes: bytes, file_name: str, parser_result: dict | None = None) -> Dict[str, Any]:
    """
    Запускает пайплайн метрик для загруженного PDF.

    Если предоставлен `parser_result` (результат из `extract_pdf_simple`),
    используем текст из него и избегаем повторного парсинга PDF.
    """
    chosen_raw = None
    parse_meta = {
        'strategy': 'direct',
        'processor': 'parse_financial_pdf',
        'line_count': 0,
        'details': {}
    }

    if parser_result is not None:
        # 1) Структурированная строка из parser_result
        lines_structured = _lines_from_parser_result(parser_result)
        raw_structured = parse_pdf_lines(lines_structured) if lines_structured else {}
        score_structured = _count_non_none_fields(raw_structured)

        # 2) Чистый текст из parser_result
        plain_text = (parser_result.get('plain_text') or parser_result.get('text') or '').strip()
        lines_plain = [ln.strip() for ln in plain_text.splitlines() if ln.strip()] if plain_text else []
        raw_plain = parse_pdf_lines(lines_plain) if lines_plain else {}
        score_plain = _count_non_none_fields(raw_plain)

        # 3) Прямой парсинг из bytes (через pdfplumber) для сравнения
        raw_direct = {}
        score_direct = -1
        if file_bytes is not None:
            direct_parsed = parse_financial_pdf(file_bytes)
            raw_direct = direct_parsed.get('raw_fields', {})
            score_direct = _count_non_none_fields(raw_direct)

        candidate = 'structured'
        chosen_raw = raw_structured
        chosen_lines = lines_structured
        chosen_score = score_structured

        if score_plain > chosen_score:
            candidate = 'plain'
            chosen_raw = raw_plain
            chosen_lines = lines_plain
            chosen_score = score_plain

        if score_direct > chosen_score:
            candidate = 'direct'
            chosen_raw = raw_direct
            chosen_lines = []
            chosen_score = score_direct

        parse_meta['strategy'] = candidate
        parse_meta['line_count'] = len(chosen_lines)
        parse_meta['details'] = {
            'score_structured': score_structured,
            'score_plain': score_plain,
            'score_direct': score_direct,
            'rows_structured': len(lines_structured),
            'rows_plain': len(lines_plain),
            'candidate': candidate,
        }

        parsed = {
            'raw_fields': chosen_raw,
            'line_count': len(chosen_lines),
            'preview_lines': chosen_lines[:80],
        }
    else:
        parsed = parse_financial_pdf(file_bytes)
        parse_meta['line_count'] = parsed.get('line_count', 0)
        parse_meta['details']['direct'] = True

    raw = parsed['raw_fields']
    facts = raw_dict_to_facts(raw)
    warnings = collect_warnings(facts)
    metrics = compute_metrics(facts)
    coeff_flat = metrics_to_coefficients_dict(metrics)

    date_s = datetime.now().strftime('%Y-%m-%d')

    return {
        'file_name': file_name,
        'date': date_s,
        'coefficients': coeff_flat,
        'warnings': warnings,
        'metrics_detailed': [_serialize_metric(m) for m in metrics],
        'facts': raw,
        'parse_meta': parse_meta,
    }


def format_metrics_for_llm_prompt(metrics_detailed: List[Dict[str, Any]]) -> str:
    lines = []
    for m in metrics_detailed:
        lines.append(f"- {m['title']}: {m['display']} ({m['status']}) — {m['hint']}")
    return "\n".join(lines)
