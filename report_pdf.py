"""
Генерация PDF-отчёта по результатам анализа (метрики, предупреждения, рекомендации).
Кириллица: шрифт Arial из Windows, иначе только латиница в заголовках.
"""
from __future__ import annotations

import io
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from coefficients_module import MetricResult, MetricStatus, status_emoji


def _register_cyrillic_font() -> str:
    candidates = [
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arial.ttf"),
        r"C:\Windows\Fonts\arial.ttf",
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            try:
                pdfmetrics.registerFont(TTFont("ReportArial", path))
                return "ReportArial"
            except Exception:
                continue
    return "Helvetica"


def build_analysis_pdf(
    *,
    file_name: str,
    analysis_date: str,
    warnings: List[str],
    metrics: List[MetricResult],
    recommendations_text: Optional[str],
) -> bytes:
    font = _register_cyrillic_font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        name="TitleRU",
        parent=styles["Title"],
        fontName=font,
        fontSize=16,
        leading=20,
    )
    body = ParagraphStyle(
        name="BodyRU",
        parent=styles["Normal"],
        fontName=font,
        fontSize=10,
        leading=14,
    )
    story: List[Any] = []

    story.append(Paragraph("Финансовый отчёт (автоанализ)", title_style))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(f"<b>Файл:</b> {file_name}", body))
    story.append(Paragraph(f"<b>Дата:</b> {analysis_date}", body))
    story.append(Spacer(1, 0.5 * cm))

    if warnings:
        story.append(Paragraph("<b>Предупреждения</b>", body))
        for w in warnings:
            story.append(Paragraph(f"• {w}", body))
        story.append(Spacer(1, 0.4 * cm))

    table_data = [["Статус", "Показатель", "Значение", "Формула"]]
    for m in metrics:
        em = status_emoji(m.status)
        table_data.append([em, m.title, m.display, m.formula])

    t = Table(table_data, colWidths=[1.2 * cm, 4.5 * cm, 2.2 * cm, 6.5 * cm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 0.6 * cm))

    if recommendations_text:
        story.append(Paragraph("<b>Рекомендации</b>", body))
        # Экранируем угловые скобки для reportlab
        safe = (
            recommendations_text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        for chunk in safe.split("\n"):
            if chunk.strip():
                story.append(Paragraph(chunk.strip(), body))

    doc.build(story)
    return buf.getvalue()


def build_pdf_from_session_payload(payload: Dict[str, Any]) -> bytes:
    """Удобная обёртка под структуру, которую можно хранить в st.session_state."""
    metrics = payload.get("metrics_detailed") or []
    if metrics and isinstance(metrics[0], dict):
        mlist: List[MetricResult] = []
        for d in metrics:
            mlist.append(
                MetricResult(
                    key=d["key"],
                    title=d["title"],
                    formula=d["formula"],
                    value=d.get("value"),
                    display=d["display"],
                    unit=d["unit"],
                    status=MetricStatus(d["status"]),
                    hint=d.get("hint", ""),
                )
            )
        metrics = mlist

    return build_analysis_pdf(
        file_name=payload.get("file_name", "document.pdf"),
        analysis_date=payload.get("date", datetime.now().strftime("%Y-%m-%d")),
        warnings=list(payload.get("warnings") or []),
        metrics=metrics,
        recommendations_text=payload.get("recommendations"),
    )
