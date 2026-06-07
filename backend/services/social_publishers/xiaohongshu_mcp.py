import json
import os
import uuid
from typing import Any

import httpx

from .base import PublishResult


class XiaohongshuMCPPublisher:
    channel = "xiaohongshu"

    def __init__(self) -> None:
        self.mcp_url = os.environ.get("XIAOHONGSHU_MCP_URL", "").rstrip("/")
        self.token = os.environ.get("XIAOHONGSHU_MCP_TOKEN", "")
        self.tool_name = os.environ.get("XIAOHONGSHU_MCP_TOOL", "publish_content")

    async def publish(
        self,
        title: str,
        content: str,
        images: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> PublishResult:
        clean_images = [item.strip() for item in (images or []) if item and item.strip()]
        clean_tags = [item.strip().lstrip("#") for item in (tags or []) if item and item.strip()]
        if not self.mcp_url:
            return PublishResult(
                channel=self.channel,
                status="configuration_required",
                external_post_id=None,
                post_url=None,
                raw_response={
                    "message": "Set XIAOHONGSHU_MCP_URL to enable Xiaohongshu MCP publishing.",
                    "title": title,
                    "content": content,
                    "images": clean_images,
                    "tags": clean_tags,
                },
            )
        if not clean_images:
            return PublishResult(
                channel=self.channel,
                status="validation_required",
                external_post_id=None,
                post_url=None,
                raw_response={
                    "message": "Xiaohongshu publishing requires at least one image URL or local image path.",
                    "title": title,
                    "content": content,
                    "images": clean_images,
                    "tags": clean_tags,
                },
            )

        arguments = {
            "title": title,
            "content": content,
            "images": clean_images,
            "tags": clean_tags,
        }
        try:
            data = await self._call_tool(arguments)
        except httpx.RequestError as exc:
            return PublishResult(
                channel=self.channel,
                status="failed",
                external_post_id=None,
                post_url=None,
                raw_response={
                    "message": f"Cannot connect to Xiaohongshu MCP at {self.mcp_url}.",
                    "error": str(exc),
                    "title": title,
                    "content": content,
                    "images": clean_images,
                    "tags": clean_tags,
                },
            )
        except httpx.HTTPStatusError as exc:
            return PublishResult(
                channel=self.channel,
                status="failed",
                external_post_id=None,
                post_url=None,
                raw_response={
                    "message": f"Xiaohongshu MCP returned HTTP {exc.response.status_code}.",
                    "error": exc.response.text,
                    "title": title,
                    "content": content,
                    "images": clean_images,
                    "tags": clean_tags,
                },
            )
        external_id = first_value(data, ("post_id", "note_id", "id", "publish_id"))
        post_url = first_value(data, ("post_url", "url", "link", "note_url"))
        status = str(data.get("status") or ("published" if external_id or post_url else "published"))
        return PublishResult(
            channel=self.channel,
            status=status,
            external_post_id=str(external_id) if external_id else None,
            post_url=str(post_url) if post_url else None,
            raw_response=data,
        )

    async def _call_tool(self, arguments: dict[str, Any]) -> dict[str, Any]:
        headers = self._headers()
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            init_response = await client.post(
                self.mcp_url,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": str(uuid.uuid4()),
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "competitive-analyzer", "version": "0.1.0"},
                    },
                },
            )
            init_response.raise_for_status()
            session_id = init_response.headers.get("Mcp-Session-Id") or init_response.headers.get("mcp-session-id")
            session_headers = self._headers(session_id=session_id)
            initialized_response = await client.post(
                self.mcp_url,
                headers=session_headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            initialized_response.raise_for_status()
            tool_response = await client.post(
                self.mcp_url,
                headers=session_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": str(uuid.uuid4()),
                    "method": "tools/call",
                    "params": {"name": self.tool_name, "arguments": arguments},
                },
            )
            tool_response.raise_for_status()
            data = parse_mcp_response(tool_response)
        if isinstance(data, dict) and data.get("error"):
            return {"status": "failed", "error": data["error"], "raw_response": data}
        if isinstance(data, dict) and "result" in data:
            return normalize_mcp_result(data["result"])
        return data if isinstance(data, dict) else {"response": data}

    def _headers(self, session_id: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        return headers


def normalize_mcp_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"result": result}
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("json"), dict):
                return item["json"]
            if isinstance(item, dict) and item.get("type") == "text":
                text = str(item.get("text") or "")
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    return {"text": text, "content": content}
    return result


def parse_mcp_response(response: httpx.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" not in content_type:
        return response.json()
    for line in response.text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if not data or data == "[DONE]":
            continue
        parsed = json.loads(data)
        if isinstance(parsed, dict):
            return parsed
    return {"text": response.text}


def first_value(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = data.get(key)
        if value:
            return value
    return None
