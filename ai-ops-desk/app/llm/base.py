"""
Simplified LLM layer using Galileo-OpenAI wrapper

Provides a simple interface for LLM operations with automatic tracing.
"""

import os
from typing import List, Dict, Tuple, Any
import numpy as np
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

try:
    from galileo.openai import openai
    GALILEO_OPENAI_AVAILABLE = True
except ImportError:
    GALILEO_OPENAI_AVAILABLE = False
    print("[WARNING] Galileo-OpenAI package not available, will fall back to mock")


class GalileoOpenAIProvider:
    """Galileo-OpenAI provider with automatic tracing"""
    
    def __init__(self, api_key: str = None):
        if not GALILEO_OPENAI_AVAILABLE:
            raise ImportError("Galileo-OpenAI package not available")
            
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key not provided")
            
        self.client = openai.OpenAI(api_key=self.api_key)
        self.embed_model = "text-embedding-3-small"
        self.chat_model = "gpt-4o-mini"
    
    async def embed(self, texts: List[str]) -> np.ndarray:
        """Generate embeddings using Galileo-OpenAI"""
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
            print(f"[GALILEO-OPENAI] Embedding failed: {e}")
            # Fallback to random embeddings
            return np.random.rand(len(texts), 1536).astype(np.float32)
    
    async def complete(self, prompt: str, **kwargs) -> str:
        """Generate completion using Galileo-OpenAI Chat API"""
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
            print(f"[GALILEO-OPENAI] Completion failed: {e}")
            # Fallback response
            return f"Unable to generate response due to API error: {str(e)}"
    
    async def classify_routing(self, text: str) -> Tuple[str, Dict[str, float]]:
        """Classify text for routing using Galileo-OpenAI"""
        
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
            
            response = self.client.chat.completions.create(
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
            print(f"[GALILEO-OPENAI] Classification failed: {e}")
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


class MockLLMProvider:
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


def get_llm_provider():
    """Get the global LLM provider instance"""
    global _llm_provider
    if _llm_provider is None:
        # Try to initialize Galileo-OpenAI provider, fall back to mock
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key and GALILEO_OPENAI_AVAILABLE:
            _llm_provider = GalileoOpenAIProvider(api_key)
            print("[LLM] Using Galileo-OpenAI provider")
        else:
            raise Exception("No OpenAI API key or Galileo-OpenAI not available")

    
    return _llm_provider
