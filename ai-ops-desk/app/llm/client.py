"""
OpenAI Client Singleton
"""

from app.llm.openai_client import OpenAIProvider

class OpenAIClientSingleton:
    """Singleton OpenAI client"""
    
    _instance = None
    _client = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(OpenAIClientSingleton, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._client is None:
            self._client = OpenAIProvider()
    
    @property
    def client(self):
        return self._client

# Global singleton instance
openai_client = OpenAIClientSingleton()
