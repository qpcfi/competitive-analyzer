import asyncio
import os
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.DEBUG)
load_dotenv("backend/.env")

from backend.agents.orchestrator import recommend_competitors

async def test():
    domain = "AI大模型"
    print(f"Testing recommend_competitors for '{domain}'")
    try:
        candidates = await recommend_competitors(domain)
        for c in candidates:
            print(f"- {c.name}: {c.reason}")
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    asyncio.run(test())
