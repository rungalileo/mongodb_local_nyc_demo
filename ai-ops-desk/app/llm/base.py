"""
Simplified LLM layer using OpenAI wrapper

Provides a simple interface for LLM operations with automatic tracing.
"""

import os
from typing import List, Dict, Tuple, Any
import numpy as np
from dotenv import load_dotenv
# import openai
from galileo.openai import openai

# Load environment variables from .env file
load_dotenv()

class OpenAIProvider:
    """OpenAI provider with automatic tracing"""
    
    def __init__(self, api_key: str = None):
            
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key not provided")
            
        self.client = openai.OpenAI(api_key=self.api_key)
        self.embed_model = "text-embedding-3-small"
        self.chat_model = "gpt-4o-mini"
    
    async def embed(self, texts: List[str]) -> np.ndarray:
        """Generate embeddings using OpenAI"""
        try:
            response = self.client.embeddings.create(
                input=texts,
                model=self.embed_model
            )
            
            embeddings = []
            for item in response.data:
                embeddings.append(item.embedding)
            
            return np.array(embeddings, dtype=np.float32)
            
        except Exception as e:
            print(f"[OPENAI] Embedding failed: {e}")
            # Fallback to random embeddings
            return np.random.rand(len(texts), 1536).astype(np.float32)
    
    async def complete(self, prompt: str, **kwargs) -> str:
        """Generate completion using OpenAI Chat API"""
        try:
            messages = [{"role": "user", "content": prompt}]
            
            response = self.client.chat.completions.create(
                model=self.chat_model,
                messages=messages,
                temperature=kwargs.get("temperature", 0.7),
                max_tokens=kwargs.get("max_tokens", 512)
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            print(f"OopenAI Completion failed: {e}")
            # Fallback response
            return f"Unable to generate response due to API error: {str(e)}"
    
   
  
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
            raise Exception("No OpenAI API key or OpenAI not available")

    
    return _llm_provider
