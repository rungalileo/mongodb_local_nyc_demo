"""
Simplified LLM Client
"""

from app.llm.base import get_llm_provider
import os
from app.llm.base import OpenAIProvider
# Global LLM provider instance
_llm_provider = None


def get_llm_provider():
    """Get the global LLM provider instance"""
    global _llm_provider
    if _llm_provider is None:
        # Future extensiblity: add other LLM providers here
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            _llm_provider = OpenAIProvider(api_key)
        else:
            raise Exception("No OpenAI API key")

    
    return _llm_provider

class LLMClientSingleton:    
    _instance = None
    _client = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LLMClientSingleton, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._client is None:
            self._client = get_llm_provider()
    
    @property
    def client(self):
        return self._client

# Global singleton instance
openai_client = LLMClientSingleton()
