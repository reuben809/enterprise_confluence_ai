import os
import requests
import sys
from qdrant_client import QdrantClient
from pymongo import MongoClient
from dotenv import load_dotenv
from chat.prompt_template import CHAT_SYSTEM_PROMPT_TEMPLATE
import json

# --- Configuration for CLI (Host) ---
load_dotenv()
OLLAMA_LLM = os.getenv("OLLAMA_LLM")
EMBED_MODEL = os.getenv("EMBED_MODEL")
TOP_K = int(os.getenv("TOP_K", 4))
MONGO_URI_HOST = "mongodb://localhost:27017/"
QDRANT_URL_HOST = "http://localhost:6333"
OLLAMA_URL_HOST = "http://localhost:11434"

# --- Connect to Services ---
try:
    mongo_client = MongoClient(MONGO_URI_HOST)
    mongo_db = mongo_client[os.getenv("MONGO_DB")]
    qdrant = QdrantClient(url=QDRANT_URL_HOST)
    print("✅ Connected to MongoDB and Qdrant on localhost.", file=sys.stderr)
    print("--- Type 'exit' or 'quit' to end the chat ---", file=sys.stderr)
except Exception as e:
    print(f"❌ Failed to connect to services on localhost: {e}", file=sys.stderr)
    sys.exit(1)


# --- Core Functions (Adapted for localhost) ---

def embed_query(text: str):
    """Generate embedding for a query using Ollama on localhost."""
    try:
        resp = requests.post(
            f"{OLLAMA_URL_HOST}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]
    except Exception as e:
        print(f"❌ Error in embed_query: {e}", file=sys.stderr)
        return None


def call_ollama(prompt: str):
    """Call Ollama LLM on localhost (streaming)."""
    try:
        payload = {
            "model": OLLAMA_LLM,
            "prompt": prompt,
            "stream": True  # Enable streaming
        }
        with requests.post(f"{OLLAMA_URL_HOST}/api/generate", json=payload, stream=True, timeout=120) as resp:
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
    except Exception as e:
        print(f"❌ Error in call_ollama: {e}", file=sys.stderr)


def format_chat_history(messages):
    """Format history for the prompt."""
    history = ""
    for msg in messages:
        history += f"{msg['role'].title()}: {msg['content']}\n"
    return history.strip()


# --- Main CLI Loop ---
def main():
    chat_history = []
    while True:
        try:
            # Get user input
            question = input("\n🤔 You: ")
            if question.lower() in ['exit', 'quit']:
                print("👋 Goodbye!")
                break

            chat_history.append({"role": "user", "content": question})

            # 1. Embed query
            print("Embedding query...", file=sys.stderr)  # Added debug print
            query_vector = embed_query(question)
            if query_vector is None:
                continue

            # 2. Search top-K chunks
            print("Searching context...", file=sys.stderr)  # Added debug print
            results = qdrant.search(
                collection_name="confluence_vectors",
                query_vector=query_vector,
                limit=TOP_K,
            )

            # 3. Build context and sources
            formatted_context = ""
            sources = []
            seen_urls = set()
            for r in results:
                meta = r.payload
                formatted_context += f"- **{meta['title']}** ({meta['url']})\n\n{meta['chunk']}\n\n"
                if meta['url'] not in seen_urls:
                    sources.append({"title": meta["title"], "url": meta["url"]})
                    seen_urls.add(meta['url'])

            if not formatted_context.strip():
                print(
                    "\n🤖 Assistant: I don't have enough information in the provided documentation to answer that question.",
                    flush=True)
                chat_history.append({"role": "assistant", "content": "I don't have enough information."})
                continue

            # 4. Build prompt
            prompt = CHAT_SYSTEM_PROMPT_TEMPLATE.format(
                formatted_context_with_sources=formatted_context.strip(),
                formatted_chat_history=format_chat_history(chat_history[:-1]),  # History *before* this question
                user_query=question
            )

            # 5. Generate and stream answer
            print("Generating answer...", file=sys.stderr)  # Added debug print
            print("\n🤖 Assistant: ", end="", flush=True)
            full_response = ""
            for token in call_ollama(prompt):
                print(token, end="", flush=True)
                full_response += token

            chat_history.append({"role": "assistant", "content": full_response})

            # 6. Print sources
            if sources:
                print("\n\n--- SOURCES ---")
                for src in sources:
                    print(f"- {src['title']} ({src['url']})")
                print("---")

        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"\nAn error occurred: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()