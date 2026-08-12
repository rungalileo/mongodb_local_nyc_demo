"""
Simplified LLM layer using OpenAI wrapper

Provides a simple interface for LLM operations with automatic tracing.
"""

import os
from typing import List, Dict, Tuple, Any, Optional
import numpy as np
from dotenv import load_dotenv
# Galileo-wrapped client: importing this patches openai's Completions.create
# *in place*, so every call through any OpenAI client auto-creates an `llm`
# span with token usage. Used for the app's LLM calls we DON'T hand-instrument.
from galileo.openai import openai
from galileo import galileo_context
from app.llm.token_usage import add_token_usage

# Load environment variables from .env file
load_dotenv()

# Trust the OS certificate store before the OpenAI client builds its TLS
# context (fixes corporate TLS-interception breaking OpenAI calls). Safe no-op
# in environments where certifi already works.
import app.tls_trust  # noqa: F401,E402

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
            print(f"  OpenAI embedding failed: {e}")
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
            print(f"  OpenAI completion failed: {e}")
            # Fallback response
            return f"Unable to generate response due to API error: {str(e)}"

    def _uninstrumented_create(self):
        """Return ``(completions, original_create)`` for the un-instrumented
        ``Completions.create``.

        galileo patches ``Completions.create`` in place (wrapping it with
        ``functools.wraps``), so ``__wrapped__`` is the pristine original that
        emits NO span. Calling it lets us hand-log exactly one llm span. Returns
        ``(None, None)`` if the original can't be found (galileo internals
        changed), so the caller can fall back to the instrumented client.
        """
        try:
            completions = self.client.chat.completions
            original = getattr(type(completions).create, "__wrapped__", None)
            if original is not None:
                return completions, original
        except Exception:
            pass
        return None, None

    def _log_llm_span(
        self, span_name: str, input_text: str, output_text: str, counts: Dict[str, int]
    ) -> None:
        """Hand-log a single `llm` span with explicit token usage onto the
        current trace. Best-effort — never breaks a run."""
        try:
            logger = galileo_context.get_logger_instance()
            if logger is not None:
                logger.add_llm_span(
                    input=input_text,
                    output=output_text,
                    model=self.chat_model,
                    name=span_name,
                    num_input_tokens=int(counts.get("input", 0) or 0),
                    num_output_tokens=int(counts.get("output", 0) or 0),
                    total_tokens=int(counts.get("total", 0) or 0),
                )
        except Exception:
            pass

    async def complete_with_usage(
        self, prompt: str, span_name: Optional[str] = None, **kwargs
    ) -> Tuple[str, Dict[str, int]]:
        """Chat completion that guarantees exactly ONE llm span with token usage.

        Why not just use the instrumented client? Its auto-span's token usage is
        dropped when the Agent Control observability bridge is active, so the
        token columns come up empty on control-on runs. Here we instead call the
        *un-instrumented* original (so no auto-span is created) and hand-log one
        span with explicit counts — populating tokens regardless of Agent
        Control, with zero risk of double counting (there is only ever one span).

        Falls back to the instrumented client if the original can't be resolved;
        in that fallback the auto-span already carries usage, so we do NOT
        hand-log (again, no double counting). Returns ``(text, {input, output,
        total})``; on error, a fallback string and zero usage.
        """
        zero = {"input": 0, "output": 0, "total": 0}
        messages = [{"role": "user", "content": prompt}]
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens", 512)
        completions, original = self._uninstrumented_create()
        try:
            if original is not None:
                # Un-instrumented path: no auto-span; we own the single span.
                response = original(
                    completions,
                    model=self.chat_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                text = response.choices[0].message.content
                usage = getattr(response, "usage", None)
                counts = {
                    "input": int(getattr(usage, "prompt_tokens", 0) or 0),
                    "output": int(getattr(usage, "completion_tokens", 0) or 0),
                    "total": int(getattr(usage, "total_tokens", 0) or 0),
                }
                add_token_usage(counts)
                if span_name:
                    self._log_llm_span(span_name, prompt, text, counts)
                return text, counts

            # Fallback: instrumented client auto-logs the span (with usage in
            # the normal path). Do NOT hand-log here.
            response = self.client.chat.completions.create(
                model=self.chat_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            usage = getattr(response, "usage", None)
            counts = {
                "input": int(getattr(usage, "prompt_tokens", 0) or 0),
                "output": int(getattr(usage, "completion_tokens", 0) or 0),
                "total": int(getattr(usage, "total_tokens", 0) or 0),
            }
            add_token_usage(counts)
            return response.choices[0].message.content, counts
        except Exception as e:
            print(f"  OpenAI completion (with usage) failed: {e}")
            return f"Unable to generate response due to API error: {str(e)}", zero
    
   
  
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
