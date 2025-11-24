from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional

import requests
from qdrant_client import QdrantClient
from rank_bm25 import BM25Okapi


def _tokenize(text: str) -> List[str]:
    return [t for t in (text or "").lower().split() if t]


class HybridRetriever:
    """Combine dense vectors with BM25 to improve recall."""

    def __init__(self, qdrant: QdrantClient, collection_name: str):
        self.qdrant = qdrant
        self.collection_name = collection_name
        self._bm25: Optional[BM25Okapi] = None
        self._bm25_payloads: List[Dict[str, Any]] = []

    def _build_bm25_index(self):
        offset = None
        payloads: List[Dict[str, Any]] = []
        tokenized_docs: List[List[str]] = []

        while True:
            points, offset = self.qdrant.scroll(
                collection_name=self.collection_name,
                limit=256,
                with_payload=True,
                with_vectors=False,
                offset=offset,
            )
            if not points:
                break
            for p in points:
                payloads.append({"id": str(p.id), "payload": p.payload})
                tokenized_docs.append(_tokenize(p.payload.get("chunk", "")))
            if offset is None:
                break

        if payloads:
            self._bm25 = BM25Okapi(tokenized_docs)
            self._bm25_payloads = payloads

    def _ensure_bm25(self):
        if self._bm25 is None:
            self._build_bm25_index()

    def hybrid_search(
        self, query_text: str, query_vector: List[float], limit: int = 10
    ) -> List[Dict[str, Any]]:
        self._ensure_bm25()

        vector_results = self.qdrant.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=limit * 2,
            with_payload=True,
        )

        candidates: Dict[str, Dict[str, Any]] = {}
        for result in vector_results:
            candidates[str(result.id)] = {
                "payload": result.payload,
                "vector_score": result.score,
                "bm25_score": 0.0,
            }

        if self._bm25:
            bm25_scores = self._bm25.get_scores(_tokenize(query_text))
            max_scores = sorted(
                enumerate(bm25_scores), key=lambda kv: kv[1], reverse=True
            )[: limit * 2]
            for idx, score in max_scores:
                if score <= 0:
                    continue
                payload_entry = self._bm25_payloads[idx]
                point_id = payload_entry["id"]
                entry = candidates.setdefault(
                    point_id,
                    {
                        "payload": payload_entry["payload"],
                        "vector_score": 0.0,
                        "bm25_score": 0.0,
                    },
                )
                entry["bm25_score"] = score

        max_vec = max((c.get("vector_score", 0.0) for c in candidates.values()), default=0.0)
        max_bm25 = max((c.get("bm25_score", 0.0) for c in candidates.values()), default=0.0)

        rescored = []
        for point_id, data in candidates.items():
            norm_vec = data.get("vector_score", 0.0) / max_vec if max_vec else 0.0
            norm_bm25 = data.get("bm25_score", 0.0) / max_bm25 if max_bm25 else 0.0
            combined = 0.6 * norm_vec + 0.4 * norm_bm25
            rescored.append(
                {
                    "id": point_id,
                    "payload": data["payload"],
                    "score": combined,
                    "vector_score": data.get("vector_score", 0.0),
                    "bm25_score": data.get("bm25_score", 0.0),
                }
            )

        return sorted(rescored, key=lambda r: r["score"], reverse=True)[:limit]


class Reranker:
    def __init__(self, ollama_url: str, model: str):
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model

    def _build_prompt(self, question: str, candidates: Iterable[Dict[str, Any]]) -> str:
        rows = [
            "Rate the relevance of each context chunk to the user question on a 0-1 scale.",
            "Return a JSON array of objects with id and score keys.",
            f"Question: {question}",
            "Contexts:",
        ]
        for idx, candidate in enumerate(candidates):
            snippet = candidate["payload"].get("parent_text") or candidate["payload"].get("chunk", "")
            rows.append(
                f"{idx + 1}. id={candidate['id']} text={snippet[:500]}"
            )
        rows.append("JSON Response:")
        return "\n".join(rows)

    def rerank(self, question: str, candidates: List[Dict[str, Any]], top_n: int) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        prompt = self._build_prompt(question, candidates)
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "format": "json",
                    "stream": False,
                },
                timeout=90,
            )
            resp.raise_for_status()
            response_text = resp.json().get("response", "[]")
            scores = json.loads(response_text)
            score_map = {str(item.get("id")): float(item.get("score", 0)) for item in scores}
        except Exception:
            score_map = {}

        rescored = []
        for c in candidates:
            rerank_score = score_map.get(str(c["id"]), 0)
            rescored.append({**c, "score": c.get("score", 0) + rerank_score})
        return sorted(rescored, key=lambda r: r["score"], reverse=True)[:top_n]


class SelfRagFilter:
    def __init__(self, ollama_url: str, model: str):
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model

    def _build_prompt(self, question: str, candidates: Iterable[Dict[str, Any]]) -> str:
        rows = [
            "Given the question and contexts, return the ids of contexts that directly support an answer.",
            "Use a JSON array of ids only.",
            f"Question: {question}",
            "Contexts:",
        ]
        for candidate in candidates:
            snippet = candidate["payload"].get("parent_text") or candidate["payload"].get("chunk", "")
            rows.append(f"id={candidate['id']} text={snippet[:500]}")
        rows.append("Supported ids as JSON array:")
        return "\n".join(rows)

    def filter(self, question: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        prompt = self._build_prompt(question, candidates)
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "format": "json",
                    "stream": False,
                },
                timeout=90,
            )
            resp.raise_for_status()
            response_text = resp.json().get("response", "[]")
            keep_ids = set(json.loads(response_text))
        except Exception:
            keep_ids = set()

        filtered = [c for c in candidates if str(c["id"]) in keep_ids]
        return filtered or candidates
