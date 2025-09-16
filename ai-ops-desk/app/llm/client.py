"""
Simplified LLM Client using Galileo-OpenAI wrapper
"""

from app.llm.base import get_llm_provider

class LLMClientSingleton:
    """Singleton LLM client using Galileo-OpenAI"""
    
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
