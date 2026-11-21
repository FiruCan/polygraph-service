"""
llm.py
------
Eine Stelle fuer alle LLM-Aufrufe (Chat und Embeddings). Welcher Server und
welches Modell, steht in llm.json im Projektordner (Vorlage: llm.example.json),
nicht im Code. Umschalten = Datei aendern, ohne Neustart: die Datei wird neu
gelesen, sobald sie sich aendert. Ohne llm.json laeuft alles wie bisher lokal
ueber Ollama mit gemma4:26b und bge-m3.

Zwei Arten von Anbietern ("type"):
- "ollama": die Ollama-API, lokal oder entfernt ("host", "api_key").
- "openai": jede OpenAI-kompatible API ("base_url", "api_key"), z.B. OpenCode.
  Die Aufrufe kommen im Ollama-Format an und gehen im Ollama-Format zurueck
  (format -> response_format, num_predict -> max_tokens, Tool-Argumente als
  Dict), damit die Aufrufer nichts davon wissen muessen. think gibt es dort
  nicht: bei think=False gehen stattdessen die Felder aus "think_off" des
  Anbieters mit (z.B. {"reasoning_effort": "none"}), bei think=True die aus
  "think_on" (z.B. {"reasoning_effort": "medium"}) - je Server verschieden.

Aufgaben (task): ask, suggest, localize, normalize, dedupe. Ein
Eintrag unter "tasks" ueberschreibt fuer eine Aufgabe Anbieter und/oder Modell
aus "chat". Embeddings kommen immer aus "embed".
"""

import json
import os
import uuid
from typing import Optional

import httpx
import ollama

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "llm.json")
# Nur wenn llm.json fehlt - steht die Datei da, gilt allein ihr Inhalt
DEFAULTS = {
    "providers": {"ollama": {"type": "ollama", "model": "gemma4:26b"}},
    "chat": {"provider": "ollama"},
    "embed": {"provider": "ollama", "model": "bge-m3"},
    "tasks": {},
}
TIMEOUT = 600  # Sekunden; Antworten mit Denkschritt brauchen ueber eine Minute

_loaded = {"key": None, "config": DEFAULTS}
_clients = {}


def config() -> dict:
    """Inhalt von llm.json (nur ohne Datei: DEFAULTS); neu gelesen, wenn sich die Datei aendert."""
    path = os.environ.get("POLYGRAPH_LLM_CONFIG", CONFIG_PATH)
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return DEFAULTS
    if _loaded["key"] != key:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:  # lieber ein klarer Fehler als still ein anderes Modell
            raise ValueError(f"{path} ist kein gueltiges JSON: {e}") from e
        _loaded.update(key=key, config=data)
    return _loaded["config"]


def target(section: str, task: Optional[str] = None) -> tuple:
    """
    -> (Anbieter-Eintrag, Modellname) fuer "chat" (ggf. mit Aufgabe) oder "embed".
    Das Modell steht beim Anbieter, umschalten = nur "provider" in "chat"
    aendern; ein "model" in "chat" oder unter "tasks" geht vor.
    """
    cfg = config()
    if section not in cfg:
        raise ValueError(f'llm.json: "{section}" fehlt')
    entry = dict(cfg[section])
    if task:
        entry.update(cfg.get("tasks", {}).get(task, {}))
    name = entry.get("provider")
    provider = cfg.get("providers", {}).get(name)
    if provider is None:
        raise ValueError(f"llm.json: Anbieter '{name}' steht nicht unter providers")
    if provider.get("type") not in ("ollama", "openai"):
        raise ValueError(f"llm.json: Anbieter '{name}' braucht \"type\": \"ollama\" oder \"openai\"")
    model = entry.get("model") or provider.get("model")
    if not model:
        raise ValueError(f"llm.json: kein \"model\" fuer Anbieter '{name}'")
    return provider, model


def parallel(task: str) -> int:
    """Wie viele Aufrufe einer Aufgabe gleichzeitig laufen duerfen ("parallel" am Anbieter, Standard 1)."""
    provider, _ = target("chat", task)
    return max(1, int(provider.get("parallel", 1)))


def chat(task: str, **kwargs):
    """Wie ollama.chat(model=..., **kwargs); Anbieter und Modell kommen aus llm.json."""
    provider, model = target("chat", task)
    if provider["type"] == "ollama":
        return _ollama(provider).chat(model=model, **kwargs)
    return _openai_chat(provider, model, **kwargs)


