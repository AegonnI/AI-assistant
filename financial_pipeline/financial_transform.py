"""
Нормализация извлечённых полей в единую структуру для расчёта метрик.
Предупреждения о пропусках — для интерфейса («добавьте параметр»).
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Dict, List, Optional, Tuple


@dataclass
class FinancialFacts:
    """Все величины в одних единицах (по умолчанию как в отчёте: млн руб.)."""

    profit_from_sales: Optional[float] = None
    revenue: Optional[float] = None
    net_profit: Optional[float] = None
    total_assets: Optional[float] = None
    equity: Optional[float] = None
    current_assets: Optional[float] = None
    current_liabilities: Optional[float] = None
    inventories: Optional[float] = None
    cash_and_short_term_investments: Optional[float] = None
    total_liabilities: Optional[float] = None
    accounts_receivable: Optional[float] = None
    capex: Optional[float] = None

    unit_label: str = "млн руб."


REQUIRED_FOR_CORE_METRICS = (
    "revenue",
    "net_profit",
    "total_assets",
    "equity",
)


def raw_dict_to_facts(raw: Dict[str, Optional[float]]) -> FinancialFacts:
    return FinancialFacts(
        profit_from_sales=raw.get("profit_from_sales"),
        revenue=raw.get("revenue"),
        net_profit=raw.get("net_profit"),
        total_assets=raw.get("total_assets"),
        equity=raw.get("equity"),
        current_assets=raw.get("current_assets"),
        current_liabilities=raw.get("current_liabilities"),
        inventories=raw.get("inventories"),
        cash_and_short_term_investments=raw.get("cash_and_short_term_investments"),
        total_liabilities=raw.get("total_liabilities"),
        accounts_receivable=raw.get("accounts_receivable"),
        capex=raw.get("capex"),
    )


def collect_warnings(facts: FinancialFacts) -> List[str]:
    warnings: List[str] = []
    for name in REQUIRED_FOR_CORE_METRICS:
        if getattr(facts, name) is None:
            warnings.append(
                f"Нет показателя «{name}» — часть метрик будет пропущена. Добавьте строку в отчёт или введите вручную."
            )

    if facts.current_assets is not None and facts.current_liabilities is None:
        warnings.append("Для ликвидности нужны краткосрочные обязательства.")
    if facts.profit_from_sales is None:
        warnings.append("Нет «прибыль от продаж / операционная прибыль» — рентабельность продаж не посчитана.")
    if (
        facts.current_assets is not None
        and facts.current_liabilities is not None
        and facts.inventories is None
    ):
        warnings.append("Нет строки «Запасы» — быстрая ликвидность не посчитана.")

    return warnings


def facts_to_prompt_summary(facts: FinancialFacts) -> str:
    parts = []
    for f in fields(FinancialFacts):
        if f.name == "unit_label":
            continue
        v = getattr(facts, f.name)
        if v is not None:
            parts.append(f"{f.name}={v}")
    return "; ".join(parts) if parts else "данные не извлечены"
