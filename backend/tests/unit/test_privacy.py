from services.privacy import contains_pii, redact_pii


def test_redacts_email_phone_and_identity_number():
    text = "contact a@example.com or +86 138-0000-0000 id 11010119900307123X"
    redacted = redact_pii(text)
    assert "a@example.com" not in redacted
    assert "138-0000-0000" not in redacted
    assert "11010119900307123X" not in redacted
    assert "[REDACTED_EMAIL]" in redacted
    assert "[REDACTED_PHONE]" in redacted
    assert "[REDACTED_ID]" in redacted


def test_contains_pii_false_for_plain_text():
    assert not contains_pii("no sensitive values here")
