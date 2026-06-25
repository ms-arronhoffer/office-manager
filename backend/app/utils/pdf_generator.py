import io
from datetime import datetime
from typing import Any
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer


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
