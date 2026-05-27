import asyncio
import os
from dotenv import load_dotenv

load_dotenv("backend/.env")

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from backend.services.web_search import search_public_web

async def test():
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    base_url = os.environ.get("DEEPSEEK_BASE_URL")
    model_name = os.environ.get("DEEPSEEK_MODEL")
    print(f"API Key: {api_key}, Base URL: {base_url}, Model: {model_name}")

    # Test Search
    try:
        res = await search_public_web("AI大模型 competitors", limit=2)
        print("Search Results:", res)
    except Exception as e:
        print("Search Error:", e)

    # Test LLM
    try:
        llm = ChatOpenAI(api_key=api_key, base_url=base_url, model=model_name)
        res = await llm.ainvoke([HumanMessage(content="Hello")])
        print("LLM Response:", res.content)
    except Exception as e:
        print("LLM Error:", e)

if __name__ == "__main__":
    asyncio.run(test())
