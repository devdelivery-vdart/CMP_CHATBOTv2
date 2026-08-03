from groq import Groq

import config
from providers.base import LLMProvider

MODEL = "llama-3.3-70b-versatile"


class GroqProvider(LLMProvider):
    name = "groq (llama-3.3)"

    def __init__(self):
        self._client = Groq(api_key=config.GROQ_API_KEY) if config.GROQ_API_KEY else None

    def is_configured(self) -> bool:
        return bool(config.GROQ_API_KEY)

    def generate_sql(self, system_prompt: str, question: str) -> str:
        response = self._client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            temperature=0,
        )
        return response.choices[0].message.content

    def generate_answer(self, system_prompt: str, user_content: str) -> str:
        response = self._client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0,
        )
        return response.choices[0].message.content.strip()
