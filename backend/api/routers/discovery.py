from fastapi import APIRouter, HTTPException, Query

from agents.orchestrator import discover_competitors

router = APIRouter()


@router.get("/api/v1/competitor-recommendations")
async def get_competitor_recommendations(
    domain: str = Query(..., min_length=1),
    existing: list[str] = Query(default=[]),
):
    normalized_domain = domain.strip()
    if not normalized_domain:
        raise HTTPException(status_code=400, detail="domain is required")

    existing_names = {item.strip().lower() for item in existing if item.strip()}
    discovered = await discover_competitors(normalized_domain)
    items = []
    seen = set(existing_names)
    for name in discovered:
        normalized_name = str(name).strip()
        lowered = normalized_name.lower()
        if not normalized_name or lowered in seen:
            continue
        seen.add(lowered)
        items.append(
            {
                "name": normalized_name,
                "reason": f"基于公开网页信号，{normalized_name} 与 {normalized_domain} 存在竞品相关性。",
            }
        )
    return {"items": items}
