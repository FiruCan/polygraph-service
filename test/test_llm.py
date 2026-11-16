"""
Unit-Tests fuer graph/llm.py (Anbieter aus llm.json). ollama.chat und
httpx.post werden gemockt - kein Server noetig.
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from graph import llm

OPENCODE = {"type": "openai", "base_url": "100.93.10.11:8888/v1", "api_key": "test-key"}


@pytest.fixture
def write_config(tmp_path, monkeypatch):
    path = tmp_path / "llm.json"
    monkeypatch.setenv("POLYGRAPH_LLM_CONFIG", str(path))

    def write(data, mtime=None):
        path.write_text(json.dumps(data) if isinstance(data, dict) else data, encoding="utf-8")
        if mtime:
            os.utime(path, (mtime, mtime))
    return write


def http_reply(payload):
    response = MagicMock(is_error=False)
    response.json.return_value = payload
    return response


def completion(content="", tool_calls=None, finish_reason="stop"):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return http_reply({"choices": [{"message": message, "finish_reason": finish_reason}]})


def test_without_config_local_ollama_as_before():
    with patch("graph.llm.ollama.chat", return_value={"message": {"content": "ok"}}) as chat:
        assert llm.chat("ask", messages=[], think=False)["message"]["content"] == "ok"
    assert chat.call_args.kwargs == {"model": "gemma4:26b", "messages": [], "think": False}
    with patch("graph.llm.ollama.embed", return_value={"embeddings": [[1.0]]}) as embed:
        llm.embed("Muskeln")
    assert embed.call_args.kwargs == {"model": "bge-m3", "input": "Muskeln"}


def test_openai_chat_translates_request_and_answer(write_config):
    write_config({"providers": {"opencode": OPENCODE}, "chat": {"provider": "opencode", "model": "qwen"}})
    schema = {"type": "object"}
    with patch("graph.llm.httpx.post", return_value=completion('{"a": 1}')) as post:
        response = llm.chat("normalize", messages=[{"role": "user", "content": "Hallo"}], think=False,
                            format=schema, options={"num_predict": 300, "temperature": 0})
    url, body = post.call_args.args[0], post.call_args.kwargs["json"]
    assert url == "http://100.93.10.11:8888/v1/chat/completions"
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer test-key"}
    assert body == {"model": "qwen", "messages": [{"role": "user", "content": "Hallo"}],
                    "max_tokens": 300, "temperature": 0,
                    "response_format": {"type": "json_schema", "json_schema": {"name": "antwort", "schema": schema}}}
    assert response["message"]["content"] == '{"a": 1}'
    assert response["message"]["tool_calls"] == [] and response["done_reason"] == "stop"


def test_openai_length_becomes_done_reason_length(write_config):
    write_config({"providers": {"opencode": OPENCODE}, "chat": {"provider": "opencode", "model": "qwen"}})
    with patch("graph.llm.httpx.post", return_value=completion("[", finish_reason="length")):
        assert llm.chat("ask", messages=[])["done_reason"] == "length"


def test_task_overrides_provider_and_model(write_config):
    write_config({"providers": {"opencode": OPENCODE, "ollama": {"type": "ollama"}},
                  "chat": {"provider": "opencode", "model": "qwen"},
                  "tasks": {"translate": {"provider": "ollama", "model": "gemma4:26b"}}})
    with patch("graph.llm.ollama.chat", return_value={"message": {"content": "ok"}}) as chat, \
         patch("graph.llm.httpx.post") as post:
        llm.chat("translate", messages=[])
    assert chat.call_args.kwargs["model"] == "gemma4:26b" and not post.called


def test_tool_calls_round_trip(write_config):
    write_config({"providers": {"opencode": OPENCODE}, "chat": {"provider": "opencode", "model": "qwen"}})
    call = {"id": "c1", "type": "function", "function": {"name": "suche_knoten", "arguments": '{"begriff": "MS"}'}}
    with patch("graph.llm.httpx.post", return_value=completion(None, [call])):
        message = llm.chat("dedupe", messages=[{"role": "user", "content": "?"}], tools=[{"type": "function"}])["message"]
    assert message["tool_calls"][0]["function"] == {"name": "suche_knoten", "arguments": {"begriff": "MS"}}
    assert message["content"] == ""

    messages = [{"role": "user", "content": "?"}, message,
                {"role": "tool", "tool_name": "suche_knoten", "content": "- multiple sclerosis"}]
    with patch("graph.llm.httpx.post", return_value=completion("fertig")) as post:
        llm.chat("dedupe", messages=messages)
    sent = post.call_args.kwargs["json"]["messages"]
    assert sent[1]["tool_calls"][0] == {"id": "c1", "type": "function", "function": {
        "name": "suche_knoten", "arguments": '{"begriff": "MS"}'}}
    assert sent[2] == {"role": "tool", "tool_call_id": "c1", "content": "- multiple sclerosis"}


def test_tool_answers_get_ids_of_their_calls():
    calls = [{"function": {"name": "a", "arguments": {}}}, {"function": {"name": "b", "arguments": {}}}]
    sent = llm._openai_messages([{"role": "assistant", "content": "", "tool_calls": calls},
                                 {"role": "tool", "tool_name": "b", "content": "B"},
                                 {"role": "tool", "tool_name": "a", "content": "A"}])
    ids = {c["function"]["name"]: c["id"] for c in sent[0]["tool_calls"]}
    assert ids["a"] != ids["b"]
    assert sent[1]["tool_call_id"] == ids["b"] and sent[2]["tool_call_id"] == ids["a"]


def test_openai_embed_keeps_order(write_config):
    write_config({"providers": {"opencode": OPENCODE}, "embed": {"provider": "opencode", "model": "emb"}})
    reply = http_reply({"data": [{"index": 1, "embedding": [2.0]}, {"index": 0, "embedding": [1.0]}]})
    with patch("graph.llm.httpx.post", return_value=reply) as post:
        assert llm.embed(["x", "y"]) == {"embeddings": [[1.0], [2.0]]}
    assert post.call_args.args[0].endswith("/v1/embeddings")


def test_config_reloaded_when_file_changes(write_config):
    write_config({"providers": {"ollama": {"type": "ollama"}}, "chat": {"provider": "ollama", "model": "eins"}}, mtime=1_000_000)
    assert llm.target("chat", "ask")[1] == "eins"
    write_config({"providers": {"ollama": {"type": "ollama"}}, "chat": {"provider": "ollama", "model": "zwei"}}, mtime=2_000_000)
    assert llm.target("chat", "ask")[1] == "zwei"


def test_api_key_from_environment(write_config, monkeypatch):
    monkeypatch.setenv("OPENCODE_KEY", "aus-env")
    provider = {"type": "openai", "base_url": "https://x/v1", "api_key_env": "OPENCODE_KEY"}
    write_config({"providers": {"opencode": provider}, "chat": {"provider": "opencode", "model": "qwen"}})
    with patch("graph.llm.httpx.post", return_value=completion("ok")) as post:
        llm.chat("ask", messages=[])
    assert post.call_args.args[0] == "https://x/v1/chat/completions"
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer aus-env"}


def test_clear_errors_for_bad_config(write_config):
    write_config({"chat": {"provider": "gibtsnicht", "model": "x"}}, mtime=3_000_000)
    with pytest.raises(ValueError, match="gibtsnicht"):
        llm.chat("ask", messages=[])
    write_config("{kaputt", mtime=4_000_000)
    with pytest.raises(ValueError, match="kein gueltiges JSON"):
        llm.chat("ask", messages=[])


def test_server_error_text_in_exception(write_config):
    write_config({"providers": {"opencode": OPENCODE}, "chat": {"provider": "opencode", "model": "qwen"}})
    reply = MagicMock(is_error=True, status_code=400, text="response_format not supported")
    with patch("graph.llm.httpx.post", return_value=reply), pytest.raises(RuntimeError, match="not supported"):
        llm.chat("ask", messages=[])


def test_think_off_and_think_on_fields(write_config):
    provider = {**OPENCODE, "think_off": {"reasoning_effort": "none"}, "think_on": {"reasoning_effort": "medium"}}
    write_config({"providers": {"opencode": provider}, "chat": {"provider": "opencode", "model": "qwen"}})
    with patch("graph.llm.httpx.post", return_value=completion("ok")) as post:
        llm.chat("ask", messages=[], think=False)
        assert post.call_args.kwargs["json"]["reasoning_effort"] == "none"
        llm.chat("ask", messages=[], think=True)
        assert post.call_args.kwargs["json"]["reasoning_effort"] == "medium"


def test_switch_is_one_word(write_config):
    """Das Modell steht beim Anbieter: umschalten = nur "provider" in "chat" aendern."""
    providers = {"ollama": {"type": "ollama", "model": "gemma4:26b"}, "opencode": {**OPENCODE, "model": "qwen"}}
    write_config({"providers": providers, "chat": {"provider": "opencode"}}, mtime=5_000_000)
    assert llm.target("chat", "ask") == (providers["opencode"], "qwen")
    write_config({"providers": providers, "chat": {"provider": "ollama"}}, mtime=6_000_000)
    assert llm.target("chat", "ask") == (providers["ollama"], "gemma4:26b")


def test_no_silent_ollama_when_llm_json_exists(write_config):
    """Fehlt in einer vorhandenen llm.json etwas, gibt es einen Fehler statt still lokalem Ollama."""
    write_config({"providers": {"opencode": OPENCODE}}, mtime=7_000_000)
    with pytest.raises(ValueError, match='"chat" fehlt'):
        llm.target("chat", "ask")
    write_config({"providers": {"x": {"model": "m"}}, "chat": {"provider": "x"}}, mtime=8_000_000)
    with pytest.raises(ValueError, match="braucht"):
        llm.target("chat", "ask")
    write_config({"providers": {"opencode": OPENCODE}, "chat": {"provider": "opencode"}}, mtime=9_000_000)
    with pytest.raises(ValueError, match="kein"):
        llm.target("chat", "ask")


def test_max_tokens_false_sends_no_limit(write_config):
    write_config({"providers": {"opencode": {**OPENCODE, "max_tokens": False}},
                  "chat": {"provider": "opencode", "model": "qwen"}})
    with patch("graph.llm.httpx.post", return_value=completion("ok")) as post:
        llm.chat("ask", messages=[], options={"num_predict": 30})
    assert "max_tokens" not in post.call_args.kwargs["json"]
