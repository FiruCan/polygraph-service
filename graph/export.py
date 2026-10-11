"""
export.py
---------
PDF-Export einer Antwort (POST /export/pdf): Frage, Datum, Service, relevante
Knoten, Antworttext und alle Belege mit Quellen - als Datei in output/, der
Dateiname ist die Frage (z.B. "Was bewirkt Clemastin.pdf").

Serverseitig statt per Browser-Druckdialog, weil ein Browser nicht in einen
festen Ordner schreiben darf und der Dialog (z.B. Safari ohne Drucker:
"Drucken" ausgegraut) umstaendlich war.

reportlab mit Arial (Systemschrift) fuer Umlaute und Zeichen wie "–" oder
"→"; ist keine der Schriften vorhanden, Helvetica (deckt nur Latin-1 ab).
"""

import os
import re
from datetime import datetime
from xml.sax.saxutils import escape, quoteattr

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")
FONT_CANDIDATES = [
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]
MAX_FILENAME = 120


def _fonts() -> tuple:
    """Registriert eine Unicode-Schrift, gibt (normal, fett) zurueck."""
    for regular, bold in FONT_CANDIDATES:
        if os.path.exists(regular) and os.path.exists(bold):
            if "PG-Regular" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("PG-Regular", regular))
                pdfmetrics.registerFont(TTFont("PG-Bold", bold))
            return "PG-Regular", "PG-Bold"
    return "Helvetica", "Helvetica-Bold"


def safe_filename(question: str) -> str:
    """Frage -> Dateiname: ohne Zeichen, die Dateisysteme nicht moegen, ohne '?' am Ende."""
    name = re.sub(r'[\\/:*?"<>|\n\r\t]+', " ", question)
    name = " ".join(name.split()).strip(" .")[:MAX_FILENAME].strip(" .")
    return name or "Antwort"


def unique_path(directory: str, name: str) -> str:
    """Ueberschreibt nichts: gibt es die Datei schon, wird ' (2)', ' (3)' ... angehaengt."""
    path = os.path.join(directory, f"{name}.pdf")
    n = 2
    while os.path.exists(path):
        path = os.path.join(directory, f"{name} ({n}).pdf")
        n += 1
    return path


def _beleg_line(t: dict) -> str:
    extra = [f"{label}: {t[key]}" for key, label in
             [("value", "value"), ("condition", "condition"),
              ("evidence_level", "evidence"), ("confidence", "confidence")]
             if t.get(key) is not None]
    text = f"[{t.get('n')}] {t.get('subject')} --{t.get('relation')}--> {t.get('object')}"
    return text + (" | " + " | ".join(extra) if extra else "")


def _origin_markup(origin: str) -> str:
    """Quelle als klickbarer Link, wenn sie eine http(s)-URL ist - sonst als Text
    (z.B. ein Dateipfad aus build_graph.py)."""
    if origin.startswith(("http://", "https://")):
        return f'Quelle: <a href={quoteattr(origin)} color="#1a5fb4"><u>{escape(origin)}</u></a>'
    return escape(f"Quelle: {origin}")


def build_pdf(path: str, question: str, answer: str, selected_nodes: list,
              triples: list, service: str = None) -> None:
    regular, bold = _fonts()
    h1 = ParagraphStyle("h1", fontName=bold, fontSize=16, leading=20, spaceAfter=4)
    meta = ParagraphStyle("meta", fontName=regular, fontSize=8.5, leading=11, textColor=HexColor("#666666"))
    body = ParagraphStyle("body", fontName=regular, fontSize=10.5, leading=15)
    h2 = ParagraphStyle("h2", fontName=bold, fontSize=12, leading=15, spaceBefore=10, spaceAfter=4)
    small = ParagraphStyle("small", fontName=regular, fontSize=8.5, leading=11)
    origin = ParagraphStyle("origin", parent=small, textColor=HexColor("#888888"), leftIndent=10, spaceAfter=4)

    def beleg_style(conf):
        # wie im Frontend: sichere Belege fett, unsichere blasser
        if conf is not None and conf >= 0.9:
            return ParagraphStyle("hi", parent=small, fontName=bold)
        if conf is not None and conf < 0.7:
            return ParagraphStyle("lo", parent=small, textColor=HexColor("#999999"))
        return small

    meta_text = f"polygraph · {datetime.now():%d.%m.%Y %H:%M}" + (f" · {service}" if service else "")
    story = [Paragraph(escape(question), h1), Paragraph(escape(meta_text), meta), Spacer(1, 8)]
    if selected_nodes:
        story.append(Paragraph(escape("Relevante Knoten: " + ", ".join(selected_nodes)), small))
        story.append(Spacer(1, 6))
    for para in (answer or "").split("\n"):
        story.append(Paragraph(escape(para) if para.strip() else "&nbsp;", body))
    if triples:
        story.append(Paragraph("Belege", h2))
        for t in triples:
            story.append(Paragraph(escape(_beleg_line(t)), beleg_style(t.get("confidence"))))
            if t.get("origin"):
                story.append(Paragraph(_origin_markup(t["origin"]), origin))

    doc = SimpleDocTemplate(path, pagesize=A4, title=question, author="polygraph",
                            leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm)
    doc.build(story)


def export_answer(question: str, answer: str, selected_nodes: list, triples: list,
                  service: str = None, output_dir: str = None) -> str:
    """Schreibt das PDF nach output_dir (Standard: OUTPUT_DIR), gibt den Dateipfad zurueck."""
    output_dir = output_dir or OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    path = unique_path(output_dir, safe_filename(question))
    build_pdf(path, question, answer, selected_nodes, triples, service)
    return path
