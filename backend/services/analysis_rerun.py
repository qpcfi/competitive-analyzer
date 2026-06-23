import copy
import json
import logging
from dataclasses import dataclass
from typing import Any

from agents.analyzer import analyzer_node, generate_goal_analysis
from agents.state import AgentState
from models_db import async_session
from services.pipeline import publish_event
from services.repositories import (
    add_intervention,
    get_task,
    latest_schema,
    load_source_materials,
    save_analysis_module,
    update_task_state,
)

logger = logging.getLogger(__name__)


@dataclass
class RerunContext:
    task_id: str
    domain: str
    competitors: list[str]
    execution_mode: str
    analysis_goal: str | None
    analysis_results: dict[str, Any]
    raw_materials: list[dict[str, Any]]
    dynamic_schema: dict[str, Any]
    schema_version: int
    task_state: str
    task_intent: dict | None = None


SCOPE_TYPES = frozenset({"cell", "dimension", "competitor", "comparison", "swot", "report", "batch"})
ALLOWED_STATES = frozenset({"ANALYSIS_REVIEW", "PAUSED", "COMPLETED"})


def normalize_scope(scope: dict, ctx: RerunContext) -> dict:
    """Validate structure and normalize scope fields."""
    scope_type = scope.get("type")
    if scope_type not in SCOPE_TYPES:
        raise ValueError(f"Invalid scope type: {scope_type}. Must be one of {sorted(SCOPE_TYPES)}")

    module_id = scope.get("module_id", "comparison")

    # module_id must be compatible with scope type
    if scope_type in ("cell", "dimension", "competitor", "comparison"):
        if module_id != "comparison":
            raise ValueError(f"Scope type '{scope_type}' requires module_id='comparison', got '{module_id}'")
    elif scope_type == "swot":
        if module_id != "swot":
            raise ValueError(f"Scope type 'swot' requires module_id='swot', got '{module_id}'")
    elif scope_type == "report":
        if module_id != "report":
            raise ValueError(f"Scope type 'report' requires module_id='report', got '{module_id}'")

    # Presence checks per type
    if scope_type == "cell":
        if not scope.get("dimension_id"):
            raise ValueError("cell scope requires 'dimension_id'")
        if not scope.get("competitor"):
            raise ValueError("cell scope requires 'competitor'")
    elif scope_type == "dimension":
        if not scope.get("dimension_id"):
            raise ValueError("dimension scope requires 'dimension_id'")
    elif scope_type == "competitor":
        if not scope.get("competitor"):
            raise ValueError("competitor scope requires 'competitor'")

    return {**scope, "module_id": module_id}


def validate_scope(scope: dict, ctx: RerunContext) -> None:
    """Validate that scope references exist in the actual task data."""
    scope_type = scope.get("type")

    if not ctx.analysis_results:
        raise ValueError("No analysis results found. Run a full analysis first.")
    if not ctx.raw_materials:
        raise ValueError("No collected materials found. Collect data first.")

    rows = ctx.analysis_results.get("comparison_rows", [])
    discovered = ctx.analysis_results.get("discovered_competitors", [])
    all_competitors = set(ctx.competitors or []) | set(discovered)

    if scope_type in ("cell", "dimension"):
        dim_id = scope.get("dimension_id")
        if not any(r.get("dimension_id") == dim_id for r in rows):
            raise ValueError(
                f"Dimension '{dim_id}' not found in analysis results. "
                f"Available dimensions: {[r.get('dimension_id') for r in rows[:20]]}"
            )

    if scope_type in ("cell", "competitor"):
        comp = scope.get("competitor")
        if comp not in all_competitors:
            raise ValueError(
                f"Competitor '{comp}' not found in task. "
                f"Available: {sorted(all_competitors)}"
            )

    if scope_type == "swot":
        if "swot" not in ctx.analysis_results:
            raise ValueError("No SWOT analysis exists yet. Run a full analysis first.")

    if scope_type == "report":
        if "report" not in ctx.analysis_results:
            raise ValueError("No report exists yet. Run a full analysis first.")


