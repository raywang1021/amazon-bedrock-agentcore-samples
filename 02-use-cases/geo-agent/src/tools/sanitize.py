"""Sanitize fetched web content to mitigate indirect prompt injection."""

import re
import unicodedata


# Patterns commonly used in prompt injection attempts
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"ignore\s+(all\s+)?above\s+instructions",
    r"disregard\s+(all\s+)?previous",
    r"forget\s+(all\s+)?(your\s+)?instructions",
    r"you\s+are\s+now\s+a",
    r"new\s+instructions?\s*:",
    r"system\s*:",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"\[INST\]",
    r"\[/INST\]",
    r"<<SYS>>",
    r"<</SYS>>",
    r"Human\s*:",
    r"Assistant\s*:",
]

_INJECTION_RE = re.compile(
    "|".join(_INJECTION_PATTERNS), re.IGNORECASE
)

# HTML comments: <!-- ... -->
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# Zero-width and invisible unicode categories
_INVISIBLE_CATEGORIES = {"Cf", "Cc", "Co"}
# Keep common whitespace
_KEEP_CHARS = {"\n", "\r", "\t", " "}


def sanitize_web_content(text: str) -> str:
    """Clean fetched web text to reduce prompt injection risk.

    1. Strip HTML comments
    2. Remove invisible unicode characters
    3. Redact known prompt injection patterns
    """
    # 1. Remove HTML comments
    text = _HTML_COMMENT_RE.sub("", text)

    # 2. Remove invisible unicode characters (keep normal whitespace)
    text = "".join(
        ch for ch in text
        if ch in _KEEP_CHARS or unicodedata.category(ch) not in _INVISIBLE_CATEGORIES
    )

    # 3. Redact injection patterns
    text = _INJECTION_RE.sub("[REDACTED]", text)

    return text.strip()
