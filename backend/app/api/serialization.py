"""Timestamp serialisation.

SQLite has no timezone-aware column type, so a `DateTime(timezone=True)`
value read back from it is NAIVE even though it was written as UTC. Emitting
that naively over JSON makes browsers parse it as LOCAL time, which silently
shifts every timestamp in the UI by the viewer's offset -- "just now" becomes
"6h ago" for anyone outside UTC.

Everything the API emits goes through here, so the offset is always explicit.
"""
from datetime import datetime, timezone


def iso_utc(value: datetime | None) -> str | None:
    """ISO 8601 with an explicit offset. Naive values are assumed to be UTC,
    which is what the application always writes."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()
