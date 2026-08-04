from config import OPENROUTER_API_KEY
from langchain_openai import ChatOpenAI

models = [
    "meta-llama/llama-3.1-8b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "deepseek/deepseek-chat:free"
]

for m in models:
    print(f"Testing {m}...")
    llm = ChatOpenAI(model=m, openai_api_key=OPENROUTER_API_KEY, openai_api_base="https://openrouter.ai/api/v1")
    try:
        res = llm.invoke("say hi")
        print(f"SUCCESS {m}")
        break
    except Exception as e:
        print(f"FAILED {m}: {str(e)}")
