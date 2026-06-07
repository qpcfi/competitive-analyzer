import os

import httpx

from .base import PublishResult


class MCPHttpPublisher:
    def __init__(self, channel: str) -> None:
        self.channel = channel
        prefix = channel.upper()
        self.endpoint = os.environ.get(f"{prefix}_MCP_PUBLISH_URL", "")
        self.token = os.environ.get(f"{prefix}_MCP_TOKEN", "")

    async def publish(
        self,
        title: str,
        content: str,
        images: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> PublishResult:
        if not self.endpoint:
            return PublishResult(
                channel=self.channel,
                status="configuration_required",
                external_post_id=None,
                post_url=None,
                raw_response={"title": title, "content": content, "images": images or [], "tags": tags or []},
            )
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.post(
                self.endpoint,
                headers=headers,
                json={"title": title, "content": content, "images": images or [], "tags": tags or []},
            )
            response.raise_for_status()
            data = response.json()
        return PublishResult(
            channel=self.channel,
            status=str(data.get("status") or "published"),
            external_post_id=data.get("post_id") or data.get("id"),
            post_url=data.get("post_url") or data.get("url"),
            raw_response=data,
        )
