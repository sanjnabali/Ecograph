"""
src/ecograph/llm/__init__.py
"""

from ecograph.llm.groq_client import (
    ILLMClient,
    GroqClient,
    MockGroqClient,
    LLMQuotaExhaustedError,
    LLMResponseError,
    get_groq_client,
)

# Alias so files importing LLMClient or LLMClient still work
LLMClient = GroqClient

__all__ = [
    "ILLMClient",
    "LLMClient",       # alias for GroqClient
    "GroqClient",
    "MockGroqClient",
    "LLMQuotaExhaustedError",
    "LLMResponseError",
    "get_groq_client",
]