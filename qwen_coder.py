import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

print(f"Key loaded: {os.getenv('OPENAI_API_KEY')[:10]}...")

try:
    llm = ChatOpenAI(
        model="qwen/qwen-2.5-coder-32b-instruct",
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url="https://openrouter.ai/api/v1"
    )
    print("Attempting to connect to OpenRouter...")
    response = llm.invoke("Hello, are you Qwen?")
    print(f"\nSUCCESS:\n{response.content}")
except Exception as e:
    print(f"\nFAILED:\n{e}")