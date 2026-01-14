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
        
        OPTIMIZED: Uses pre-fetched vectors from Qdrant instead of re-embedding.
        This reduces complexity from O(n² × embedding_time) to O(n × k).
        
        Args:
            query_embedding: The query vector (numpy array)
            candidates: List of search results WITH pre-fetched 'vector' field
            limit: Number of results to return
            lambda_param: Balance between relevance (1.0) and diversity (0.0)
                         Default 0.7 = 70% relevance, 30% diversity
        
        Returns:
            Reordered list prioritizing both relevance and diversity
        """
        if len(candidates) <= limit:
            return candidates
        
        n_candidates = len(candidates)
        
        # Extract pre-computed embeddings from candidates (fetched from Qdrant)
        # If vectors weren't fetched, fall back to zeros (shouldn't happen with correct query)
        embeddings = np.zeros((n_candidates, 384))
        for i, c in enumerate(candidates):
            if "vector" in c and c["vector"] is not None:
                # Qdrant returns vectors in the 'vector' field
                vec = c["vector"].get("dense", None)
                if vec is not None:
                    embeddings[i] = np.array(vec)
        
        # Normalize query embedding
        query_norm = query_embedding / (np.linalg.norm(query_embedding) + 1e-10)
        
        # Pre-compute all relevance scores (query similarity) using vectorized operation
        embedding_norms = np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-10
        normalized_embeddings = embeddings / embedding_norms
        relevance_scores = np.dot(normalized_embeddings, query_norm)
        
        # Track selected indices and remaining indices
        selected_indices = []
        remaining_mask = np.ones(n_candidates, dtype=bool)
        
        # Select k items using MMR
        for _ in range(min(limit, n_candidates)):
            if not remaining_mask.any():
                break
            
            # Get indices of remaining candidates
            remaining_indices = np.where(remaining_mask)[0]
            
            if len(selected_indices) == 0:
                # First selection: pick highest relevance
                best_remaining_idx = remaining_indices[np.argmax(relevance_scores[remaining_indices])]
            else:
                # Compute MMR scores for remaining candidates
                mmr_scores = np.zeros(len(remaining_indices))
                
                # Get embeddings of selected items
                selected_embeddings = normalized_embeddings[selected_indices]
                
                for j, idx in enumerate(remaining_indices):
                    # Relevance component
                    rel = relevance_scores[idx]
                    
                    # Diversity component: max similarity to any selected item
                    similarities_to_selected = np.dot(selected_embeddings, normalized_embeddings[idx])
                    max_sim = np.max(similarities_to_selected) if len(similarities_to_selected) > 0 else 0.0
                    
                    # MMR formula: λ * relevance - (1-λ) * max_similarity_to_selected
                    mmr_scores[j] = lambda_param * rel - (1 - lambda_param) * max_sim
                
                best_remaining_idx = remaining_indices[np.argmax(mmr_scores)]
            
            selected_indices.append(best_remaining_idx)
            remaining_mask[best_remaining_idx] = False
        
        # Return candidates in MMR order
        return [candidates[i] for i in selected_indices]

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

        # OPTIMIZED: Fetch pre-computed dense vectors when MMR is enabled
        # This eliminates the need to re-embed candidates during MMR
        results = self.qdrant.query_points(
            collection_name=self.collection_name,
            prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=fetch_limit if use_mmr else limit,
            with_payload=True,
            with_vectors=["dense"] if use_mmr else None  # Fetch vectors only when needed
        ).points

        # 3. Format results (include vectors if fetched for MMR)
        hits = []
        for hit in results:
            hit_dict = {
                "id": str(hit.id),
                "payload": hit.payload,
                "score": hit.score
            }
            # Include vectors for MMR processing
            if use_mmr and hit.vector is not None:
                hit_dict["vector"] = hit.vector
            hits.append(hit_dict)
        
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
