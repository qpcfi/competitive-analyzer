import asyncio
from copy import deepcopy
from typing import Any

from sqlalchemy import select

from agents.analyzer import analyzer_node
from agents.reporter import reporter_node
from models_db import SourceMaterialRecord, async_session
from services.pipeline import StaleRunError, guard_active, publish_event
from services.repositories import (
    get_survey_campaign,
    get_task,
    latest_schema,
    latest_survey_campaign,
    list_survey_artifacts,
    list_survey_responses,
    save_analysis_module,
    save_source_materials,
    update_survey_campaign,
)
from services.serialization import serialize_source
from services.survey_materials import synthesize_survey_materials


async def refresh_report_with_survey(
    task_id: str,
    run_id: str,
    response_ids: list[str] | None = None,
    campaign_id: str | None = None,
) -> dict[str, Any]:
    try:
        await guard_active(task_id, run_id)
        await publish_event(
            task_id,
            "survey_report_refresh_progress",
            {"stage": "loading", "progress": 10, "status": "running", "message": "正在读取任务、问卷和已选择的答卷。"},
            run_id=run_id,
        )
        async with async_session() as session:
            await guard_active(task_id, run_id)
            task = await get_task(session, task_id)
            if not task:
                raise KeyError(task_id)
            campaign = await get_survey_campaign(session, campaign_id) if campaign_id else await latest_survey_campaign(session, task_id)
            if campaign and campaign.task_id != task_id:
                campaign = None
            if not campaign:
                raise KeyError("survey_campaign")
            artifacts = await list_survey_artifacts(session, campaign.id)
            questionnaire = next((item.content_json for item in artifacts if item.type == "questionnaire"), {})
            selected_ids = set(response_ids or [])
            response_records = await list_survey_responses(session, campaign.id)
            if selected_ids:
                response_records = [item for item in response_records if item.id in selected_ids]
            responses = [
                {
                    "response_id": item.id,
                    "external_response_id": item.external_response_id,
                    "source": item.source,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "response_json": item.response_json or {},
                }
                for item in response_records
            ]
            schema_record = await latest_schema(session, task_id)
            source_stmt = select(SourceMaterialRecord).where(SourceMaterialRecord.task_id == task_id)
            material_ids = task.current_material_ids or []
            if material_ids:
                source_stmt = source_stmt.where(SourceMaterialRecord.id.in_(material_ids))
            elif task.current_collection_run_id:
                source_stmt = source_stmt.where(SourceMaterialRecord.collection_run_id == task.current_collection_run_id)
            source_result = await session.execute(source_stmt)
            existing_materials = [serialize_source(item) for item in source_result.scalars()]
            existing_analysis = task.analysis_results or {}
            existing_versions = existing_analysis.get("report_versions") if isinstance(existing_analysis, dict) else None
            base_analysis = deepcopy((existing_versions or {}).get("base") or existing_analysis)

        await guard_active(task_id, run_id)
        await publish_event(
            task_id,
            "survey_report_refresh_progress",
            {
                "stage": "synthesizing",
                "progress": 30,
                "status": "running",
                "message": f"已读取 {len(responses)} 份答卷，正在转换为一手调研材料。",
                "selected_response_count": len(responses),
            },
            run_id=run_id,
        )
        survey_materials = synthesize_survey_materials(
            task_id=task_id,
            campaign_id=campaign.id,
            questionnaire=questionnaire,
            responses=responses,
        )

        await guard_active(task_id, run_id)
        await publish_event(
            task_id,
            "survey_report_refresh_progress",
            {
                "stage": "saving_materials",
                "progress": 45,
                "status": "running",
                "message": f"已生成 {len(survey_materials)} 条调研材料，正在写入资料库。",
                "survey_material_count": len(survey_materials),
            },
            run_id=run_id,
        )
        async with async_session() as session:
            await guard_active(task_id, run_id)
            task = await get_task(session, task_id)
            collection_run_id = (task.current_collection_run_id if task else None) or run_id
            if task and not task.current_collection_run_id:
                task.current_collection_run_id = collection_run_id
            if survey_materials:
                await save_source_materials(session, task_id, survey_materials, collection_run_id=collection_run_id)
                survey_ids = [m.get("id") for m in survey_materials if m.get("id")]
                current_ids = list(task.current_material_ids or [])
                current_ids.extend(item for item in survey_ids if item not in current_ids)
                task.current_material_ids = current_ids
            await update_survey_campaign(session, campaign.id, status="synthesized")
            await session.commit()

        await guard_active(task_id, run_id)
        await publish_event(
            task_id,
            "survey_report_refresh_progress",
            {"stage": "analyzing", "progress": 65, "status": "running", "message": "正在把问卷材料并入原始资料，并重新运行 Analyzer。"},
            run_id=run_id,
        )
        state = {
            "task_id": task_id,
            "task_context": {
                "domain": task.domain,
                "competitors": task.competitors or [],
                "execution_mode": task.execution_mode,
                "analysis_goal": task.analysis_goal or "",
                "task_intent": task.task_intent or {},
                "predefined_schema": [],
                "previous_report": (base_analysis.get("report") if isinstance(base_analysis, dict) else {}) or {},
                "refresh_reason": "survey_enrichment",
            },
            "schema_version": schema_record.version if schema_record else 1,
            "dynamic_schema": schema_record.schema_json if schema_record else (task.dynamic_schema or {}),
            "raw_materials": existing_materials + survey_materials,
            "source_ids": [item["id"] for item in existing_materials + survey_materials if item.get("id")],
            "analysis_results": deepcopy(base_analysis),
            "critic_feedback": task.critic_feedback or [],
            "suggested_schema_extensions": [],
            "task_events": [],
            "progress": task.progress or 100,
            "module_updates": [],
            "retry_counts": {},
        }

        state = await analyzer_node({**state, "task_id": None})
        state["task_id"] = task_id

        await guard_active(task_id, run_id)
        await publish_event(
            task_id,
            "survey_report_refresh_progress",
            {"stage": "reporting", "progress": 82, "status": "running", "message": "Analyzer 已完成，正在重新生成结构化报告。"},
            run_id=run_id,
        )
        state = await reporter_node({**state, "task_id": None})
        state["task_id"] = task_id

        await guard_active(task_id, run_id)
        analysis = state.get("analysis_results") or {}
        analysis.setdefault("report", {})
        analysis["report"]["version_label"] = "v2_survey_enriched"
        analysis["report"]["survey_campaign_id"] = campaign.id
        enriched_analysis = deepcopy(analysis)
        analysis["report_versions"] = {
            "base": base_analysis,
            "survey_enriched": enriched_analysis,
            "comparison": build_report_comparison(
                base_analysis,
                enriched_analysis,
                selected_response_count=len(responses),
                survey_material_count=len(survey_materials),
            ),
        }

        await publish_event(
            task_id,
            "survey_report_refresh_progress",
            {"stage": "saving_report", "progress": 92, "status": "running", "message": "正在保存调研增强版报告并更新分析模块。"},
            run_id=run_id,
        )
        async with async_session() as session:
            await guard_active(task_id, run_id)
            task = await get_task(session, task_id)
            if task:
                task.analysis_results = analysis
                task.final_report = analysis.get("report", {})
            for module_id in ("comparison", "swot", "report"):
                content = analysis.get(module_id, {}) if isinstance(analysis, dict) else {}
                await save_analysis_module(
                    session,
                    task_id,
                    module_id=module_id,
                    module_type=module_id,
                    content=content if isinstance(content, dict) else {"items": content},
                    evidence_refs=analysis.get("evidence_refs", []) if isinstance(analysis, dict) else [],
                    quality_status="survey_enriched",
                )
            await update_survey_campaign(session, campaign.id, status="report_updated")
            await session.commit()

        await publish_event(
            task_id,
            "report_updated",
            {"version": 2, "reason": "survey_enrichment", "campaign_id": campaign.id, "survey_material_count": len(survey_materials)},
            run_id=run_id,
        )
        await publish_event(
            task_id,
            "survey_report_refresh_progress",
            {
                "stage": "completed",
                "progress": 100,
                "status": "completed",
                "message": "调研增强版报告已生成。",
                "survey_material_count": len(survey_materials),
                "selected_response_count": len(responses),
            },
            run_id=run_id,
        )
        return {"status": "updated", "version": 2, "survey_material_count": len(survey_materials), "analysis": analysis}
    except (StaleRunError, asyncio.CancelledError):
        return {"status": "cancelled"}


