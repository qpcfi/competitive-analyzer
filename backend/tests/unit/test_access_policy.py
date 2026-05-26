import pytest

from services.access_policy import _path_disallowed, check_public_access


def test_path_disallowed_for_matching_rule():
    robots = "User-agent: *\nDisallow: /private"
    assert _path_disallowed(robots, "/private/page", "*")
    assert not _path_disallowed(robots, "/public/page", "*")


@pytest.mark.asyncio
async def test_invalid_url_returns_error_decision():
    decision = await check_public_access("not-a-url")
    assert decision.access_status == "error"
    assert not decision.allowed
