import time
import asyncio
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from backend.config import OPENAI_API_KEY, OPENAI_MODEL

async def main():
    llm = ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY, temperature=0.0)
    
    t0 = time.time()
    resp = await llm.ainvoke([HumanMessage(content="Hello")])
    t1 = time.time()
    print(f"Raw ainvoke: {t1-t0:.2f}s")
    
    t2 = time.time()
    async for chunk in llm.astream([HumanMessage(content="Tell me a joke")]):
        pass
    t3 = time.time()
    print(f"Raw astream: {t3-t2:.2f}s")

if __name__ == "__main__":
    asyncio.run(main())
