"""Settings file and a small Claude API client (standard library only).

Claude is optional.  Every feature that uses it has an offline fallback, so
the app works with no key and no internet.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

MODEL = "claude-sonnet-5-5"
API_URL = "https://api.anthropic.com/v1/messages"


class ClaudeError(RuntimeError):
    pass


def settings_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "FieldReportBuilder")


def _settings_path() -> str:
    return os.path.join(settings_dir(), "settings.json")


def load_settings() -> dict:
    try:
        with open(_settings_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_setting(name: str, value) -> None:
    settings = load_settings()
    settings[name] = value
    os.makedirs(settings_dir(), exist_ok=True)
    with open(_settings_path(), "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=1)


def api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or load_settings().get("anthropic_api_key") or None


def save_api_key(key: str) -> None:
    save_setting("anthropic_api_key", key.strip())


def call(messages: list[dict], system: str, max_tokens: int = 1500, tools: list[dict] | None = None,
         tool_choice: dict | None = None, timeout: float = 60.0, key: str | None = None) -> dict:
    """POST to the Messages API and return the parsed response.  Raises ClaudeError."""
    key = key or api_key()
    if not key:
        raise ClaudeError("No Claude API key set")
    body = {"model": MODEL, "max_tokens": max_tokens, "system": system, "messages": messages}
    if tools:
        body["tools"] = tools
    if tool_choice:
        body["tool_choice"] = tool_choice
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode(), method="POST",
        headers={"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise ClaudeError(f"Claude API error {e.code}: {detail}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ClaudeError(f"Could not reach the Claude API: {e}") from e


def tool_input(response: dict, name: str) -> dict:
    for block in response.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == name:
            return block.get("input") or {}
    raise ClaudeError(f"Claude did not call {name}")


def text_of(response: dict) -> str:
    return "".join(b.get("text", "") for b in response.get("content", []) if b.get("type") == "text").strip()


def image_block(jpeg: bytes) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(jpeg).decode()}}
