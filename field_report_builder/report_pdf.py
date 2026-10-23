"""PDF export (ReportLab)."""

from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    CondPageBreak, Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)
from xml.sax.saxutils import escape

from . import __version__, layout
from .model import Report
from .photos import jpeg_bytes

MARGIN = 0.6 * inch
WIDTH = letter[0] - 2 * MARGIN
LINE = colors.HexColor("#8a8f98")
SHADE = colors.HexColor("#e8ebef")

_ss = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=_ss["BodyText"], fontName="Helvetica", fontSize=9, leading=11.5)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=7.5, leading=9, textColor=colors.HexColor("#555555"))
LABEL = ParagraphStyle("label", parent=BODY, fontName="Helvetica-Bold", fontSize=7.5, leading=9,
                       textColor=colors.HexColor("#444444"))
CELL_HEAD = ParagraphStyle("cellhead", parent=BODY, fontName="Helvetica-Bold", fontSize=8.5)
TITLE = ParagraphStyle("title", parent=BODY, fontName="Helvetica-Bold", fontSize=15, leading=18,
                       alignment=TA_CENTER, spaceAfter=8)
H2 = ParagraphStyle("h2", parent=BODY, fontName="Helvetica-Bold", fontSize=10, leading=12,
                    textColor=colors.white)


def _p(text, style=BODY):
    return Paragraph(escape(text or "").replace("\n", "<br/>"), style)


def _bar(title):
    t = Table([[_p(title.upper(), H2)]], colWidths=[WIDTH])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#2f3b4c")),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def _grid(t: Table, header=True):
    style = [("GRID", (0, 0), (-1, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), SHADE))
    t.setStyle(TableStyle(style))
    return t


def _table(sec: layout.Table):
    if not sec.rows:
        return [_bar(sec.title), Spacer(1, 3), _p(sec.empty), Spacer(1, 8)]
    data = [[_p(h, CELL_HEAD) for h in sec.headers]] + [[_p(c) for c in row] for row in sec.rows]
    t = _grid(Table(data, colWidths=[w * WIDTH for w in sec.widths], repeatRows=1))
    return [_bar(sec.title), Spacer(1, 3), t, Spacer(1, 8)]


def _bullets(sec: layout.Bullets):
    if not sec.items:
        body = _p(sec.empty)
    else:
        body = ListFlowable([ListItem(_p(x), leftIndent=10) for x in sec.items], bulletType="bullet",
                            start="•", leftIndent=10, bulletFontSize=8)
    return [KeepTogether([_bar(sec.title), Spacer(1, 3), body]), Spacer(1, 8)]


def _header(r: Report):
    rows = []
    for pair in layout.header_rows(r):
        row = []
        for label, value in pair:
            row += [_p(label.upper(), LABEL), _p(value)]
        rows.append(row)
    return _grid(Table(rows, colWidths=[0.15 * WIDTH, 0.35 * WIDTH, 0.15 * WIDTH, 0.35 * WIDTH]), header=False)


def _signatures():
    cells = []
    for title, _ in layout.SIGNATURES:
        line = Table([["", ""], [_p("Signature", SMALL), _p("Date", SMALL)]],
                     colWidths=[(WIDTH / 2 - 18) * 0.68, (WIDTH / 2 - 18) * 0.32])
        line.setStyle(TableStyle([("LINEABOVE", (0, 1), (-1, 1), 0.5, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        cells.append([_p(title.upper(), LABEL), Spacer(1, 18), line])
    t = Table([cells], colWidths=[WIDTH / 2 - 6, WIDTH / 2 - 6], spaceBefore=4)
    t.setStyle(TableStyle([("BOX", (0, 0), (0, 0), 0.5, LINE), ("BOX", (1, 0), (1, 0), 0.5, LINE),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return KeepTogether([_bar("Certification"), Spacer(1, 3),
                         _p("I certify that this report is a true record of the work and conditions observed."),
                         Spacer(1, 4), t])


def _photo_cell(photo, line, width):
    data = jpeg_bytes(photo.path, max_px=1400)
    img = Image(io.BytesIO(data))
    scale = min(width / img.imageWidth, (3.0 * inch) / img.imageHeight)
    img.drawWidth, img.drawHeight = img.imageWidth * scale, img.imageHeight * scale
    return [img, Spacer(1, 3), _p(line)]


def build_pdf(r: Report, path: str) -> None:
    doc = SimpleDocTemplate(path, pagesize=letter, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN,
                            bottomMargin=0.75 * inch, title=f"Daily Work Report {r.report_date}",
                            author=r.inspector or "Field Report Builder")
    story = [_p(layout.TITLE, TITLE), _header(r), Spacer(1, 10)]
    story += _table(layout.weather_table(r))
    note = layout.weather_source_note(r)
    if note:
        story[-1:] = [_p(note, SMALL), Spacer(1, 8)]
    for sec in layout.sections(r):
        story += _table(sec) if isinstance(sec, layout.Table) else _bullets(sec)
    story.append(_signatures())

    photos = layout.report_photos(r)
    if photos:
        story += [PageBreak(), _bar("Photographs"), Spacer(1, 6)]
        colw = WIDTH / 2 - 6
        for i in range(0, len(photos), 2):
            pair = photos[i:i + 2]
            cells = []
            for _, photo, line in pair:
                try:
                    cells.append(_photo_cell(photo, line, colw))
                except OSError:
                    cells.append([_p(line + " (image file missing)")])
            if len(cells) == 1:
                cells.append("")
            t = Table([cells], colWidths=[colw + 6, colw + 6])
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story += [CondPageBreak(3.6 * inch), t, Spacer(1, 10)]

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#555555"))
        left = f"{r.project}  |  {r.report_date}" + (f"  |  Report {r.report_no}" if r.report_no else "")
        canvas.drawString(MARGIN, 0.45 * inch, left)
        canvas.drawRightString(letter[0] - MARGIN, 0.45 * inch, f"Page {doc_.page}")
        canvas.drawCentredString(letter[0] / 2, 0.3 * inch, f"Prepared with Field Report Builder {__version__}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
