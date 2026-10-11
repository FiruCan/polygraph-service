"""
Tests fuer graph/export.py (PDF-Export einer Antwort). Schreibt nur in
temporaere Ordner, nie nach output/.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from graph import export
from graph.export import export_answer, safe_filename, unique_path

TRIPLES = [
    {"n": 1, "subject": "Clemastin", "relation": "regulates", "object": "Myelin",
     "evidence_level": "RCT", "confidence": 0.9, "origin": "https://example.org/clemastin"},
    {"n": 2, "subject": "Clemastin", "relation": "causes", "object": "Fatigue", "confidence": 0.6},
]


def test_safe_filename_drops_question_mark_and_forbidden_chars():
    assert safe_filename("Was bewirkt Clemastin?") == "Was bewirkt Clemastin"
    assert safe_filename('A/B: "C" <D>|E*?') == "A B C D E"
    assert safe_filename("Wie hängen Myokine und Demenz zusammen?") == "Wie hängen Myokine und Demenz zusammen"


def test_safe_filename_fallback_and_length():
    assert safe_filename("???") == "Antwort"
    assert len(safe_filename("x" * 500)) <= export.MAX_FILENAME


def test_unique_path_never_overwrites(tmp_path):
    first = unique_path(str(tmp_path), "Frage")
    open(first, "w").close()
    second = unique_path(str(tmp_path), "Frage")
    assert os.path.basename(first) == "Frage.pdf"
    assert os.path.basename(second) == "Frage (2).pdf"


def test_export_answer_writes_pdf_named_after_question(tmp_path):
    path = export_answer(
        "Was bewirkt Clemastin?",
        "Clemastin fördert die Remyelinisierung [1] – und verursacht Müdigkeit → Fatigue [2].\n\nZweiter Absatz <mit> & Sonderzeichen.",
        ["Clemastin"], TRIPLES, "http://localhost:8000", output_dir=str(tmp_path))
    assert os.path.basename(path) == "Was bewirkt Clemastin.pdf"
    with open(path, "rb") as f:
        data = f.read()
    assert data.startswith(b"%PDF")
    assert len(data) > 1000


def test_export_answer_without_triples_and_nodes(tmp_path):
    path = export_answer("Leere Antwort?", "", [], [], output_dir=str(tmp_path))
    assert os.path.exists(path)


def test_export_uses_output_dir_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "OUTPUT_DIR", str(tmp_path / "output"))
    path = export_answer("Frage?", "Antwort", [], [])
    assert os.path.dirname(path) == str(tmp_path / "output")


def test_origin_url_becomes_clickable_link(tmp_path):
    from graph.export import _origin_markup
    assert _origin_markup("https://example.org/a?x=1&y=2") == (
        'Quelle: <a href="https://example.org/a?x=1&amp;y=2" color="#1a5fb4">'
        '<u>https://example.org/a?x=1&amp;y=2</u></a>')
    assert _origin_markup("test/output/muskel.json") == "Quelle: test/output/muskel.json"
    path = export_answer("Link?", "x", [], [{**TRIPLES[0], "origin": "https://example.org/a?x=1&y=2"}],
                         output_dir=str(tmp_path))
    with open(path, "rb") as f:
        data = f.read()
    assert b"/URI (https://example.org/a?x=1&y=2)" in data  # echter Link-Annotation im PDF
