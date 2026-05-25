import httpx
from bs4 import BeautifulSoup
from .state import AgentState

async def collector_node(state: AgentState):
    context = state.get('task_context', {})
    competitors = context.get('competitors', [])
    
    results = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for comp in competitors:
            try:
                url = f"https://html.duckduckgo.com/html/?q={comp}+pricing+features"
                response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                soup = BeautifulSoup(response.text, 'html.parser')
                content = soup.get_text(separator=' ', strip=True)
                results.append({"competitor": comp, "content": content[:1500]})
            except Exception as e:
                results.append({"competitor": comp, "content": f"Failed to fetch data: {str(e)}"})
        
    state["raw_materials"] = results
    return state