def build_report_comparison(
    base_analysis: dict[str, Any],
    enriched_analysis: dict[str, Any],
    *,
    selected_response_count: int,
    survey_material_count: int,
) -> dict[str, Any]:
    base_report = base_analysis.get("report") if isinstance(base_analysis, dict) else {}
    enriched_report = enriched_analysis.get("report") if isinstance(enriched_analysis, dict) else {}
    base_recommendations = extract_report_texts(base_report.get("recommendations") if isinstance(base_report, dict) else [])
    enriched_recommendations = extract_report_texts(enriched_report.get("recommendations") if isinstance(enriched_report, dict) else [])
    base_findings = extract_report_texts(base_report.get("findings") if isinstance(base_report, dict) else [])
    enriched_findings = extract_report_texts(enriched_report.get("findings") if isinstance(enriched_report, dict) else [])
    differences: list[dict[str, str]] = []
    if normalize_text(base_report.get("summary") if isinstance(base_report, dict) else "") != normalize_text(
        enriched_report.get("summary") if isinstance(enriched_report, dict) else ""
    ):
        differences.append(
            {
                "area": "执行摘要",
                "change": "调研增强版报告基于问卷答复重新生成了执行摘要。",
            }
        )
    new_recommendations = [item for item in enriched_recommendations if item not in set(base_recommendations)]
    if new_recommendations:
        differences.append(
            {
                "area": "战略建议",
                "change": f"新增或改写了 {len(new_recommendations)} 条建议。",
                "detail": "；".join(new_recommendations[:3]),
            }
        )
    new_findings = [item for item in enriched_findings if item not in set(base_findings)]
    if new_findings:
        differences.append(
            {
                "area": "关键发现",
                "change": f"新增或改写了 {len(new_findings)} 条发现。",
                "detail": "；".join(new_findings[:3]),
            }
        )
    differences.append(
        {
            "area": "证据来源",
            "change": f"调研增强版纳入 {selected_response_count} 份问卷答复，沉淀为 {survey_material_count} 条一手调研材料。",
        }
    )
    return {
        "base_label": "v1_public_sources",
        "enriched_label": "v2_survey_enriched",
        "selected_response_count": selected_response_count,
        "survey_material_count": survey_material_count,
        "differences": differences,
    }


def extract_report_texts(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    texts = []
    for item in value:
        text = normalize_text(item)
        if text:
            texts.append(text)
    return texts


def normalize_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "；".join(filter(None, (normalize_text(item) for item in value)))
    if isinstance(value, dict):
        for key in ("text", "summary", "message", "value", "title"):
            if value.get(key):
                return normalize_text(value[key])
    return ""
