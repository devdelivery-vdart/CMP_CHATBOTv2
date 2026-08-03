"""
Defines the ORDER providers are tried in. To add a new provider (say,
Anthropic) later:
  1. Write providers/anthropic_provider.py implementing LLMProvider
     (copy groq_provider.py as a template).
  2. Import it below and add an instance to PROVIDER_CHAIN, in whatever
     priority position you want (e.g. append it as a third fallback).
No other file needs to change -- llm.py just walks this list.
"""

from providers.openai_provider import OpenAIProvider

# Order = priority. First configured provider that succeeds wins.
PROVIDER_CHAIN = [
    OpenAIProvider(),
    # Add more providers here later, e.g.:
    # GroqProvider(),
    # AnthropicProvider(),
]
