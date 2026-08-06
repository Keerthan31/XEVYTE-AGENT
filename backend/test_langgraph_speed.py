import time
import asyncio
from langchain_core.messages import HumanMessage
from agent import _compiled_agent

async def main():
    t2 = time.time()
    async for event in _compiled_agent.astream_events({"messages": [HumanMessage(content="I want to apply for casual leave")]}, version="v2"):
        pass
    t3 = time.time()
    print(f"astream_events (Tools): {t3-t2:.2f}s")

if __name__ == "__main__":
    asyncio.run(main())
