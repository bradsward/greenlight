"""
Best-effort redaction for anything greenlight writes to disk that came from
the traffic it relays.

By default a session log holds metadata only: methods, ids, latencies, and
the text of errors. With --capture-payloads it also holds request params and
result content, which routinely contain credentials (an `Authorization`
argument, a token in a URL, a key a tool echoes back). Everything goes
through here *before* it's written, so a secret this catches never reaches
the file.

It is not a guarantee. It recognizes secret-looking key names and a list of
well-known secret shapes; a secret in free text that matches neither gets
through. That's why payload capture is opt-in, and why the log file is
created owner-only.
"""
from __future__ import annotations

import json
import re

REDACTED = "[redacted]"
MAX_DEPTH = 40

# Matched against a key with case, "-" and "_" removed, so `apiKey`,
# `api_key` and `X-API-Key` are all "apikey".
_SECRET_KEY_PARTS = (
    "token", "secret", "password", "passwd", "passphrase", "apikey", "authorization",
    "credential", "privatekey", "cookie", "bearer",
)

_SECRET_PATTERNS = [
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}"),                  # OpenAI / Anthropic style keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),                          # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),                       # Slack
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                                   # AWS access key id
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),                             # Google API key
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),  # JWT
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"),                        # user:password@host
]

_BASE64_BLOB = re.compile(r"^[A-Za-z0-9+/=_\-]+$")
_BLOB_MIN = 256


def _is_secret_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.lower().replace("-", "").replace("_", "")
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def redact_text(text: str) -> str:
    """Replace well-known secret shapes inside a string."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def _redact_string(value: str) -> str:
    # A long run of base64-ish characters with no whitespace is a blob
    # (an image, a file), not something worth storing: note its size.
    if len(value) >= _BLOB_MIN and _BASE64_BLOB.match(value):
        return f"<{len(value)} chars, base64-like>"
    return redact_text(value)


def redact(value: object, _depth: int = 0) -> object:
    """A copy of a JSON-like value with secrets removed. Never raises."""
    if _depth > MAX_DEPTH:
        return "<nested too deeply>"
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if _is_secret_key(key) and item is not None and not isinstance(item, (bool, int, float)):
                out[key] = REDACTED
            else:
                out[key] = redact(item, _depth + 1)
        return out
    if isinstance(value, list):
        return [redact(item, _depth + 1) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def to_payload(value: object, limit: int) -> tuple[str, bool]:
    """Redacted, compact JSON text of `value`, cut to `limit` characters.
    Returns (text, was_truncated). Never raises."""
    try:
        text = json.dumps(redact(value), ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return "<unserializable>", False
    if len(text) > limit:
        return text[:limit], True
    return text, False
