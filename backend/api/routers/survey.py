from fastapi import APIRouter, HTTPException, Query

from core.runtime import runner
from models_db import async_session
from schemas import (
    SurveyCreatePlatformRequest,
    SurveyGenerateRequest,
    SurveyPosterGenerateRequest,
    SurveyPublishPostRequest,
    SurveyQuestionnaireUpdateRequest,
    SurveyRecruitmentPostUpdateRequest,
    SurveyRefreshReportRequest,
    SurveyResponsesImportRequest,
)
from services.report_refresh import refresh_report_with_survey
from services.repositories import get_task, new_run_id, set_task_run
from services.survey_posters import generate_survey_poster
from services.survey_campaigns import (
    approve_survey,
    create_platform_survey,
    generate_survey_for_task,
    get_task_survey,
    import_survey_responses,
    list_task_surveys,
    list_responses,
    publish_recruitment_post,
    save_questionnaire,
    save_recruitment_posts,
    sync_platform_responses,
)

router = APIRouter()


@router.post("/api/v1/tasks/{task_id}/survey/generate")
async def generate_survey(task_id: str, req: SurveyGenerateRequest):
    try:
        return await generate_survey_for_task(task_id, platform=req.platform, channels=req.channels)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")


@router.get("/api/v1/tasks/{task_id}/survey")
async def get_survey(task_id: str, campaign_id: str | None = Query(default=None)):
    item = await get_task_survey(task_id, campaign_id=campaign_id)
    if not item:
        raise HTTPException(status_code=404, detail="Survey campaign not found")
    return item


@router.get("/api/v1/tasks/{task_id}/survey/campaigns")
async def list_survey_campaigns(task_id: str, retention_days: int | None = Query(default=30, ge=0, le=365)):
    try:
        return await list_task_surveys(task_id, retention_days=retention_days)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")


@router.put("/api/v1/tasks/{task_id}/survey/questionnaire")
async def update_survey_questionnaire(task_id: str, req: SurveyQuestionnaireUpdateRequest):
    try:
        return await save_questionnaire(task_id, req.questionnaire, campaign_id=req.campaign_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Survey campaign not found")


@router.put("/api/v1/tasks/{task_id}/survey/recruitment-post")
async def update_survey_recruitment_post(task_id: str, req: SurveyRecruitmentPostUpdateRequest):
    try:
        return await save_recruitment_posts(task_id, req.recruitment_posts, campaign_id=req.campaign_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Survey campaign not found")


@router.post("/api/v1/tasks/{task_id}/survey/approve")
async def approve_task_survey(task_id: str, req: SurveyCreatePlatformRequest | None = None):
    try:
        return await approve_survey(task_id, campaign_id=req.campaign_id if req else None)
    except KeyError:
        raise HTTPException(status_code=404, detail="Survey campaign not found")


@router.post("/api/v1/tasks/{task_id}/survey/create-platform-survey")
async def create_task_platform_survey(task_id: str, req: SurveyCreatePlatformRequest):
    try:
        return await create_platform_survey(task_id, platform=req.platform, survey_url=req.survey_url, campaign_id=req.campaign_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Survey campaign not found")


@router.post("/api/v1/tasks/{task_id}/survey/publish-post")
async def publish_task_survey_post(task_id: str, req: SurveyPublishPostRequest):
    try:
        return await publish_recruitment_post(task_id, channel=req.channel, images=req.images, tags=req.tags, campaign_id=req.campaign_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Survey campaign not found")


@router.post("/api/v1/tasks/{task_id}/survey/generate-poster")
async def generate_task_survey_poster(task_id: str, req: SurveyPosterGenerateRequest):
    try:
        return await generate_survey_poster(task_id, channel=req.channel, campaign_id=req.campaign_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Survey campaign not found")


@router.post("/api/v1/tasks/{task_id}/survey/responses")
async def import_task_survey_responses(task_id: str, req: SurveyResponsesImportRequest):
    try:
        return await import_survey_responses(task_id, req.responses, source=req.source, campaign_id=req.campaign_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Survey campaign not found")


@router.get("/api/v1/tasks/{task_id}/survey/responses")
async def list_task_survey_responses(task_id: str, campaign_id: str | None = Query(default=None)):
    try:
        return await list_responses(task_id, campaign_id=campaign_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Survey campaign not found")


@router.post("/api/v1/tasks/{task_id}/survey/sync-responses")
async def sync_task_survey_responses(task_id: str, req: SurveyCreatePlatformRequest | None = None):
    try:
        return await sync_platform_responses(task_id, campaign_id=req.campaign_id if req else None)
    except KeyError:
        raise HTTPException(status_code=404, detail="Survey campaign not found")


@router.post("/api/v1/tasks/{task_id}/survey/refresh-report")
async def refresh_task_report_with_survey(task_id: str, req: SurveyRefreshReportRequest):
    run_id = new_run_id()
    if not runner.claim(task_id, run_id):
        raise HTTPException(status_code=409, detail="A pipeline is already running. Wait for it to complete or pause it first.")

    try:
        async with async_session() as session:
            task = await get_task(session, task_id)
            if not task:
                raise KeyError(task_id)
            await set_task_run(session, task_id, run_id)
            await session.commit()

        return await refresh_report_with_survey(task_id, run_id, response_ids=req.response_ids, campaign_id=req.campaign_id)
    except KeyError as exc:
        detail = "Task not found" if str(exc).strip("'") == task_id else "Survey campaign not found"
        raise HTTPException(status_code=404, detail=detail)
    finally:
        runner.release(task_id, run_id)
