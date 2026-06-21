"""Map critic feedback records to incremental rerun scopes.

This module is the bridge between Critic feedback and the incremental
partial rerun system.  Any feedback item that suggests re-analysis is
mapped to one or more scope dicts that `analysis_rerun.py` understands.

Mapping rules (first-match wins for each feedback item):
1. module_id == "swot"        → swot scope
2. module_id == "report"      → report scope
3. target  matches "competitor:dimension" (both exist)  → cell scope
4. target  matches a dimension_id                       → dimension scope
5. target  matches a competitor name                    → competitor scope
6. fallback                                             → comparison scope
"""

from typing import Any


def feedback_to_rerun_scopes(
    feedback_items: list[dict[str, Any]],
    current_analysis: dict[str, Any],
    current_schema: dict[str, Any],
) -> list[dict[str, Any]]:
    """Map feedback dicts to rerun scope dicts.

    Parameters
    ----------
    feedback_items :
        Each dict should contain at least *target* (str) and *module_id* (str).
        Other keys (action, severity, code) are informational.
    current_analysis :
        The full analysis_results dict (used to discover dimension_ids and
        competitor names).
    current_schema :
        The active schema dict (used only as a secondary source of dimension_ids).

    Returns
    -------
    A list of scope dicts (order preserved, no deduplication — call
    *normalize_batch_scopes* for that).
    """
    if not feedback_items:
        return []

    dim_ids = _collect_dimension_ids(current_analysis, current_schema)
    competitors = _collect_competitors(current_analysis)

    scopes: list[dict[str, Any]] = []
    for item in feedback_items:
        target = str(item.get("target") or item.get("target_id") or "")
        module_id = str(item.get("module_id") or "")
        action = str(item.get("action") or item.get("suggested_action") or "")

        # Skip items that are about collection — they don't need analysis scopes
        if action == "retry_collection":
            continue

        scope = _map_single_feedback(target, module_id, dim_ids, competitors)
        scopes.append(scope)

    return scopes


def _map_single_feedback(
    target: str,
    module_id: str,
    dim_ids: set[str],
    competitors: set[str],
) -> dict[str, Any]:
    """Map one feedback item to a single scope dict."""
    # 1. module_id-based routing
    if module_id == "swot":
        return {"type": "swot", "module_id": "swot"}
    if module_id == "report":
        return {"type": "report", "module_id": "report"}

    # 2. Try colon-separated "competitor:dimension"
    if ":" in target:
        parts = target.split(":", 1)
        comp, dim_candidate = parts[0].strip(), parts[1].strip()
        if comp in competitors and dim_candidate in dim_ids:
            return {
                "type": "cell",
                "module_id": "comparison",
                "dimension_id": dim_candidate,
                "competitor": comp,
            }

    # 3. Target is a dimension_id
    if target in dim_ids:
        return {"type": "dimension", "module_id": "comparison", "dimension_id": target}

    # 4. module_id is a dimension_id
    if module_id in dim_ids:
        return {"type": "dimension", "module_id": "comparison", "dimension_id": module_id}

    # 5. Target is a competitor name
    if target in competitors:
        return {"type": "competitor", "module_id": "comparison", "competitor": target}

    # 6. Fallback
    return {"type": "comparison", "module_id": "comparison"}


# ── helpers ──────────────────────────────────────────────────────────────────


def _collect_dimension_ids(
    current_analysis: dict[str, Any],
    current_schema: dict[str, Any],
) -> set[str]:
    """Collect all known dimension IDs from analysis + schema."""
    ids: set[str] = set()
    for row in current_analysis.get("comparison_rows", []):
        did = row.get("dimension_id") or row.get("key") or ""
        if did:
            ids.add(did)
    for group_fields in current_schema.values():
        if not isinstance(group_fields, list):
            continue
        for field in group_fields:
            if isinstance(field, dict):
                fid = field.get("id") or ""
                if fid:
                    ids.add(fid)
    return ids


def _collect_competitors(current_analysis: dict[str, Any]) -> set[str]:
    """Collect all known competitor names from analysis."""
    comps: set[str] = set()
    for comp in current_analysis.get("discovered_competitors", []):
        comps.add(str(comp))
    return comps