async def load_rerun_context(task_id: str) -> RerunContext:
    """Load all data needed for a rerun from the database."""
    async with async_session() as session:
        task = await get_task(session, task_id)
        if not task:
            raise KeyError(task_id)

        schema_record = await latest_schema(session, task_id)
        dynamic_schema = schema_record.schema_json if schema_record else {}
        material_ids = task.current_material_ids or []
        if material_ids:
            raw_materials = await load_source_materials(
                session,
                task_id,
                material_ids=material_ids,
                collection_run_id=task.current_collection_run_id,
                schema=dynamic_schema,
            )
        elif task.current_collection_run_id:
            raw_materials = await load_source_materials(
                session,
                task_id,
                collection_run_id=task.current_collection_run_id,
                schema=dynamic_schema,
            )
        else:
            raw_materials = await load_source_materials(
                session,
                task_id,
                schema=dynamic_schema,
            )
            raw_materials = list(task.raw_materials or [])

        return RerunContext(
            task_id=task.id,
            domain=task.domain or "",
            competitors=list(task.competitors or []),
            execution_mode=task.execution_mode or "step_by_step",
            analysis_goal=task.analysis_goal,
            analysis_results=dict(task.analysis_results or {}),
            raw_materials=raw_materials,
            dynamic_schema=dynamic_schema,
            schema_version=schema_record.version if schema_record else 0,
            task_state=task.state,
            task_intent=task.task_intent or {},
        )


def build_scoped_analyzer_state(
    ctx: RerunContext,
    scope: dict,
    instruction: str,
    run_id: str,
) -> AgentState:
    """Build an AgentState for the analyzer with rerun context."""
    return {
        "task_id": ctx.task_id,
        "task_context": {
            "domain": ctx.domain,
            "competitors": ctx.competitors,
            "execution_mode": ctx.execution_mode,
            "analysis_goal": ctx.analysis_goal or "",
            "task_intent": ctx.task_intent or {},
            "analysis_rerun_scope": scope,
            "analysis_rerun_instruction": instruction,
        },
        "dynamic_schema": ctx.dynamic_schema,
        "schema_version": ctx.schema_version,
        "raw_materials": list(ctx.raw_materials),
        "source_ids": [m["id"] for m in ctx.raw_materials if m.get("id")],
        "analysis_results": dict(ctx.analysis_results),
        "critic_feedback": [],
        "suggested_schema_extensions": [],
        "task_events": [],
        "progress": 85,
        "module_updates": [],
        "retry_counts": {},
    }


# ── Merge helpers ──────────────────────────────────────────────────────────


def _find_row(analysis: dict, dimension_id: str) -> dict | None:
    for row in analysis.get("comparison_rows", []):
        if row.get("dimension_id") == dimension_id:
            return row
    return None


def _merge_cell(old: dict, rerun: dict, dimension_id: str, competitor: str) -> dict:
    """Replace a single cell (one competitor in one dimension row)."""
    old_row = _find_row(old, dimension_id)
    if not old_row:
        return old
    if competitor not in old_row.get("values", {}):
        return old
    new_row = _find_row(rerun, dimension_id)
    if new_row and competitor in new_row.get("values", {}):
        old_row["values"][competitor] = new_row["values"][competitor]
    return old


def _merge_dimension(old: dict, rerun: dict, dimension_id: str) -> dict:
    """Replace one entire dimension row, or append if it doesn't exist yet."""
    rows = old.get("comparison_rows", [])
    new_row = _find_row(rerun, dimension_id)
    if not new_row:
        return old

    for i, row in enumerate(rows):
        if row.get("dimension_id") == dimension_id:
            rows[i] = new_row
            return old

    # Not found — append (e.g. a newly added schema extension field)
    rows.append(new_row)
    return old


def _merge_competitor(old: dict, rerun: dict, competitor: str) -> dict:
    """Replace one competitor's values across all dimensions."""
    for dim_id in {r["dimension_id"] for r in old.get("comparison_rows", []) if r.get("dimension_id")}:
        old_row = _find_row(old, dim_id)
        new_row = _find_row(rerun, dim_id)
        if old_row and new_row and competitor in old_row.get("values", {}) and competitor in new_row.get("values", {}):
            old_row["values"][competitor] = new_row["values"][competitor]
    return old


def _merge_comparison(old: dict, rerun: dict) -> dict:
    """Replace comparison-related fields. Does NOT touch swot/report/goal_analysis."""
    old["comparison_rows"] = rerun.get("comparison_rows", old.get("comparison_rows", []))
    old["schema_dimensions"] = rerun.get("schema_dimensions", old.get("schema_dimensions", []))
    old["selected_angles"] = rerun.get("selected_angles", old.get("selected_angles", []))
    old["comparison"] = rerun.get("comparison", old.get("comparison", []))
    old["discovered_competitors"] = rerun.get("discovered_competitors", old.get("discovered_competitors", []))
    old["evidence_refs"] = rerun.get("evidence_refs", old.get("evidence_refs", []))
    return old


