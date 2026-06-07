from typing import Any

import httpx

from agents.survey import survey_node
from models_db import async_session
from services.pipeline import publish_event
from services.repositories import (
    create_survey_campaign,
    get_survey_campaign,
    get_task,
    latest_schema,
    latest_survey_campaign,
    list_survey_artifacts,
    list_survey_campaigns,
    list_survey_responses,
    save_survey_artifact,
    save_survey_responses,
    update_survey_campaign,
)
from services.serialization import serialize_survey_campaign, serialize_survey_response
from services.social_publishers import XiaohongshuMCPPublisher
from services.survey_platforms import ManualSurveyPlatform, TencentWenjuanSurveyPlatform, WenjuanxingSurveyPlatform


async def generate_survey_for_task(
    task_id: str,
    *,
    platform: str = "manual",
    channels: list[str] | None = None,
) -> dict[str, Any]:
    async with async_session() as session:
        task = await get_task(session, task_id)
        if not task:
            raise KeyError(task_id)
        schema_record = await latest_schema(session, task_id)
        state = {
            "task_id": task_id,
            "task_context": {
                "domain": task.domain,
                "main_product": task.main_product,
                "competitors": task.competitors or [],
                "execution_mode": task.execution_mode,
                "predefined_schema": [],
            },
            "schema_version": schema_record.version if schema_record else 1,
            "dynamic_schema": schema_record.schema_json if schema_record else (task.dynamic_schema or {}),
            "raw_materials": task.raw_materials or [],
            "source_ids": [],
            "analysis_results": task.analysis_results or {},
            "critic_feedback": [],
            "suggested_schema_extensions": [],
            "task_events": [],
            "progress": task.progress or 0,
            "module_updates": [],
            "retry_counts": {},
        }
    survey_output = await survey_node(state)
    async with async_session() as session:
        campaign = await create_survey_campaign(
            session,
            task_id,
            platform=platform,
            objective=f"{state['task_context']['domain']} 用户体验与购买决策调研",
            target_persona="当前或潜在用户",
            channels=channels or ["xiaohongshu"],
        )
        await save_survey_artifact(session, campaign.id, artifact_type="questionnaire", content_json=survey_output["questionnaire"])
        await save_survey_artifact(session, campaign.id, artifact_type="recruitment_post", content_json=survey_output["recruitment_posts"])
        await update_survey_campaign(session, campaign.id, status="review")
        artifacts = await list_survey_artifacts(session, campaign.id)
        refreshed = await get_survey_campaign(session, campaign.id)
        await session.commit()
    await publish_event(task_id, "survey_ready", {"campaign_id": campaign.id, "status": "review"})
    return serialize_survey_campaign(refreshed, artifacts)


async def get_task_survey(task_id: str, campaign_id: str | None = None) -> dict[str, Any] | None:
    async with async_session() as session:
        campaign = await selected_survey_campaign(session, task_id, campaign_id)
        if not campaign:
            return None
        artifacts = await list_survey_artifacts(session, campaign.id)
        return serialize_survey_campaign(campaign, artifacts)


async def list_task_surveys(task_id: str, retention_days: int | None = None) -> dict[str, Any]:
    async with async_session() as session:
        task = await get_task(session, task_id)
        if not task:
            raise KeyError(task_id)
        campaigns = await list_survey_campaigns(session, task_id, retention_days=retention_days)
        items = []
        for campaign in campaigns:
            artifacts = await list_survey_artifacts(session, campaign.id)
            items.append(serialize_survey_campaign(campaign, artifacts))
    return {"items": items, "retention_days": retention_days}


async def save_questionnaire(task_id: str, questionnaire: dict[str, Any], campaign_id: str | None = None) -> dict[str, Any]:
    async with async_session() as session:
        campaign = await selected_survey_campaign(session, task_id, campaign_id)
        if not campaign:
            raise KeyError("survey_campaign")
        await save_survey_artifact(session, campaign.id, artifact_type="questionnaire", content_json=questionnaire, status="draft")
        campaign = await update_survey_campaign(session, campaign.id, status="review")
        artifacts = await list_survey_artifacts(session, campaign.id)
        await session.commit()
    await publish_event(task_id, "survey_updated", {"campaign_id": campaign.id, "status": campaign.status})
    return serialize_survey_campaign(campaign, artifacts)


async def save_recruitment_posts(task_id: str, recruitment_posts: dict[str, Any], campaign_id: str | None = None) -> dict[str, Any]:
    async with async_session() as session:
        campaign = await selected_survey_campaign(session, task_id, campaign_id)
        if not campaign:
            raise KeyError("survey_campaign")
        await save_survey_artifact(session, campaign.id, artifact_type="recruitment_post", content_json=recruitment_posts, status="draft")
        campaign = await update_survey_campaign(session, campaign.id, status="review")
        artifacts = await list_survey_artifacts(session, campaign.id)
        await session.commit()
    await publish_event(task_id, "survey_updated", {"campaign_id": campaign.id, "status": campaign.status})
    return serialize_survey_campaign(campaign, artifacts)


async def approve_survey(task_id: str, campaign_id: str | None = None) -> dict[str, Any]:
    async with async_session() as session:
        campaign = await selected_survey_campaign(session, task_id, campaign_id)
        if not campaign:
            raise KeyError("survey_campaign")
        artifacts = await list_survey_artifacts(session, campaign.id)
        for artifact in artifacts:
            artifact.status = "approved"
        campaign = await update_survey_campaign(session, campaign.id, status="approved")
        await session.commit()
    await publish_event(task_id, "survey_approved", {"campaign_id": campaign.id, "status": "approved"})
    return serialize_survey_campaign(campaign, artifacts)


