"""
Omoikane - Secret redaction (spec §11.2).

Hard gate that runs before any activity event is written to disk.
Strips API keys, tokens, passwords, private keys, and high-entropy
secrets that look like credentials. The Book is a durable artifact —
it must never persist live credentials.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

REDACTION_PLACEHOLDER = "[REDACTED]"

# Patterns are intentionally broad: false positives are acceptable, leaks are not.
_PATTERNS: List[re.Pattern] = [
    # OpenAI / Anthropic / generic provider keys
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"sk-ant-(?:api\d+-)?[A-Za-z0-9_\-]{20,}"),
    # AWS access keys
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ASIA[0-9A-Z]{16}"),
    # GitHub tokens
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    # Slack tokens
    re.compile(r"xox[abposr]-[A-Za-z0-9-]{10,}"),
    # Google API keys
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    # JWT (three base64url segments)
    re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    # PEM private key blocks
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
    # Bearer tokens in HTTP headers
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.=]{16,}"),
]

# Keys whose *values* are always redacted regardless of content.
_SENSITIVE_KEYS = {
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "access_token", "refresh_token", "client_secret", "private_key",
    "authorization", "auth",
}

# Inline key=value patterns ("API_KEY=abc123", "password: hunter2", etc.)
_KV_PATTERN = re.compile(
    r"(?i)\b(" + "|".join(re.escape(k) for k in _SENSITIVE_KEYS) +
    r")\s*[:=]\s*[\"']?([^\s\"',;]{4,})[\"']?"
)


def redact_text(value: str) -> str:
    """Apply all secret patterns to a string."""
    if not isinstance(value, str) or not value:
        return value
    result = value
    for pat in _PATTERNS:
        result = pat.sub(REDACTION_PLACEHOLDER, result)
    result = _KV_PATTERN.sub(lambda m: f"{m.group(1)}={REDACTION_PLACEHOLDER}", result)
    return result


def redact(value: Any) -> Any:
    """Recursively redact secrets in any JSON-serializable value.

    - Strings: regex-scrubbed.
    - Dicts: values for sensitive keys replaced wholesale; other values recursed.
    - Lists/tuples: recursed element-wise.
    - Other primitives: returned untouched.
    """
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in _SENSITIVE_KEYS:
                out[k] = REDACTION_PLACEHOLDER
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value
