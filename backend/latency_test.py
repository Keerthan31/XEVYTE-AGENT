import time
import asyncio
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv
import os

load_dotenv()

async def main():
    llm = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        api_key=os.getenv("OPENAI_API_KEY"),
        temperature=0.0
    )
    
    print(f"Using model: {os.getenv('OPENAI_MODEL')}")
    start = time.time()
    
    print("Starting stream...")
    first_token_time = None
    
    async for chunk in llm.astream([HumanMessage(content="Hello, how are you?")]):
        if not first_token_time:
            first_token_time = time.time()
            print(f"\nTTFT (Time To First Token): {first_token_time - start:.2f}s")
        print(chunk.content, end="", flush=True)
        
    end = time.time()
    print(f"\nTotal time: {end - start:.2f}s")

if __name__ == "__main__":
    asyncio.run(main())
