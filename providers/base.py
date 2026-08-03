"""
Base interface for an LLM provider. To add a new provider later (e.g.
Anthropic, a local model, Gemini, etc.), create a new file in this
`providers/` folder implementing this interface (see groq_provider.py or
openai_provider.py for the pattern), then add ONE line registering it in
`provider_chain.py`. Nothing else in the codebase needs to change.
"""

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    name: str = "unnamed-provider"

    @abstractmethod
    def generate_sql(self, system_prompt: str, question: str) -> str:
        """Returns raw SQL text (may include markdown fences -- caller cleans it)."""
        raise NotImplementedError

    @abstractmethod
    def generate_answer(self, system_prompt: str, user_content: str) -> str:
        """Returns a plain-English answer string."""
        raise NotImplementedError

    def is_configured(self) -> bool:
        """Whether this provider has the credentials it needs to run at all."""
        return True
