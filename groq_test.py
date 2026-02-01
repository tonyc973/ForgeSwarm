from groq import Groq
import os
api_key = os.environ.get("GROQ_API_KEY")

client = Groq(api_key=api_key)
completion = client.chat.completions.create(
    model="qwen-2.5-coder-32b",
    messages=[
        {
            "role": "user",
            "content": "Explain why fast inference is critical for reasoning models"
        }
    ]
)
print(completion.choices[0].message.content)