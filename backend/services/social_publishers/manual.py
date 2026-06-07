from .base import PublishResult


class ManualPublisher:
    channel = "manual"

    async def publish(
        self,
        title: str,
        content: str,
        images: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> PublishResult:
        return PublishResult(
            channel=self.channel,
            status="manual_required",
            external_post_id=None,
            post_url=None,
            raw_response={"title": title, "content": content, "images": images or [], "tags": tags or []},
        )
