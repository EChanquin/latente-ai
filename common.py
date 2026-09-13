"""Shared helpers: local .env loading, response parsing, and system-prompt extraction."""
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL = "claude-opus-5"

FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def load_env(path=ROOT / ".env"):
    """Load KEY=VALUE lines from a git-ignored .env without overriding variables already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def try_parse(text):
    """Parse a model response as a JSON object.

    Returns (obj, stage): stage is "direct" when the raw text parsed, "stripped" when it only
    parsed after removing markdown fences and whitespace, and None (with obj None) on failure.
    """
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj, "direct"
    except (json.JSONDecodeError, TypeError):
        pass
    stripped = FENCE_RE.sub("", (text or "").strip()).strip()
    try:
        obj = json.loads(stripped)
        if isinstance(obj, dict):
            return obj, "stripped"
    except json.JSONDecodeError:
        pass
    return None, None


def response_text(message):
    """Concatenate the text blocks of a Messages API response."""
    return "".join(block.text for block in message.content if block.type == "text")


def load_system_prompt(path=ROOT / "agent-instructions-v4.txt"):
    """Everything from '## CONTEXT' to the end, minus the Langflow-only '## WRITING THE RESULT' section."""
    text = Path(path).read_text()
    text = text[text.index("## CONTEXT"):]
    section = re.search(r"^## WRITING THE RESULT\b.*?(?=^## )", text, flags=re.DOTALL | re.MULTILINE)
    if not section:
        raise ValueError("'## WRITING THE RESULT' section not found; refusing to send the Langflow tool instructions")
    return (text[:section.start()] + text[section.end():]).strip()
