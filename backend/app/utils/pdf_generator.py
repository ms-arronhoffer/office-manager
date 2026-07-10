import io
from datetime import datetime, timezone
from typing import Any
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable


def generate_pdf(
    title: str,
    headers: list[str],
    rows: list[list[Any]],
    orientation: str = "landscape",
) -> io.BytesIO:
    buffer = io.BytesIO()
    pagesize = landscape(letter) if orientation == "landscape" else letter

    doc = SimpleDocTemplate(
        buffer,
        pagesize=pagesize,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Heading1"], fontSize=16, spaceAfter=12
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle", parent=styles["Normal"], fontSize=9, textColor=colors.grey
    )

    elements = []
    elements.append(Paragraph(title, title_style))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", subtitle_style))
    elements.append(Spacer(1, 12))

    cell_style = ParagraphStyle("CellStyle", parent=styles["Normal"], fontSize=7, leading=9)

    def make_cell(val):
        text = str(val) if val is not None else ""
        if len(text) > 80:
            text = text[:77] + "..."
        return Paragraph(text, cell_style)

    table_data = [[make_cell(h) for h in headers]]
    for row in rows:
        table_data.append([make_cell(v) for v in row])

    if not table_data or len(table_data) <= 1:
        elements.append(Paragraph("No data to display.", styles["Normal"]))
    else:
        num_cols = len(headers)
        available_width = pagesize[0] - 1 * inch
        col_width = available_width / num_cols

        table = Table(table_data, colWidths=[col_width] * num_cols, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#232f3e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("FONTSIZE", (0, 1), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
            ("TOPPADDING", (0, 1), (-1, -1), 4),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        elements.append(table)

    doc.build(elements)
    buffer.seek(0)
    return buffer


def _fmt_money(value: Any) -> str:
    if value is None:
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    formatted = f"${abs(num):,.2f}"
    return f"({formatted})" if num < 0 else formatted


def generate_statement_pdf(
    *,
    company_name: str,
    statement_title: str,
    period_label: str,
    sections: list[dict[str, Any]],
    summary_lines: list[tuple[str, Any]] | None = None,
) -> io.BytesIO:
    """Render a single GAAP financial statement as an executive-ready PDF.

    ``sections`` is an ordered list of ``{"title", "rows", "total_label",
    "total"}`` dicts, where ``rows`` is a list of ``(code, name, amount)``
    tuples. ``summary_lines`` renders a closing key/value box (e.g. net
    income, or a balance/reconciliation check) below the sections.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=f"{company_name} — {statement_title}",
    )

    styles = getSampleStyleSheet()
    company_style = ParagraphStyle(
        "Company", parent=styles["Normal"], fontSize=11, textColor=colors.HexColor("#232f3e"),
        alignment=TA_CENTER, spaceAfter=2,
    )
    title_style = ParagraphStyle(
        "StatementTitle", parent=styles["Heading1"], fontSize=18, alignment=TA_CENTER, spaceAfter=2,
    )
    period_style = ParagraphStyle(
        "Period", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#545b64"),
        alignment=TA_CENTER, spaceAfter=4,
    )
    generated_style = ParagraphStyle(
        "Generated", parent=styles["Normal"], fontSize=7.5, textColor=colors.grey,
        alignment=TA_CENTER, spaceAfter=14,
    )
    section_header_style = ParagraphStyle(
        "SectionHeader", parent=styles["Heading3"], fontSize=11, textColor=colors.HexColor("#232f3e"),
        spaceBefore=10, spaceAfter=4,
    )
    line_style = ParagraphStyle("Line", parent=styles["Normal"], fontSize=9, leading=12)
    amount_style = ParagraphStyle("Amount", parent=styles["Normal"], fontSize=9, leading=12, alignment=TA_RIGHT)
    total_label_style = ParagraphStyle("TotalLabel", parent=line_style, fontName="Helvetica-Bold")
    total_amount_style = ParagraphStyle("TotalAmount", parent=amount_style, fontName="Helvetica-Bold")

    elements: list[Any] = [
        Paragraph(company_name, company_style),
        Paragraph(statement_title, title_style),
        Paragraph(period_label, period_style),
        Paragraph(f"Generated {datetime.now(timezone.utc).strftime('%B %d, %Y at %I:%M %p UTC')}", generated_style),
    ]

    available_width = letter[0] - 1.5 * inch

    for section in sections:
        rows = section.get("rows") or []
        elements.append(Paragraph(section["title"], section_header_style))
        elements.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#232f3e")))

        table_data = [
            [Paragraph(f"{code} — {name}" if code else name, line_style), Paragraph(_fmt_money(amount), amount_style)]
            for code, name, amount in rows
        ]
        table_data.append([
            Paragraph(section.get("total_label", "Total"), total_label_style),
            Paragraph(_fmt_money(section.get("total")), total_amount_style),
        ])

        if not rows:
            elements.append(Paragraph("No activity.", ParagraphStyle("Empty", parent=line_style, textColor=colors.grey, spaceBefore=4)))
            table_data = table_data[-1:]

        table = Table(table_data, colWidths=[available_width * 0.72, available_width * 0.28])
        style_cmds = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("LINEABOVE", (0, -1), (-1, -1), 0.75, colors.HexColor("#232f3e")),
            ("TOPPADDING", (0, -1), (-1, -1), 6),
        ]
        table.setStyle(TableStyle(style_cmds))
        elements.append(table)
        elements.append(Spacer(1, 6))

    if summary_lines:
        elements.append(Spacer(1, 6))
        elements.append(HRFlowable(width="100%", thickness=1.25, color=colors.HexColor("#232f3e")))
        summary_data = [
            [Paragraph(label, total_label_style), Paragraph(_fmt_money(value) if not isinstance(value, str) else value, total_amount_style)]
            for label, value in summary_lines
        ]
        summary_table = Table(summary_data, colWidths=[available_width * 0.72, available_width * 0.28])
        summary_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(summary_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer
