"""Treating document content as data, not instructions.

READ THIS BEFORE TRUSTING IT.

Nothing in this module is a security guarantee. Text filtering against
prompt injection is a mitigation, not a control: a sufficiently clever
injection will eventually get past any pattern list, and anyone who tells
you otherwise is selling something.

The actual control is the governance engine. A model that has been fooled
by a document can only PROPOSE a tool call. Permission checks, risk
classification and human approval still stand between that proposal and
the database. tests/test_prompt_injection.py proves this by scripting a
model that fully obeys a malicious document and showing the data survives.

What this module does buy:

1. **Envelope integrity.** Retrieved text is wrapped in a delimited
   envelope. Any occurrence of the delimiter is stripped from the content
   first, so a document cannot close its own envelope and continue as
   though it were the system.
2. **Structural neutralisation.** Line-initial role markers (``Human:``,
   ``Assistant:``, ``System:``) and tags that mimic our own framing are
   defanged, so a chunk cannot fake a turn boundary.
3. **Visibility.** Suspicious passages are flagged at ingest so an
   administrator can look at what was uploaded.
"""
import re

#: Envelope markers. Stripped from content before wrapping, so they cannot
#: appear inside an envelope.
OPEN_TAG = "<<<DOCUMENT_EXCERPT>>>"
CLOSE_TAG = "<<<END_DOCUMENT_EXCERPT>>>"

#: Line-initial markers that imitate a conversation turn.
_ROLE_MARKER = re.compile(
    r"^(\s*)(human|assistant|system|user|ai)(\s*:)", re.IGNORECASE | re.MULTILINE
)

#: Tags that imitate framing, e.g. <system>, </instructions>.
_FAKE_TAG = re.compile(
    r"</?\s*(system|instructions?|prompt|tool_result|tool_use|document_excerpt)"
    r"[^>]{0,80}>",
    re.IGNORECASE,
)

#: Heuristics for flagging, NOT for blocking. Deliberately broad; a hit
#: means "an administrator should look at this", not "this is an attack".
_SUSPICIOUS_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above|earlier)\s+"
        r"(instructions?|prompts?|rules?|messages?)",
        r"disregard\s+(all\s+)?(previous|prior|above|your)\s+\w+",
        r"you\s+are\s+now\s+(a|an|in)\b",
        r"new\s+(system\s+)?instructions?\s*:",
        r"\bsystem\s+override\b",
        r"developer\s+mode",
        r"do\s+not\s+(tell|inform|mention\s+to)\s+(the\s+)?(user|customer|admin)",
        r"without\s+(asking|requiring|seeking)\s+(for\s+)?(approval|permission|confirmation)",
        r"\b(call|invoke|execute|run)\s+(the\s+)?(tool|function)\b",
        r"\b(cancel|delete|remove)\s+all\b",
        r"reveal\s+(your|the)\s+(system\s+)?prompt",
        r"</?\s*(system|instructions?)\s*>",
        r"^\s*(human|assistant|system)\s*:",
    )
]


def looks_suspicious(text: str) -> bool:
    """Heuristic flag for admin review. Never used to allow or deny."""
    return any(p.search(text) for p in _SUSPICIOUS_PATTERNS)


def suspicious_matches(text: str) -> list[str]:
    return [p.pattern for p in _SUSPICIOUS_PATTERNS if p.search(text)]


def neutralise(text: str) -> str:
    """Defang content so it cannot imitate conversation structure.

    Applied at RETRIEVAL, not at ingest: the stored chunk stays faithful to
    the source document, so what an administrator reads back is what they
    uploaded.
    """
    # 1. The envelope must be forgeable by nobody but us.
    cleaned = text.replace(OPEN_TAG, "").replace(CLOSE_TAG, "")
    # 2. Role markers lose their colon, so they read as prose.
    cleaned = _ROLE_MARKER.sub(r"\1\2 ", cleaned)
    # 3. Framing-like tags become inert text.
    cleaned = _FAKE_TAG.sub(lambda m: m.group(0).replace("<", "(").replace(">", ")"), cleaned)
    return cleaned


def wrap_excerpt(text: str, *, source: str, chunk_id: int) -> str:
    """Put one retrieved passage inside a tamper-resistant envelope."""
    return (
        f"{OPEN_TAG}\n"
        f"source: {source} (chunk {chunk_id})\n"
        f"---\n"
        f"{neutralise(text)}\n"
        f"{CLOSE_TAG}"
    )
