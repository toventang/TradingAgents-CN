import logging
import contextvars
import re
from collections.abc import Mapping
from typing import Any

# Shared contextvar for trace id across the whole process
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")

REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "api_secret",
    "client_secret",
    "password",
    "private_key",
}
_AUTH_RE = re.compile(
    r"(?i)((?:authorization(?:\s+header(?:格式错误)?)?|token(?:\s*prefix|前\d+位)?)"
    r"\s*[:=]\s*(?:bearer\s+)?)([^\s,;]+)"
)
_QUERY_RE = re.compile(
    r"(?i)([?&](?:token|access_token|refresh_token|authorization|api_key)=)([^&\s]+)"
)
_JSON_RE = re.compile(
    r"""(?i)(["'](?:token|access_token|refresh_token|authorization|api_key)["']\s*:\s*["'])([^"']+)(["'])"""
)
_JWT_RE = re.compile(
    r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}(?![A-Za-z0-9_-])"
)


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).strip().lower()
    if normalized == "max_tokens":
        return False
    return (
        normalized in _SENSITIVE_KEYS
        or normalized.endswith("_token")
        or normalized.endswith("_secret")
        or normalized.endswith("_password")
    )


def redact_sensitive_mapping(value: Any) -> Any:
    """Recursively redact sensitive mapping fields while preserving structure."""
    if isinstance(value, Mapping):
        return {
            key: REDACTED if _is_sensitive_key(key) else redact_sensitive_mapping(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_mapping(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_mapping(item) for item in value)
    return value


def redact_sensitive_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    redacted = _AUTH_RE.sub(r"\1" + REDACTED, value)
    redacted = _QUERY_RE.sub(r"\1" + REDACTED, redacted)
    redacted = _JSON_RE.sub(r"\1" + REDACTED + r"\3", redacted)
    return _JWT_RE.sub(REDACTED, redacted)


class LoggingContextFilter(logging.Filter):
    """Injects trace_id from contextvars into LogRecord.
    Always sets record.trace_id to a string (default '-') so formatters are safe.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.trace_id = trace_id_var.get()
        except Exception:
            record.trace_id = "-"
        try:
            record.msg = redact_sensitive_text(record.getMessage())
            record.args = ()
        except Exception:
            record.msg = "[LOG MESSAGE REDACTION FAILED]"
            record.args = ()
        return True
