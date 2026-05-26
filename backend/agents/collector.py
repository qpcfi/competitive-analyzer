import httpx
import uuid
from bs4 import BeautifulSoup
from services.access_policy import check_public_access
from services.privacy import redact_pii
from .state import AgentState

async def collector_node(state: AgentState):
    context = state.get('task_context', {})
    competitors = context.get('competitors', [])
    task_id = state.get("task_id", "task")
    
    results = []
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for comp in competitors:
            search_url = f"https://html.duckduckgo.com/html/?q={comp}+pricing+features"
            access = await check_public_access(search_url)
            try:
                if access.status in {"blocked", "failed"}:
                    raise RuntimeError(access.reason or access.status)
                response = await client.get(search_url, headers={"User-Agent": "Mozilla/5.0"})
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                content = soup.get_text(separator=' ', strip=True)
                redacted = redact_pii(content[:1500])
                results.append(
                    {
                        "id": f"src_{uuid.uuid5(uuid.NAMESPACE_URL, f'{task_id}:{comp}:search').hex[:12]}",
                        "competitor": comp,
                        "source_url": str(response.url),
                        "source_type": "search_result",
                        "quote_text": redacted.text,
                        "extracted_value": {"summary": redacted.text[:500]},
                        "agent_node": "collector",
                        "access_status": access.status,
                        "validation_status": "accepted" if redacted.text else "degraded",
                        "trust_status": "third_party",
                        "retry_count": 0,
                        "degraded_reason": None if redacted.text else "empty_content",
                        "pii_redacted": redacted.redacted,
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "id": f"src_{uuid.uuid5(uuid.NAMESPACE_URL, f'{task_id}:{comp}:degraded').hex[:12]}",
                        "competitor": comp,
                        "source_url": search_url,
                        "source_type": "search_result",
                        "quote_text": "",
                        "extracted_value": {"error": str(e)},
                        "agent_node": "collector",
                        "access_status": access.status,
                        "validation_status": "degraded",
                        "trust_status": "degraded",
                        "retry_count": 1,
                        "degraded_reason": str(e),
                        "pii_redacted": False,
                    }
                )
        
    state["raw_materials"] = results
    state["source_ids"] = [item["id"] for item in results]
    return state
