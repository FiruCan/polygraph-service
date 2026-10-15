"""
Unit-Tests fuer graph/localize.py (Anzeige des Graphen in der Sprache des
Lesers). ollama.chat wird gemockt, der Cache liegt in tmp_path.
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from graph import localize as loc
from graph.localize import localize


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(loc, "CACHE_DIR", str(tmp_path))
    loc._caches.clear()
    yield tmp_path
    loc._caches.clear()


def answer(pairs):
    items = [{"original": o, "uebersetzung": t} for o, t in pairs]
    return {"message": {"content": json.dumps({"uebersetzungen": items})}}


def test_translates_and_keeps_missing_texts_unchanged():
    with patch("graph.localize.ollama.chat", return_value=answer([("muscles", "Muskeln")])) as chat:
        assert localize(["muscles", "IL-6"], "Deutsch") == {"muscles": "Muskeln", "IL-6": "IL-6"}
    prompt = chat.call_args.kwargs["messages"][0]["content"]
    assert "Deutsch" in prompt and "- muscles" in prompt


def test_english_needs_no_llm():
    with patch("graph.localize.ollama.chat") as chat:
        assert localize(["muscles"], "Englisch") == {"muscles": "muscles"}
    chat.assert_not_called()


def test_cache_is_persisted_per_language(cache_dir):
    with patch("graph.localize.ollama.chat", return_value=answer([("muscles", "kaslar")])):
        localize(["muscles"], "Türkisch")
    loc._caches.clear()  # wie nach einem Neustart
    with patch("graph.localize.ollama.chat") as chat:
        assert localize(["muscles"], "Türkisch") == {"muscles": "kaslar"}
        assert localize(["muscles"], "Deutsch", cached_only=True) == {}
    chat.assert_not_called()


def test_cached_only_skips_unknown_texts():
    with patch("graph.localize.ollama.chat", return_value=answer([("muscles", "Muskeln")])):
        localize(["muscles"], "Deutsch")
    with patch("graph.localize.ollama.chat") as chat:
        assert localize(["muscles", "brain"], "Deutsch", cached_only=True) == {"muscles": "Muskeln"}
    chat.assert_not_called()


def test_batches_and_ignores_broken_answers():
    texts = [f"t{i}" for i in range(loc.BATCH_SIZE + 5)]
    broken = {"message": {"content": "{kaputt"}}
    with patch("graph.localize.ollama.chat", return_value=broken) as chat:
        assert localize(texts, "Deutsch") == {t: t for t in texts}
    assert chat.call_count == 2


def test_language_cannot_escape_cache_dir(cache_dir):
    assert os.path.dirname(loc._cache_path("../../etc/x")) == str(cache_dir)


def texts_answer(items, done_reason="stop"):
    return {"message": {"content": json.dumps({"uebersetzungen": items})}, "done_reason": done_reason}


def test_translate_texts_keeps_order_and_missing_texts():
    reply = texts_answer([{"nr": 2, "text": "Kaslar [1]."}, {"nr": 9, "text": "x"}])
    with patch("graph.localize.ollama.chat", return_value=reply) as chat:
        assert loc.translate_texts(["IL-6", "Muskeln [1]."], "Türkisch") == ["IL-6", "Kaslar [1]."]
    prompt = chat.call_args.kwargs["messages"][0]["content"]
    assert "Türkisch" in prompt and "### Text 2\nMuskeln [1]." in prompt


def test_translate_texts_truncated_is_an_error():
    with patch("graph.localize.ollama.chat", return_value=texts_answer([], "length")):
        with pytest.raises(ValueError):
            loc.translate_texts(["Muskeln"], "Englisch")


def test_translate_texts_empty_needs_no_llm():
    with patch("graph.localize.ollama.chat") as chat:
        assert loc.translate_texts([], "Deutsch") == []
    chat.assert_not_called()