def _merge_swot(old: dict, rerun: dict) -> dict:
    """Replace SWOT section only."""
    if "swot" in rerun:
        old["swot"] = rerun["swot"]
    return old


def _merge_report(old: dict, rerun: dict) -> dict:
    """Replace report section only."""
    if "report" in rerun:
        old["report"] = rerun["report"]
    return old


def merge_analysis_patch(old_analysis: dict, rerun_analysis: dict, scope: dict) -> dict:
    """Merge rerun output into existing analysis respecting scope boundaries.

    Only fields within scope are replaced. Everything else is preserved.
    This prevents SWOT/report/goal_analysis from being overwritten by a
    comparison-scoped rerun.
    """
    # Work on deep copies to avoid mutating the caller's reference
    merged = copy.deepcopy(old_analysis)
    rerun = copy.deepcopy(rerun_analysis)
    scope_type = scope["type"]

    if scope_type == "cell":
        merged = _merge_cell(merged, rerun, scope["dimension_id"], scope["competitor"])
    elif scope_type == "dimension":
        merged = _merge_dimension(merged, rerun, scope["dimension_id"])
    elif scope_type == "competitor":
        merged = _merge_competitor(merged, rerun, scope["competitor"])
    elif scope_type == "comparison":
        merged = _merge_comparison(merged, rerun)
    elif scope_type == "swot":
        merged = _merge_swot(merged, rerun)
    elif scope_type == "report":
        merged = _merge_report(merged, rerun)

    return merged


# ── Persistence ────────────────────────────────────────────────────────────


async def persist_incremental_analysis(
    task_id: str,
    merged_analysis: dict[str, Any],
    scope: dict,
    next_state: str,
    affected_modules: list[str] | None = None,
) -> None:
    """Save merged analysis and update task state in a single transaction.

    Parameters
    ----------
    affected_modules :
        Override which analysis modules to save.  When ``None`` (the default),
        derived from *scope* via ``affected_modules_for_scopes``.
    """
    async with async_session() as session:
        task = await get_task(session, task_id)
        if not task:
            raise KeyError(task_id)

        task.analysis_results = merged_analysis

        if affected_modules is None:
            affected_modules = affected_modules_for_scopes([scope])

        for module_id in affected_modules:
            if module_id == "comparison":
                content = {
                    "comparison_rows": merged_analysis.get("comparison_rows", []),
                    "schema_dimensions": merged_analysis.get("schema_dimensions", []),
                    "selected_angles": merged_analysis.get("selected_angles", []),
                    "comparison": merged_analysis.get("comparison", []),
                    "discovered_competitors": merged_analysis.get("discovered_competitors", []),
                }
            elif module_id == "swot":
                content = merged_analysis.get("swot", {})
            elif module_id == "report":
                content = merged_analysis.get("report", {})
            else:
                continue

            await save_analysis_module(
                session, task_id,
                module_id=module_id, module_type=module_id,
                content=content if isinstance(content, dict) else {"items": content},
                evidence_refs=merged_analysis.get("evidence_refs", []),
            )

        await add_intervention(session, task_id, "partial_rerun", {
            "scope": scope,
            "previous_state": task.state,
        })

        await update_task_state(session, task_id, state=next_state, progress=90)
        await session.commit()


def affected_modules_for_scopes(scopes: list[dict]) -> list[str]:
    """Determine which analysis modules are touched by a set of scopes.

    Rules:
    * *swot* / *report* scope types → the respective module.
    * everything else (cell, dimension, competitor, comparison, batch) → comparison.
    """
    modules: set[str] = set()
    for s in scopes:
        t = s.get("type", "")
        if t == "swot":
            modules.add("swot")
        elif t == "report":
            modules.add("report")
        else:
            modules.add("comparison")
    return list(modules)


async def publish_incremental_analysis_events(
    task_id: str,
    run_id: str,
    merged_analysis: dict[str, Any],
    scope: dict,
) -> None:
    """Publish SSE events with the complete merged analysis."""
    await publish_event(task_id, "analysis_progress", {
        "module_id": "analysis",
        "scope": scope,
        "data": merged_analysis,
    }, run_id=run_id)

    await publish_event(task_id, "module_updated", {
        "module_id": scope.get("module_id", "comparison"),
        "scope": scope,
        "patch_applied": True,
    }, run_id=run_id)

    await publish_event(task_id, "debug_log", {
        "agent": "System",
        "event": "partial_rerun",
        "message": f"Partial rerun completed for scope: {json.dumps(scope, ensure_ascii=False)}",
    }, run_id=run_id)


