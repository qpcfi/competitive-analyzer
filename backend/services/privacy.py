import re


EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s\-()]{7,}\d)(?!\d)")
CN_ID_RE = re.compile(r"\b\d{17}[\dXx]\b")


def redact_pii(text: str) -> str:
    if not text:
        return text
    redacted = EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    redacted = CN_ID_RE.sub("[REDACTED_ID]", redacted)
    redacted = PHONE_RE.sub("[REDACTED_PHONE]", redacted)
    return redacted


def contains_pii(text: str) -> bool:
    if not text:
        return False
    return any(pattern.search(text) for pattern in (EMAIL_RE, PHONE_RE, CN_ID_RE))
