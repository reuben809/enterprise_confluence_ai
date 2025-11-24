import json
import sys
from typing import List, Tuple

import requests
from pymongo import MongoClient
from qdrant_client import QdrantClient

from chat.prompt_template import CHAT_SYSTEM_PROMPT_TEMPLATE
from config.settings import settings
from retrieval import HybridRetriever, Reranker, SelfRagFilter


OLLAMA_URL = settings.ollama_base_url

mongo_client = MongoClient(settings.mongo_uri)
qdrant = QdrantClient(url=settings.qdrant_url)
retriever = HybridRetriever(qdrant, settings.qdrant_collection)
reranker = Reranker(OLLAMA_URL, settings.reranker_model or settings.ollama_llm)
self_rag_filter = SelfRagFilter(OLLAMA_URL, settings.ollama_llm)

print("✅ Connected to MongoDB and Qdrant.", file=sys.stderr)
print("--- Type 'exit' or 'quit' to end the chat ---", file=sys.stderr)


def embed_query(text: str):
    """Generate embedding for a query using Ollama on localhost."""
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": settings.embed_model, "prompt": text},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]
    except Exception as e:  # pylint: disable=broad-except
        print(f"❌ Error in embed_query: {e}", file=sys.stderr)
        return None


def call_ollama(prompt: str):
    """Call Ollama LLM (streaming)."""
    try:
        payload = {
            "model": settings.ollama_llm,
            "prompt": prompt,
            "stream": True,
        }
        with requests.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            stream=True,
            timeout=120,
        ) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_lines():
                if chunk:
                    try:
                        data = json.loads(chunk)
                        if data.get("response"):
                            yield data["response"]
                        if data.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue
    except Exception as e:  # pylint: disable=broad-except
        print(f"❌ Error in call_ollama: {e}", file=sys.stderr)


def format_chat_history(messages):
    """Format history for the prompt."""
    history = ""
    for msg in messages:
        history += f"{msg['role'].title()}: {msg['content']}\n"
    return history.strip()


def build_context_and_sources(candidates: List[dict]) -> Tuple[str, List[dict]]:
    formatted_context = ""
    sources = []
    seen_parents = set()
    seen_urls = set()

    for c in candidates:
        meta = c["payload"]
        parent_key = f"{meta.get('page_id')}:{meta.get('parent_index')}"
        if parent_key in seen_parents:
            continue
        parent_text = meta.get("parent_text") or meta.get("chunk") or ""
        formatted_context += (
            f"- **{meta['title']}** ({meta['url']})\n\n{parent_text}\n\n"
        )
        seen_parents.add(parent_key)

        if meta.get("url") and meta["url"] not in seen_urls:
            sources.append({"title": meta.get("title"), "url": meta.get("url")})
            seen_urls.add(meta["url"])

        if len(seen_parents) >= settings.top_k:
            break

    return formatted_context.strip(), sources


def main():
    chat_history = []
    while True:
        try:
            question = input("\n🤔 You: ")
            if question.lower() in ["exit", "quit"]:
                print("👋 Goodbye!")
                break

            chat_history.append({"role": "user", "content": question})

            print("Embedding query...", file=sys.stderr)
            query_vector = embed_query(question)
            if query_vector is None:
                continue

            print("Running hybrid retrieval...", file=sys.stderr)
            hybrid_candidates = retriever.hybrid_search(
                question, query_vector, limit=settings.top_k * 3
            )
            reranked = reranker.rerank(
                question, hybrid_candidates, top_n=settings.top_k * 2
            )
            filtered = self_rag_filter.filter(question, reranked)

            formatted_context, sources = build_context_and_sources(filtered)
            if not formatted_context:
                print(
                    "\n🤖 Assistant: I don't have enough information in the provided documentation to answer that question.",
                    flush=True,
                )
                chat_history.append(
                    {"role": "assistant", "content": "I don't have enough information."}
                )
                continue

            prompt = CHAT_SYSTEM_PROMPT_TEMPLATE.format(
                formatted_context_with_sources=formatted_context,
                formatted_chat_history=format_chat_history(chat_history[:-1]),
                user_query=question,
            )

            print("Generating answer...", file=sys.stderr)
            print("\n🤖 Assistant: ", end="", flush=True)
            full_response = ""
            for token in call_ollama(prompt):
                print(token, end="", flush=True)
                full_response += token

            chat_history.append({"role": "assistant", "content": full_response})

            if sources:
                print("\n\n--- SOURCES ---")
                for src in sources:
                    print(f"- {src['title']} ({src['url']})")
                print("---")

        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            break
        except Exception as e:  # pylint: disable=broad-except
            print(f"\nAn error occurred: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
