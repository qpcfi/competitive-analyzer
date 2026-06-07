from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class PublishResult:
    channel: str
    status: str
    external_post_id: str | None
    post_url: str | None
    raw_response: dict[str, Any]


class SocialPublisher(Protocol):
    channel: str

    async def publish(
        self,
        title: str,
        content: str,
        images: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> PublishResult:
        ...
