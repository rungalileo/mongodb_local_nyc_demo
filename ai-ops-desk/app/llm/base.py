"""
LLM abstraction layer

Provides a simple interface for LLM operations with OpenAI adapter implementation
and mock provider for development.
"""

import os
from abc import ABC, abstractmethod
from typing import List, Dict, Tuple, Any
import numpy as np
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class LLMProvider(ABC):
    """Abstract base class for LLM providers"""
    
    @abstractmethod
    async def embed(self, texts: List[str]) -> np.ndarray:
        """Generate embeddings for a list of texts"""
        pass
    
    @abstractmethod
    async def complete(self, prompt: str, **kwargs) -> str:
        """Generate text completion from prompt"""
        pass
    
    @abstractmethod
    async def classify_routing(self, text: str) -> Tuple[str, Dict[str, float]]:
        """Classify text for routing with confidence scores"""
        pass


class MockLLMProvider(LLMProvider):
    """Mock LLM provider for local development without API keys"""
    
    async def embed(self, texts: List[str]) -> np.ndarray:
        # Generate deterministic embeddings for demo
        embeddings = []
        for text in texts:
            # Simple hash-based embedding for consistency
            hash_val = hash(text) % (2**31)
            np.random.seed(hash_val)
            embedding = np.random.rand(1536).astype(np.float32)
            embeddings.append(embedding)
        return np.array(embeddings)
    
    async def complete(self, prompt: str, **kwargs) -> str:
        # Mock completion based on prompt content
        prompt_lower = prompt.lower()
        
        if "policy" in prompt_lower and "refund" in prompt_lower:
            return "Based on policy v23 for EU region, electronics purchases can be returned within 14 days of purchase. This policy covers all electronic devices excluding custom-built items. Refunds will be processed in the original currency (EUR)."
        elif "policy" in prompt_lower:
            return "Policy v23 applies to your region with standard return windows and coverage for electronic items."
        elif "claim" in prompt_lower or "records" in prompt_lower:
            return "Found 3 recent claims totaling €129.99. Most recent claim is in reopened state, updated on 2024-08-15. Previous claims show consistent electronics purchases."
        elif "privacy" in prompt_lower:
            return "PII detection complete. Email addresses and personal identifiers have been redacted. Compliance check passed for EU GDPR requirements."
        elif "action" in prompt_lower or "refund" in prompt_lower:
            return "Processed partial refund of €129.99 for claim. Refund API call completed successfully with 200ms latency. Transaction ID: RF_20240815_001."
        else:
            return f"Generated response based on context: {prompt[:100]}..."
    
    async def classify_routing(self, text: str) -> Tuple[str, Dict[str, float]]:
        # Mock routing based on keywords with some intelligence
        text_lower = text.lower()
        
        # Score each route
        scores = {
            "billing": 0.1,
            "claims": 0.1, 
            "policy": 0.1,
            "privacy": 0.1,
            "escalation": 0.1
        }
        
        # Billing keywords
        if any(word in text_lower for word in ["refund", "billing", "payment", "charge", "invoice"]):
            scores["billing"] += 0.3
        
        # Claims keywords
        if any(word in text_lower for word in ["claim", "return", "reopen", "order", "purchase"]):
            scores["claims"] += 0.4
            
        # Policy keywords
        if any(word in text_lower for word in ["policy", "terms", "what's", "rules", "can i"]):
            scores["policy"] += 0.5
            
        # Privacy keywords  
        if any(word in text_lower for word in ["privacy", "gdpr", "delete", "personal", "data"]):
            scores["privacy"] += 0.6
            
        # Electronics keywords boost claims/policy
        if any(word in text_lower for word in ["electronic", "laptop", "phone", "device"]):
            scores["claims"] += 0.2
            scores["policy"] += 0.1
            
        # Normalize scores
        total = sum(scores.values())
        probs = {k: v/total for k, v in scores.items()}
        
        # Get top route
        top_route = max(probs.keys(), key=lambda k: probs[k])
        
        return top_route, probs


# Global LLM provider instance
_llm_provider = None


def get_llm_provider() -> LLMProvider:
    """Get the global LLM provider instance"""
    global _llm_provider
    if _llm_provider is None:
        # Try to initialize OpenAI provider, fall back to mock
        try:
            from app.llm.openai_client import OpenAIProvider
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                _llm_provider = OpenAIProvider(api_key)
                print("[LLM] Using OpenAI provider")
            else:
                _llm_provider = MockLLMProvider()
                print("[LLM] Using Mock provider (no OpenAI API key)")
        except ImportError:
            _llm_provider = MockLLMProvider()
            print("[LLM] Using Mock provider (OpenAI not available)")
    
    return _llm_provider
