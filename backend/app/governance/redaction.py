"""PII redaction for audit parameters.

The audit trail records WHAT was attempted, not everyone's personal data.
Redaction happens at WRITE time, not display time: redacting on the way out
would leave the PII sitting in the database for anyone with a SQL client,
which defeats the point.

What survives redaction is enough to answer the questions an auditor
actually asks -- which tool, which appointment, which service, was it
allowed -- while customer names and email addresses do not accumulate in a
table that is deliberately append-only and never deleted.
"""
from typing import Any

#: Parameter names redacted on every tool, matched case-insensitively.
GLOBAL_SENSITIVE_FIELDS = frozenset({
    "customer_email", "email", "customer_name", "name", "phone",
    "customer_phone", "address", "password", "token", "api_key",
})

#: Free-text fields a customer's words land in. Kept as a length marker so
#: the trail still shows that a reason was given.
FREE_TEXT_FIELDS = frozenset({"summary", "reason", "query", "note"})

REDACTED = "[redacted]"
MAX_FREE_TEXT = 200


def _redact_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if lowered in GLOBAL_SENSITIVE_FIELDS:
        return REDACTED
    if lowered in FREE_TEXT_FIELDS and isinstance(value, str):
        # Keep short free text (it is operationally useful and rarely PII);
        # truncate long text rather than storing a transcript.
        if len(value) > MAX_FREE_TEXT:
            return value[:MAX_FREE_TEXT] + f"... [truncated, {len(value)} chars]"
        return value
    return value


def redact_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """Return a copy safe to persist in audit_logs."""
    if not params:
        return {}
    out: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, dict):
            out[key] = redact_params(value)
        elif isinstance(value, list):
            out[key] = [
                redact_params(v) if isinstance(v, dict) else _redact_value(key, v)
                for v in value
            ]
        else:
            out[key] = _redact_value(key, value)
    return out