async def create_platform_survey(task_id: str, platform: str | None = None, survey_url: str | None = None, campaign_id: str | None = None) -> dict[str, Any]:
    async with async_session() as session:
        campaign = await selected_survey_campaign(session, task_id, campaign_id)
        if not campaign:
            raise KeyError("survey_campaign")
        artifacts = await list_survey_artifacts(session, campaign.id)
        questionnaire = next((a.content_json for a in artifacts if a.type == "questionnaire"), {})
    selected = platform or campaign.platform or "manual"
    if selected == "tencent_wenjuan":
        adapter = TencentWenjuanSurveyPlatform()
    elif selected == "wenjuanxing":
        adapter = WenjuanxingSurveyPlatform()
    else:
        adapter = ManualSurveyPlatform()
    result = await adapter.create_survey(questionnaire)
    final_url = survey_url or result.survey_url
    campaign_status = "created" if final_url else ("approved" if result.status in {"manual_required", "configuration_required"} else result.status)
    async with async_session() as session:
        campaign = await update_survey_campaign(
            session,
            campaign.id,
            platform=result.platform,
            external_survey_id=result.external_survey_id,
            survey_url=final_url,
            status=campaign_status,
        )
        artifacts = await list_survey_artifacts(session, campaign.id)
        await session.commit()
    await publish_event(task_id, "survey_platform_created", {"campaign_id": campaign.id, "platform": result.platform, "survey_url": final_url})
    return {
        **serialize_survey_campaign(campaign, artifacts),
        "platform_status": result.status,
        "platform_result": result.raw_response,
    }


async def publish_recruitment_post(
    task_id: str,
    channel: str = "xiaohongshu",
    images: list[str] | None = None,
    tags: list[str] | None = None,
    campaign_id: str | None = None,
) -> dict[str, Any]:
    channel = "xiaohongshu"
    async with async_session() as session:
        campaign = await selected_survey_campaign(session, task_id, campaign_id)
        if not campaign:
            raise KeyError("survey_campaign")
        artifacts = await list_survey_artifacts(session, campaign.id)
        posts = next((a.content_json for a in artifacts if a.type == "recruitment_post"), {})
    post = posts.get(channel) if isinstance(posts, dict) else None
    if not isinstance(post, dict):
        post = {}
    survey_url = campaign.survey_url or "{survey_url}"
    title = str(post.get("title") or "用户体验调研")
    content = str(post.get("content") or "欢迎参与调研：{survey_url}").replace("{survey_url}", survey_url)
    if campaign.survey_url and campaign.survey_url not in content:
        content = f"{content}\n\n问卷链接：{campaign.survey_url}"
    publisher = XiaohongshuMCPPublisher()
    result = await publisher.publish(title, content, images, tags)
    async with async_session() as session:
        status = "collecting" if result.status in {"published", "manual_required", "configuration_required", "validation_required"} else campaign.status
        campaign = await update_survey_campaign(session, campaign.id, status=status)
        artifacts = await list_survey_artifacts(session, campaign.id)
        await session.commit()
    await publish_event(task_id, "survey_post_published", {"campaign_id": campaign.id, "channel": channel, "status": result.status})
    return {
        **serialize_survey_campaign(campaign, artifacts),
        "publish_result": result.raw_response,
        "publish_status": result.status,
        "post_id": result.external_post_id,
        "post_url": result.post_url,
    }


async def import_survey_responses(task_id: str, responses: list[dict[str, Any]], source: str = "manual", campaign_id: str | None = None) -> dict[str, Any]:
    async with async_session() as session:
        campaign = await selected_survey_campaign(session, task_id, campaign_id)
        if not campaign:
            raise KeyError("survey_campaign")
        records = await save_survey_responses(session, campaign.id, responses, source=source)
        artifacts = await list_survey_artifacts(session, campaign.id)
        refreshed = await get_survey_campaign(session, campaign.id)
        await session.commit()
    await publish_event(task_id, "survey_responses_imported", {"campaign_id": campaign.id, "imported": len(records), "response_count": refreshed.response_count})
    return {**serialize_survey_campaign(refreshed, artifacts), "imported": len(records)}


async def sync_platform_responses(task_id: str, campaign_id: str | None = None) -> dict[str, Any]:
    async with async_session() as session:
        campaign = await selected_survey_campaign(session, task_id, campaign_id)
        if not campaign:
            raise KeyError("survey_campaign")
    if campaign.platform not in {"tencent_wenjuan", "wenjuanxing"} or not campaign.external_survey_id:
        return {"status": "skipped", "reason": "No sync-capable platform survey configured."}
    if campaign.platform == "tencent_wenjuan":
        adapter = TencentWenjuanSurveyPlatform()
    else:
        adapter = WenjuanxingSurveyPlatform()
    try:
        responses = await adapter.sync_responses(campaign.external_survey_id)
    except httpx.HTTPError as exc:
        return {"status": "failed", "reason": str(exc), "platform": campaign.platform}
    return await import_survey_responses(task_id, responses, source=campaign.platform, campaign_id=campaign.id)


async def list_responses(task_id: str, campaign_id: str | None = None) -> dict[str, Any]:
    async with async_session() as session:
        campaign = await selected_survey_campaign(session, task_id, campaign_id)
        if not campaign:
            raise KeyError("survey_campaign")
        responses = await list_survey_responses(session, campaign.id)
    return {"campaign_id": campaign.id, "items": [serialize_survey_response(item) for item in responses]}


async def selected_survey_campaign(session, task_id: str, campaign_id: str | None = None):
    if not campaign_id:
        return await latest_survey_campaign(session, task_id)
    campaign = await get_survey_campaign(session, campaign_id)
    if not campaign or campaign.task_id != task_id:
        return None
    return campaign
