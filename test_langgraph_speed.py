import time
import asyncio
from langchain_core.messages import HumanMessage
from backend.agent import _compiled_agent

async def main():
    t0 = time.time()
    async for event in _compiled_agent.astream_events({"messages": [HumanMessage(content="Hello")]}, version="v2"):
        pass
    t1 = time.time()
    print(f"astream_events (Hello): {t1-t0:.2f}s")

    t2 = time.time()
    async for event in _compiled_agent.astream_events({"messages": [HumanMessage(content="I want to apply for casual leave")]}, version="v2"):
        pass
    t3 = time.time()
    print(f"astream_events (Tools): {t3-t2:.2f}s")

if __name__ == "__main__":
    asyncio.run(main())
