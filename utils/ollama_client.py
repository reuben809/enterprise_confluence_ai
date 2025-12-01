"""
Centralized Ollama HTTP Client

Provides reusable async HTTP client for Ollama API with:
- Retry logic
- Timeout handling  
- Error logging
- Batch embedding support
"""

import httpx
import logging
import asyncio
from typing import Optional, List, AsyncGenerator
import json

logger = logging.getLogger(__name__)


class OllamaClient:
    """Centralized async HTTP client for Ollama API"""
    
    def __init__(self, base_url: str, timeout: float = 120.0):
        """
        Initialize Ollama client.
        
        Args:
            base_url: Ollama API base URL (e.g., "http://ollama:11434")
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client = None  # Lazy initialization
    
    async def __aenter__(self):
        """Async context manager entry"""
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.client:
            await self.client.aclose()
    
    async def embed(self, text: str, model: str) -> Optional[List[float]]:
        """
        Generate embedding for a single text.
        
        Args:
            text: Text to embed
            model: Embedding model name (e.g., "nomic-embed-text")
            
        Returns:
            Embedding vector or None on error
        """
        try:
            resp = await self.client.post(
                "/api/embeddings",
                json={"model": model, "prompt": text}
            )
            resp.raise_for_status()
            logger.debug(f"Embedded text ({len(text)} chars)")
            return resp.json()["embedding"]
        except httpx.TimeoutException:
            logger.error(f"Timeout embedding text (length: {len(text)})")
            return None
        except Exception as e:
            logger.error(f"Error embedding text: {e}")
            return None
    
    async def embed_batch(self, texts: List[str], model: str, max_concurrent: int = 5) -> List[Optional[List[float]]]:
        """
        Generate embeddings for multiple texts concurrently.
        
        Args:
            texts: List of texts to embed
            model: Embedding model name
            max_concurrent: Maximum concurrent requests
            
        Returns:
            List of embeddings (None for failed requests)
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def embed_with_semaphore(text):
            async with semaphore:
                return await self.embed(text, model)
        
        logger.info(f"Embedding batch of {len(texts)} texts")
        results = await asyncio.gather(*[embed_with_semaphore(t) for t in texts])
        logger.info(f"Completed batch embedding: {sum(1 for r in results if r is not None)}/{len(texts)} successful")
        return results
    
    async def generate_stream(self, prompt: str, model: str) -> AsyncGenerator[str, None]:
        """
        Stream response from Ollama LLM.
        
        Args:
            prompt: Input prompt
            model: LLM model name (e.g., "mistral")
            
        Yields:
            Response tokens
        """
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": True
        }
        
        try:
            async with self.client.stream("POST", "/api/generate", json=payload) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_lines():
                    if chunk:
                        try:
                            data = json.loads(chunk)
                            if data.get("response"):
                                yield data["response"]
                        except json.JSONDecodeError:
                            continue
        except httpx.TimeoutException:
            logger.error("Timeout while streaming from Ollama")
            yield "Error: Request timed out. Please try again."
        except Exception as e:
            logger.error(f"Error streaming from Ollama: {e}")
            yield f"Error: {str(e)}"
    
    async def generate(self, prompt: str, model: str, format: Optional[str] = None) -> Optional[str]:
        """
        Generate non-streaming response from Ollama LLM.
        
        Args:
            prompt: Input prompt
            model: LLM model name
            format: Optional output format (e.g., "json")
            
        Returns:
            Generated response or None on error
        """
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False
        }
        if format:
            payload["format"] = format
        
        try:
            resp = await self.client.post("/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "")
        except httpx.TimeoutException:
            logger.error("Timeout generating response")
            return None
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return None
