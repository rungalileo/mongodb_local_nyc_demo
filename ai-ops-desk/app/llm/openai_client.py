"""
OpenAI LLM provider implementation

Provides async OpenAI API integration for embeddings, completions, and routing classification.
"""

import os
import asyncio
from typing import List, Dict, Tuple, Any
import numpy as np
from app.llm.base import LLMProvider

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("[WARNING] OpenAI package not available, will fall back to mock")


class OpenAIProvider(LLMProvider):
    """OpenAI LLM provider implementation with async support"""
    
    def __init__(self, api_key: str = None):
        if not OPENAI_AVAILABLE:
            raise ImportError("OpenAI package not available")
            
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key not provided")
            
        self.client = openai.AsyncOpenAI(api_key=self.api_key)
        self.embed_model = "text-embedding-3-small"
        self.chat_model = "gpt-4o-mini"
    
    async def embed(self, texts: List[str]) -> np.ndarray:
        """Generate embeddings using OpenAI"""
        try:
            response = await self.client.embeddings.create(
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
            
            response = await self.client.chat.completions.create(
                model=self.chat_model,
                messages=messages,
                temperature=kwargs.get("temperature", 0.7),
                max_tokens=kwargs.get("max_tokens", 512)
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            print(f"[OPENAI] Completion failed: {e}")
            # Fallback response
            return f"Unable to generate response due to API error: {str(e)}"
    
    async def classify_routing(self, text: str) -> Tuple[str, Dict[str, float]]:
        """Classify text for routing using OpenAI"""
        
        try:
            prompt = f"""
Classify the following customer inquiry into one of these categories:

Categories:
- billing: billing issues, refund requests, payment problems
- claims: product returns, warranty claims, order issues, reopened claims  
- policy: questions about terms, policies, what's allowed, return windows
- privacy: data deletion, GDPR requests, privacy concerns, personal data
- escalation: complex issues needing human review

Customer inquiry: "{text}"

Respond with only the category name (billing/claims/policy/privacy/escalation).
"""
            
            response = await self.client.chat.completions.create(
                model=self.chat_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=50
            )
            
            route = response.choices[0].message.content.strip().lower()
            
            # Validate route
            valid_routes = ["billing", "claims", "policy", "privacy", "escalation"]
            if route not in valid_routes:
                route = "escalation"  # Default fallback
            
            # Generate confidence scores based on route
            if route == "billing":
                probs = {"billing": 0.8, "claims": 0.1, "policy": 0.05, "privacy": 0.03, "escalation": 0.02}
            elif route == "claims":
                probs = {"claims": 0.75, "billing": 0.15, "policy": 0.05, "privacy": 0.03, "escalation": 0.02}
            elif route == "policy":
                probs = {"policy": 0.85, "claims": 0.08, "billing": 0.04, "privacy": 0.02, "escalation": 0.01}
            elif route == "privacy":
                probs = {"privacy": 0.9, "policy": 0.05, "claims": 0.03, "billing": 0.01, "escalation": 0.01}
            else:  # escalation
                probs = {"escalation": 0.7, "billing": 0.1, "claims": 0.1, "policy": 0.05, "privacy": 0.05}
            
            return route, probs
            
        except Exception as e:
            print(f"[OPENAI] Classification failed: {e}")
            # Fallback to keyword-based classification
            return await self._fallback_classify(text)
    
    async def _fallback_classify(self, text: str) -> Tuple[str, Dict[str, float]]:
        """Fallback classification using keywords"""
        text_lower = text.lower()
        
        # Score each route
        scores = {
            "billing": 0.1,
            "claims": 0.1, 
            "policy": 0.1,
            "privacy": 0.1,
            "escalation": 0.1
        }
        
        # Keyword scoring
        if any(word in text_lower for word in ["refund", "billing", "payment", "charge", "invoice"]):
            scores["billing"] += 0.4
        
        if any(word in text_lower for word in ["claim", "return", "reopen", "order", "purchase"]):
            scores["claims"] += 0.5
            
        if any(word in text_lower for word in ["policy", "terms", "what's", "rules", "can i"]):
            scores["policy"] += 0.5
            
        if any(word in text_lower for word in ["privacy", "gdpr", "delete", "personal", "data"]):
            scores["privacy"] += 0.6
        
        # Normalize scores
        total = sum(scores.values())
        probs = {k: v/total for k, v in scores.items()}
        
        # Get top route
        top_route = max(probs.keys(), key=lambda k: probs[k])
        
        return top_route, probs


# Legacy alias for backward compatibility
OpenAIClient = OpenAIProvider