from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select

from models_db import LinkVerificationResultRecord, ReportExportRecord, SourceMaterialRecord, async_session
from services.pipeline import publish_event
from services.repositories import get_task, new_id

router = APIRouter()


@router.get("/api/v1/tasks/{task_id}/report")
async def get_report(task_id: str):
    async with async_session() as session:
        task = await get_task(session, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        report = task.final_report or (task.analysis_results or {}).get("report") or {
            "summary": "",
            "findings": [],
            "recommendations": [],
            "source_appendix": task.raw_materials or [],
        }
    return {"task_id": task_id, "report": report}


@router.get("/api/v1/tasks/{task_id}/export")
async def export_report(task_id: str, format: str = Query("json", pattern="^(pdf|markdown|json)$")):
    report_response = await get_report(task_id)
    report = report_response["report"]
    async with async_session() as session:
        session.add(ReportExportRecord(id=new_id("export"), task_id=task_id, format=format, status="completed"))
        await session.commit()
    if format == "json":
        return JSONResponse(report)
    if format == "markdown":
        body = f"# Competitive Analysis Report\n\n{report.get('summary', '')}\n"
        for item in report.get("recommendations", []):
            body += f"\n- {item}"
        return PlainTextResponse(body, media_type="text/markdown")
    body = f"PDF-ready report for {task_id}\n\n{report.get('summary', '')}"
    return PlainTextResponse(body, media_type="application/pdf")


@router.post("/api/v1/tasks/{task_id}/share")
async def share_report(task_id: str):
    token = new_id("report")
    async with async_session() as session:
        if not await get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        session.add(ReportExportRecord(id=new_id("export"), task_id=task_id, format="share", status="completed", share_token=token))
        await session.commit()
    return {"share_url": f"http://localhost:3000/share/{token}", "expires_at": None}


@router.post("/api/v1/tasks/{task_id}/verify_links")
async def verify_links(task_id: str):
    async with async_session() as session:
        if not await get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        result = await session.execute(select(SourceMaterialRecord).where(SourceMaterialRecord.task_id == task_id))
        sources = list(result.scalars())
        checks = []
        for source in sources:
            reachable = bool(source.source_url) and source.access_status not in {"blocked", "failed"}
            record = LinkVerificationResultRecord(
                id=new_id("link"),
                task_id=task_id,
                source_material_id=source.id,
                source_url=source.source_url or "",
                reachable=reachable,
            )
            session.add(record)
            checks.append({"source_id": source.id, "source_url": source.source_url, "reachable": reachable})
        await session.commit()
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "verify_links", "message": f"Checked {len(checks)} source links"})
    return {"status": "checked", "results": checks}
