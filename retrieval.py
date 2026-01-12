from __future__ import annotations

import logging
import hashlib
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from qdrant_client import QdrantClient, models
from fastembed import TextEmbedding, SparseTextEmbedding
from flashrank import Ranker, RerankRequest

from config.settings import settings

logger = logging.getLogger(__name__)

class HybridRetriever:
    """
    State-of-the-art Hybrid Retriever using Qdrant Native Sparse Vectors.
    No in-memory indices. Fully scalable.
    """

    def __init__(
        self, 
        qdrant: QdrantClient, 
        collection_name: str,
        dense_model_name: str = "BAAI/bge-small-en-v1.5",
        sparse_model_name: str = "prithivida/Splade_PP_en_v1"
    ):
        self.qdrant = qdrant
        self.collection_name = collection_name
        
        # Load embedding models using configurable cache path
        logger.info(f"Initializing HybridRetriever models from {settings.fastembed_cache_path}...")
        self.dense_model = TextEmbedding(
            model_name=dense_model_name,
            cache_dir=settings.fastembed_cache_path,
            local_files_only=True
        )
        self.sparse_model = SparseTextEmbedding(
            model_name=sparse_model_name,
            cache_dir=settings.fastembed_cache_path,
            local_files_only=True
        )
        
        # Query cache for repeated queries
        self._cache: Dict[str, List[Dict[str, Any]]] = {}
        self._cache_max_size = 100

    def _get_cache_key(self, query: str, limit: int, use_mmr: bool) -> str:
        """Generate cache key from query parameters."""
        return hashlib.md5(f"{query}:{limit}:{use_mmr}".encode()).hexdigest()

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors."""
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(vec1, vec2) / (norm1 * norm2))

    def _apply_mmr(
        self, 
        query_embedding: np.ndarray,
        candidates: List[Dict[str, Any]], 
        limit: int,
        lambda_param: float = 0.7
    ) -> List[Dict[str, Any]]:
        """
        Apply Maximal Marginal Relevance for diverse results.
        
        Args:
            query_embedding: The query vector
            candidates: List of search results with embeddings
            limit: Number of results to return
            lambda_param: Balance between relevance (1.0) and diversity (0.0)
                         Default 0.7 = 70% relevance, 30% diversity
        
        Returns:
            Reordered list prioritizing both relevance and diversity
        """
        if len(candidates) <= limit:
            return candidates
        
        selected = []
        remaining = candidates.copy()
        
        # Get embeddings for all candidates (we'll use dense for diversity calculation)
        candidate_embeddings = []
        for c in remaining:
            # Generate embedding for each chunk
            chunk_text = c["payload"].get("chunk", "")
            if chunk_text:
                emb = list(self.dense_model.embed([chunk_text]))[0]
                candidate_embeddings.append(emb)
            else:
                candidate_embeddings.append(np.zeros(384))  # Default for empty
        
        while len(selected) < limit and remaining:
            mmr_scores = []
            
            for i, (cand, cand_emb) in enumerate(zip(remaining, candidate_embeddings)):
                # Relevance: similarity to query
                relevance = self._cosine_similarity(query_embedding, cand_emb)
                
                # Diversity: max similarity to already selected items
                max_sim_to_selected = 0.0
                if selected:
                    for sel_idx in [candidates.index(s) for s in selected if s in candidates]:
                        sim = self._cosine_similarity(
                            cand_emb, 
                            candidate_embeddings[candidates.index(remaining[0]) if remaining else 0]
                        )
                        max_sim_to_selected = max(max_sim_to_selected, sim)
                
                # MMR score
                mmr = lambda_param * relevance - (1 - lambda_param) * max_sim_to_selected
                mmr_scores.append((i, mmr, cand))
            
            # Select highest MMR score
            mmr_scores.sort(key=lambda x: x[1], reverse=True)
            best_idx, _, best_cand = mmr_scores[0]
            
            selected.append(best_cand)
            remaining.pop(best_idx)
            candidate_embeddings.pop(best_idx)
        
        return selected

    def search(
        self, 
        query_text: str, 
        limit: int = 10, 
        use_mmr: bool = False,
        use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Perform Hybrid Search (Dense + Sparse) on Qdrant.
        
        Args:
            query_text: The search query
            limit: Number of results to return
            use_mmr: If True, apply MMR for diverse results
            use_cache: If True, use query cache
            
        Returns:
            List of search results
        """
        # Check cache
        cache_key = self._get_cache_key(query_text, limit, use_mmr)
        if use_cache and cache_key in self._cache:
            logger.info(f"Cache hit for query: {query_text[:50]}...")
            return self._cache[cache_key]
        
        # 1. Generate Query Embeddings
        query_dense = list(self.dense_model.embed([query_text]))[0]
        query_sparse_obj = list(self.sparse_model.embed([query_text]))[0]
        
        query_sparse = models.SparseVector(
            indices=query_sparse_obj.indices.tolist(),
            values=query_sparse_obj.values.tolist()
        )

        # 2. Execute Hybrid Query (Prefetch Dense + Sparse -> RRF Fusion)
        fetch_limit = limit * 3 if use_mmr else limit * 2
        prefetch = [
            models.Prefetch(
                query=query_dense.tolist(),
                using="dense",
                limit=fetch_limit, 
            ),
            models.Prefetch(
                query=query_sparse,
                using="sparse",
                limit=fetch_limit,
            ),
        ]

        results = self.qdrant.query_points(
            collection_name=self.collection_name,
            prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=fetch_limit if use_mmr else limit,
            with_payload=True
        ).points

        # 3. Format results
        hits = []
        for hit in results:
            hits.append({
                "id": str(hit.id),
                "payload": hit.payload,
                "score": hit.score
            })
        
        # 4. Apply MMR if requested
        if use_mmr and len(hits) > limit:
            hits = self._apply_mmr(query_dense, hits, limit)
        
        # 5. Cache results
        if use_cache:
            if len(self._cache) >= self._cache_max_size:
                # Remove oldest entry (simple FIFO)
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
            self._cache[cache_key] = hits
        
        return hits


class LocalReranker:
    """
    High-speed local reranker using FlashRank (TinyBERT).
    Replaces slow LLM calls.
    """
    def __init__(self, model_name: str = "ms-marco-TinyBERT-L-2-v2", cache_dir: str = None):
        try:
            # Use local cache to avoid downloading from HuggingFace
            model_cache = cache_dir or settings.fastembed_cache_path
            logger.info(f"Loading FlashRank model: {model_name} from {model_cache}...")
            self.ranker = Ranker(model_name=model_name, cache_dir=model_cache)
            logger.info("FlashRank loaded successfully!")
        except Exception as e:
            logger.warning(f"FlashRank failed to load: {e}. Using pass-through reranking.")
            self.ranker = None

    def rerank(self, query: str, candidates: List[Dict[str, Any]], top_n: int = 5) -> List[Dict[str, Any]]:
        """
        Rerank Qdrant results using Cross-Encoder logic (if available).
        """
        if not candidates:
            return []
        
        # If ranker is disabled, pass-through
        if self.ranker is None:
            return candidates[:top_n]

        # Prepare for FlashRank
        passages = []
        for c in candidates:
            text = c["payload"].get("chunk", "")
            passages.append({
                "id": c["id"],
                "text": text,
                "meta": c["payload"]
            })

        rerank_request = RerankRequest(query=query, passages=passages)
        results = self.ranker.rerank(rerank_request)

        # Map back to our format
        reranked = []
        for r in results[:top_n]:
            reranked.append({
                "id": r["id"],
                "payload": r["meta"],
                "score": r["score"]
            })
        
        return reranked