# ── Main entry point (runs as background task via runner.start_claimed) ────


async def run_incremental_analysis_rerun(
    task_id: str,
    run_id: str,
    scope: dict,
    instruction: str,
) -> dict[str, Any]:
    """Execute a scoped incremental rerun and return the merged analysis."""
    try:
        # 1. Load context
        ctx = await load_rerun_context(task_id)

        if ctx.task_state not in ALLOWED_STATES:
            raise RuntimeError(
                f"Cannot rerun while task is {ctx.task_state}. "
                f"Allowed: {sorted(ALLOWED_STATES)}"
            )

        # 2. Normalize & validate scope
        normalized_scope = normalize_scope(scope, ctx)
        validate_scope(normalized_scope, ctx)

        # 3. Build scoped state
        scoped_state = build_scoped_analyzer_state(
            ctx=ctx, scope=normalized_scope, instruction=instruction, run_id=run_id,
        )

        # 4. Run analyzer (LLM call)
        rerun_state = await analyzer_node(scoped_state)
        rerun_analysis = rerun_state.get("analysis_results") or {}

        # 5. Merge
        merged_analysis = merge_analysis_patch(
            old_analysis=ctx.analysis_results,
            rerun_analysis=rerun_analysis,
            scope=normalized_scope,
        )

        # 5b. Refresh goal_analysis from the complete merged results
        merged_analysis = await refresh_goal_analysis_for_merged(
            ctx, merged_analysis, run_id, [normalized_scope],
        )

        # 6. Persist (own DB session)
        next_state = "ANALYSIS_REVIEW"
        await persist_incremental_analysis(
            task_id=task_id,
            merged_analysis=merged_analysis,
            scope=normalized_scope,
            next_state=next_state,
        )

        # 7. Events
        await publish_incremental_analysis_events(
            task_id=task_id,
            run_id=run_id,
            merged_analysis=merged_analysis,
            scope=normalized_scope,
        )

        return merged_analysis

    except Exception:
        logger.exception("Partial rerun failed for task %s run %s", task_id, run_id)
        await publish_event(task_id, "error", {
            "event": "partial_rerun_failed",
            "scope": scope,
        }, run_id=run_id, allow_inactive=True)
        raise


# ── Batch scope support ──────────────────────────────────────────────────────


def normalize_batch_scopes(
    scopes: list[dict],
    analysis_results: dict[str, Any] | None = None,
) -> list[dict]:
    """Deduplicate scopes with a strict priority hierarchy.

    Priority (highest → lowest):
        comparison  >  {competitor, dimension}  >  cell

    Rules
    -----
    * If a *comparison* scope is present, return ``[comparison]`` only.
    * *competitor* and *dimension* scopes are kept as-is.
    * *cell* scopes whose *competitor* is covered by a competitor scope, or
      whose *dimension_id* is covered by a dimension scope, are removed.
    * Exact duplicates (same type + same target fields) are collapsed.
    """
    if any(s.get("type") == "comparison" for s in scopes):
        return [{"type": "comparison", "module_id": "comparison"}]

    competitor_names: set[str] = set()
    dimension_ids: set[str] = set()
    seen_broad: set[tuple] = set()   # dedup for non-cell scopes
    seen_cell: set[tuple] = set()     # dedup for cell scopes (separate to avoid
                                      # the "first-pass kills all cells" bug)
    out: list[dict] = []

    for s in scopes:
        t = s.get("type")
        if t == "competitor":
            k = (t, s.get("competitor", ""))
            if k in seen_broad:
                continue
            seen_broad.add(k)
            comp = s.get("competitor", "")
            if comp:
                competitor_names.add(comp)
            out.append(s)
        elif t == "dimension":
            k = (t, s.get("dimension_id", ""))
            if k in seen_broad:
                continue
            seen_broad.add(k)
            dim = s.get("dimension_id", "")
            if dim:
                dimension_ids.add(dim)
            out.append(s)
        elif t in ("swot", "report"):
            k = (t, "")
            if k in seen_broad:
                continue
            seen_broad.add(k)
            out.append(s)

    # Second pass: cell scopes only — covered by broader scope or dedup
    for s in scopes:
        t = s.get("type")
        if t != "cell":
            continue
        k = ("cell", s.get("dimension_id", ""), s.get("competitor", ""))
        if k in seen_cell:
            continue
        seen_cell.add(k)
        dim = s.get("dimension_id", "")
        comp = s.get("competitor", "")
        if comp and comp in competitor_names:
            continue
        if dim and dim in dimension_ids:
            continue
        out.append(s)

    return out


