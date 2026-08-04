import asyncio
from agent import stream_agent

async def main():
    async for chunk in stream_agent("I want to apply for casual leave", [], "dummy_token", "dummy_emp"):
        print(chunk)

asyncio.run(main())
