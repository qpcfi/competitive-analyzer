from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


@dataclass(slots=True)
class AccessDecision:
    source_url: str
    access_status: str
    allowed: bool
    reason: str | None = None


async def check_public_access(source_url: str, user_agent: str = "*", timeout: float = 5.0) -> AccessDecision:
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return AccessDecision(source_url, "error", False, "invalid_url")

    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(robots_url)
    except httpx.TimeoutException:
        return AccessDecision(source_url, "timeout", False, "robots_timeout")
    except httpx.HTTPError as exc:
        return AccessDecision(source_url, "error", False, exc.__class__.__name__)

    if response.status_code >= 400:
        return AccessDecision(source_url, "allowed", True, "robots_unavailable")

    path = parsed.path or "/"
    blocked = _path_disallowed(response.text, path, user_agent)
    if blocked:
        return AccessDecision(source_url, "blocked", False, "robots_disallow")
    return AccessDecision(source_url, "allowed", True, "robots_allow")


def _path_disallowed(robots_text: str, path: str, user_agent: str) -> bool:
    applies = False
    disallowed: list[str] = []
    for raw_line in robots_text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = [part.strip() for part in line.split(":", 1)]
        key_l = key.lower()
        if key_l == "user-agent":
            applies = value == "*" or value.lower() == user_agent.lower()
        elif applies and key_l == "disallow" and value:
            disallowed.append(value)
    return any(path.startswith(rule) for rule in disallowed)