async def run_incremental_analysis_rerun_batch(
    task_id: str,
    run_id: str,
    scopes: list[dict],
    instruction: str,
) -> dict[str, Any]:
    """Full batch rerun: load context → normalize → core → persist → events.

    This is the **self-contained** entry-point (owns its DB transaction and
    event publishing).  For callers that already hold in-memory context (e.g.
    ``run_critic_retry`` in pipeline.py), use ``run_scoped_rerun_with_ctx``
    directly.
    """
    try:
        ctx = await load_rerun_context(task_id)

        if ctx.task_state not in ALLOWED_STATES:
            raise RuntimeError(
                f"Cannot rerun while task is {ctx.task_state}. "
                f"Allowed: {sorted(ALLOWED_STATES)}"
            )

        normalized = normalize_batch_scopes(scopes, ctx.analysis_results)
        if not normalized:
            logger.warning("run_incremental_analysis_rerun_batch: empty scopes after normalisation")
            return ctx.analysis_results

        merged = await run_scoped_rerun_with_ctx(ctx, run_id, normalized, instruction)

        affected_modules = affected_modules_for_scopes(normalized)
        await persist_incremental_analysis(
            task_id=task_id,
            merged_analysis=merged,
            scope={"type": "batch", "item_count": len(normalized), "items": normalized},
            next_state="ANALYSIS_REVIEW",
            affected_modules=affected_modules,
        )

        await publish_incremental_analysis_events(
            task_id=task_id,
            run_id=run_id,
            merged_analysis=merged,
            scope={"type": "batch", "item_count": len(normalized)},
        )

        return merged

    except Exception:
        logger.exception("Batch rerun failed for task %s run %s", task_id, run_id)
        await publish_event(task_id, "error", {
            "event": "batch_rerun_failed",
            "scope_count": len(scopes),
        }, run_id=run_id, allow_inactive=True)
        raise


async def run_scoped_rerun_with_ctx(
    ctx: RerunContext,
    run_id: str,
    normalized: list[dict],
    instruction: str,
) -> dict[str, Any]:
    """Core rerun logic — shared between batch API and ``run_critic_retry``.

    Assumes *normalized* has already been deduplicated via
    ``normalize_batch_scopes``.  Steps:

    1. Build a single scoped ``AgentState`` (batch scope listing all items).
    2. Make **one** ``analyzer_node`` call (the LLM sees all scopes at once).
    3. Iteratively call ``merge_analysis_patch`` for each scope.

    Returns the fully merged analysis dict (not persisted — caller's
    responsibility).
    """
    batch_scope = {"type": "batch", "items": normalized}
    batch_instruction = instruction or "批量局部重跑，请覆盖以下所有范围"

    scoped_state = build_scoped_analyzer_state(
        ctx=ctx, scope=batch_scope, instruction=batch_instruction, run_id=run_id,
    )

    rerun_state = await analyzer_node(scoped_state)
    rerun_analysis = rerun_state.get("analysis_results") or {}

    merged = ctx.analysis_results
    for scope in normalized:
        merged = merge_analysis_patch(merged, rerun_analysis, scope)

    merged = await refresh_goal_analysis_for_merged(ctx, merged, run_id, normalized)

    return merged


async def refresh_goal_analysis_for_merged(
    ctx: RerunContext,
    merged_analysis: dict,
    run_id: str,
    scopes: list[dict],
) -> dict:
    """Re-generate *goal_analysis* from the complete merged analysis.

    Called after every batch or single-scope merge so the top-level conclusion
    always reflects the full *comparison_rows* (not just the scoped delta).

    If the LLM call fails, the existing *goal_analysis* (if any) is preserved.
    """
    merged_analysis = dict(merged_analysis)  # don't mutate caller ref

    # Build a minimal state with the merged analysis as the source
    goal_state = build_scoped_analyzer_state(
        ctx=ctx,
        scope={"type": "goal_analysis_refresh", "items": scopes},
        instruction="基于增量重跑合并后的完整分析结果，刷新顶部分析结论",
        run_id=run_id,
    )
    # The merged analysis replaces the original ctx.analysis_results
    goal_state["analysis_results"] = merged_analysis

    goal = await generate_goal_analysis(goal_state, merged_analysis, reason="incremental_rerun")
    if goal:
        merged_analysis["goal_analysis"] = goal

    return merged_analysis
