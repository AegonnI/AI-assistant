"""
Расчёт 12 финансовых метрик и грубая оценка статуса (норма / внимание / риск).
Пороги упрощённые, при необходимости вынести в конфиг.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from financial_transform import FinancialFacts


class MetricStatus(str, Enum):
    OK = "ok"
    WARN = "warn"
    RISK = "risk"
    NA = "na"


@dataclass
class MetricResult:
    key: str
    title: str
    formula: str
    value: Optional[float]
    display: str
    unit: str
    status: MetricStatus
    hint: str


def _safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _ros_status(v: Optional[float]) -> MetricStatus:
    if v is None:
        return MetricStatus.NA
    if v >= 0.15:
        return MetricStatus.OK
    if v >= 0.05:
        return MetricStatus.WARN
    return MetricStatus.RISK


def _npm_status(v: Optional[float]) -> MetricStatus:
    if v is None:
        return MetricStatus.NA
    if v >= 0.10:
        return MetricStatus.OK
    if v >= 0.03:
        return MetricStatus.WARN
    return MetricStatus.RISK


def _roa_roe_status(v: Optional[float]) -> MetricStatus:
    if v is None:
        return MetricStatus.NA
    if v >= 0.08:
        return MetricStatus.OK
    if v >= 0.03:
        return MetricStatus.WARN
    return MetricStatus.RISK


def _current_ratio_status(v: Optional[float]) -> MetricStatus:
    if v is None:
        return MetricStatus.NA
    if v >= 1.5:
        return MetricStatus.OK
    if v >= 1.0:
        return MetricStatus.WARN
    return MetricStatus.RISK


def _quick_ratio_status(v: Optional[float]) -> MetricStatus:
    if v is None:
        return MetricStatus.NA
    if v >= 1.0:
        return MetricStatus.OK
    if v >= 0.7:
        return MetricStatus.WARN
    return MetricStatus.RISK


def _cash_ratio_status(v: Optional[float]) -> MetricStatus:
    if v is None:
        return MetricStatus.NA
    if v >= 0.2:
        return MetricStatus.OK
    if v >= 0.1:
        return MetricStatus.WARN
    return MetricStatus.RISK


def _autonomy_status(v: Optional[float]) -> MetricStatus:
    if v is None:
        return MetricStatus.NA
    if v >= 0.5:
        return MetricStatus.OK
    if v >= 0.33:
        return MetricStatus.WARN
    return MetricStatus.RISK


def _leverage_status(v: Optional[float]) -> MetricStatus:
    if v is None:
        return MetricStatus.NA
    if v <= 1.0:
        return MetricStatus.OK
    if v <= 2.5:
        return MetricStatus.WARN
    return MetricStatus.RISK


def _dso_status(days: Optional[float]) -> MetricStatus:
    if days is None:
        return MetricStatus.NA
    if days <= 45:
        return MetricStatus.OK
    if days <= 90:
        return MetricStatus.WARN
    return MetricStatus.RISK


def _asset_turnover_status(v: Optional[float]) -> MetricStatus:
    if v is None:
        return MetricStatus.NA
    if v >= 0.5:
        return MetricStatus.OK
    if v >= 0.3:
        return MetricStatus.WARN
    return MetricStatus.RISK


def _capex_rev_status(v: Optional[float]) -> MetricStatus:
    if v is None:
        return MetricStatus.NA
    if v <= 0.25:
        return MetricStatus.OK
    if v <= 0.40:
        return MetricStatus.WARN
    return MetricStatus.RISK


def compute_metrics(facts: FinancialFacts) -> List[MetricResult]:
    p_sales = facts.profit_from_sales
    rev = facts.revenue
    np_ = facts.net_profit
    assets = facts.total_assets
    eq = facts.equity
    ca = facts.current_assets
    cl = facts.current_liabilities
    inv_known = facts.inventories is not None
    inv = facts.inventories if inv_known else None
    cash = facts.cash_and_short_term_investments
    tl = facts.total_liabilities
    ar = facts.accounts_receivable
    capex = facts.capex

    ros = _safe_div(p_sales, rev)
    npm = _safe_div(np_, rev)
    roa = _safe_div(np_, assets)
    roe = _safe_div(np_, eq)
    current_ratio = _safe_div(ca, cl)
    quick_num = None
    if ca is not None and cl not in (None, 0) and inv is not None:
        quick_num = (ca - inv) / cl
    cash_ratio = _safe_div(cash, cl)
    autonomy = _safe_div(eq, assets)
    lev = _safe_div(tl, eq)
    dso = None
    if ar is not None and rev not in (None, 0):
        dso = (ar / rev) * 365.0
    asset_turn = _safe_div(rev, assets)
    capex_rev = _safe_div(capex, rev)

    def fmt_pct(x: Optional[float]) -> str:
        if x is None:
            return "—"
        return f"{x * 100:.2f}%"

    def fmt_num(x: Optional[float], nd: int = 2) -> str:
        if x is None:
            return "—"
        return f"{x:.{nd}f}"

    rows: List[MetricResult] = [
        MetricResult(
            "ros",
            "Рентабельность продаж",
            "Прибыль от продаж / Выручка",
            ros,
            fmt_pct(ros),
            "%",
            _ros_status(ros),
            "Доля операционной прибыли в выручке.",
        ),
        MetricResult(
            "net_margin",
            "Рентабельность чистой прибыли",
            "Чистая прибыль / Выручка",
            npm,
            fmt_pct(npm),
            "%",
            _npm_status(npm),
            "Сколько чистой прибыли с рубля выручки.",
        ),
        MetricResult(
            "roa",
            "ROA",
            "Чистая прибыль / Активы",
            roa,
            fmt_pct(roa),
            "%",
            _roa_roe_status(roa),
            "Эффективность использования активов.",
        ),
        MetricResult(
            "roe",
            "ROE",
            "Чистая прибыль / Собственный капитал",
            roe,
            fmt_pct(roe),
            "%",
            _roa_roe_status(roe),
            "Доходность капитала для владельцев.",
        ),
        MetricResult(
            "current_ratio",
            "Текущая ликвидность",
            "Оборотные активы / Краткосрочные обязательства",
            current_ratio,
            fmt_num(current_ratio),
            "раз",
            _current_ratio_status(current_ratio),
            "Покрытие краткосрочных долгов оборотными активами.",
        ),
        MetricResult(
            "quick_ratio",
            "Быстрая ликвидность",
            "(Оборотные активы − Запасы) / Краткосрочные обязательства",
            quick_num,
            fmt_num(quick_num),
            "раз",
            _quick_ratio_status(quick_num),
            "Ликвидность без запасов.",
        ),
        MetricResult(
            "cash_ratio",
            "Денежная ликвидность",
            "(Деньги + краткоср. вложения) / Краткосрочные обязательства",
            cash_ratio,
            fmt_num(cash_ratio),
            "раз",
            _cash_ratio_status(cash_ratio),
            "Мгновенная платёжеспособность.",
        ),
        MetricResult(
            "autonomy",
            "Автономия",
            "Собственный капитал / Активы",
            autonomy,
            fmt_num(autonomy),
            "доля",
            _autonomy_status(autonomy),
            "Доля собственных средств в активах.",
        ),
        MetricResult(
            "leverage",
            "Финансовый леверидж",
            "Обязательства / Собственный капитал",
            lev,
            fmt_num(lev),
            "раз",
            _leverage_status(lev),
            "Долг на рубль собственного капитала.",
        ),
        MetricResult(
            "dso",
            "Оборачиваемость дебиторки (дни)",
            "(Дебиторка / Выручка) × 365",
            dso,
            fmt_num(dso, 0) + " дн." if dso is not None else "—",
            "дни",
            _dso_status(dso),
            "Средний срок погашения дебиторки.",
        ),
        MetricResult(
            "asset_turnover",
            "Оборачиваемость активов",
            "Выручка / Активы",
            asset_turn,
            fmt_num(asset_turn),
            "раз",
            _asset_turnover_status(asset_turn),
            "Выручка на рубль активов.",
        ),
        MetricResult(
            "capex_revenue",
            "CAPEX / Выручка",
            "Приобретение ОС / Выручка",
            capex_rev,
            fmt_pct(capex_rev),
            "%",
            _capex_rev_status(capex_rev),
            "Доля инвестиций в основные средства от выручки.",
        ),
    ]
    return rows


def metrics_to_coefficients_dict(metrics: List[MetricResult]) -> Dict[str, float]:
    """Плоский словарь для совместимости со старым UI (числа, без «%» в ключе)."""
    out: Dict[str, float] = {}
    for m in metrics:
        if m.value is None:
            continue
        if m.unit == "%":
            out[m.title] = round(m.value * 100, 4)
        else:
            out[m.title] = round(float(m.value), 4)
    return out


def status_emoji(status: MetricStatus) -> str:
    if status == MetricStatus.OK:
        return "🟢"
    if status == MetricStatus.WARN:
        return "🟡"
    if status == MetricStatus.RISK:
        return "🔴"
    return "⚪"
