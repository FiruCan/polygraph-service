"""
Gemeinsame Test-Einstellungen: eine echte llm.json im Projektordner gilt in
den Tests nicht, alle LLM-Aufrufe gehen an das (gemockte) lokale Ollama. Der
Serverstart rechnet keine Embeddings vor (das ginge an ein echtes Ollama).
"""

import pytest


@pytest.fixture(autouse=True)
def no_llm_config(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYGRAPH_LLM_CONFIG", str(tmp_path / "keine-llm.json"))
    monkeypatch.setenv("POLYGRAPH_WARM_EMBEDDINGS", "0")