def embed(input):
    """Wie ollama.embed(model=..., input=...) -> {"embeddings": [...]}, Modell aus llm.json."""
    provider, model = target("embed")
    if provider["type"] == "ollama":
        return _ollama(provider).embed(model=model, input=input)
    data = _post(provider, "/embeddings", {"model": model, "input": input})["data"]
    return {"embeddings": [d["embedding"] for d in sorted(data, key=lambda d: d["index"])]}


def _api_key(provider: dict) -> str:
    return provider.get("api_key") or os.environ.get(provider.get("api_key_env", ""), "")


def _ollama(provider: dict):
    """Das ollama-Modul selbst (lokal, Standard) oder ein Client fuer einen anderen Host."""
    host, key = provider.get("host"), _api_key(provider)
    if not host and not key:
        return ollama
    if (host, key) not in _clients:
        headers = {"Authorization": f"Bearer {key}"} if key else None
        _clients[(host, key)] = ollama.Client(host=host, headers=headers)
    return _clients[(host, key)]


def _post(provider: dict, path: str, body: dict) -> dict:
    base = provider.get("base_url", "").rstrip("/")
    if "://" not in base:
        base = "http://" + base
    key = _api_key(provider)
    response = httpx.post(base + path, json=body, headers={"Authorization": f"Bearer {key}"} if key else {},
                          timeout=provider.get("timeout", TIMEOUT))
    if response.is_error:  # mit Text des Servers, z.B. "response_format not supported"
        raise RuntimeError(f"{response.status_code} von {base + path}: {response.text[:500]}")
    return response.json()


def _openai_chat(provider: dict, model: str, messages: list, tools=None, think=None, format=None,
                 options=None) -> dict:
    options = options or {}
    body = {"model": model, "messages": _openai_messages(messages)}
    if tools:
        body["tools"] = tools
    # "max_tokens": false am Anbieter = keine Grenze mitschicken, der Server entscheidet
    # (die Grenzen sind fuer Antworten ohne Denken bemessen, Denk-Tokens zaehlen mit)
    if "num_predict" in options and provider.get("max_tokens", True) is not False:
        body["max_tokens"] = options["num_predict"]
    if "temperature" in options:
        body["temperature"] = options["temperature"]
    if think is False:  # Felder je Server, z.B. {"reasoning_effort": "none"}; ohne sie denkt Qwen3 das Budget leer
        body.update(provider.get("think_off", {}))
    elif think is True:  # z.B. {"reasoning_effort": "medium"}; ohne Eintrag entscheidet der Server
        body.update(provider.get("think_on", {}))
    if format == "json":
        body["response_format"] = {"type": "json_object"}
    elif format:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "antwort", "schema": format}}
    choice = _post(provider, "/chat/completions", body)["choices"][0]
    message = choice["message"]
    calls = [{"id": c.get("id"), "function": {"name": c["function"]["name"],
                                               "arguments": _arguments(c["function"].get("arguments"))}}
             for c in message.get("tool_calls") or []]
    return {"message": {"role": "assistant", "content": message.get("content") or "", "tool_calls": calls},
            "done_reason": "length" if choice.get("finish_reason") == "length" else "stop"}


def _arguments(raw) -> dict:
    """OpenAI liefert Tool-Argumente als JSON-Text, Ollama als Dict."""
    if isinstance(raw, dict):
        return raw
    try:
        args = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return args if isinstance(args, dict) else {}


def _openai_messages(messages: list) -> list:
    """
    Ollama-Nachrichten -> OpenAI: Tool-Aufrufe brauchen eine id und Argumente
    als JSON-Text, Tool-Antworten die id des Aufrufs statt des Werkzeugnamens
    (zugeordnet in der Reihenfolge der Aufrufe).
    """
    out, pending = [], []
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            calls = []
            for c in m["tool_calls"]:
                call_id = c.get("id") or f"call_{uuid.uuid4().hex[:12]}"
                fn = c["function"]
                calls.append({"id": call_id, "type": "function", "function": {
                    "name": fn["name"], "arguments": json.dumps(dict(fn["arguments"] or {}), ensure_ascii=False)}})
                pending.append((fn["name"], call_id))
            out.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
        elif role == "tool":
            name = m.get("tool_name")
            match = next((p for p in pending if p[0] == name), pending[0] if pending else None)
            if match:
                pending.remove(match)
            out.append({"role": "tool", "tool_call_id": match[1] if match else "call_0",
                        "content": m.get("content") or ""})
        else:
            out.append({"role": role, "content": m.get("content") or ""})
    return out
