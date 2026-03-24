"""
Сквозной сценарий: PDF → факты → метрики → структура для UI и рекомендаций.
Подключение в app.py: вызвать run_pipeline_on_uploaded_pdf(bytes, name).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from .coefficients_module import MetricResult, compute_metrics, metrics_to_coefficients_dict
from .financial_parser import parse_financial_pdf
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


def run_pipeline_on_uploaded_pdf(file_bytes: bytes, file_name: str) -> Dict[str, Any]:
    parsed = parse_financial_pdf(file_bytes)
    raw = parsed["raw_fields"]
    facts = raw_dict_to_facts(raw)
    warnings = collect_warnings(facts)
    metrics = compute_metrics(facts)
    coeff_flat = metrics_to_coefficients_dict(metrics)

    date_s = datetime.now().strftime("%Y-%m-%d")

    return {
        "file_name": file_name,
        "date": date_s,
        "coefficients": coeff_flat,
        "warnings": warnings,
        "metrics_detailed": [_serialize_metric(m) for m in metrics],
        "facts": raw,
        "parse_meta": {"line_count": parsed["line_count"]},
    }


def format_metrics_for_llm_prompt(metrics_detailed: List[Dict[str, Any]]) -> str:
    lines = []
    for m in metrics_detailed:
        lines.append(f"- {m['title']}: {m['display']} ({m['status']}) — {m['hint']}")
    return "\n".join(lines)
