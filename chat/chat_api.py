from fastapi import FastAPI
from pydantic import BaseModel
from qdrant_client import QdrantClient
from pymongo import MongoClient
import requests, os, json
from dotenv import load_dotenv
from .prompt_template import STRICT_SYSTEM_PROMPT

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB")
QDRANT_URL = os.getenv("QDRANT_URL")
OLLAMA_LLM = os.getenv("OLLAMA_LLM")
TOP_K = int(os.getenv("TOP_K", 4))

# Connect to MongoDB & Qdrant
mongo_client = MongoClient(MONGO_URI)
mongo_db = mongo_client[MONGO_DB]
pages_collection = mongo_db["pages"]
qdrant = QdrantClient(url=QDRANT_URL)

app = FastAPI(title="Enterprise Confluence Chat API")

class Query(BaseModel):
    question: str

def embed_query(text: str):
    """Generate embedding for a query using Ollama."""
    resp = requests.post(
        "http://ollama:11434/api/embeddings",
        json={"model": os.getenv("EMBED_MODEL"), "prompt": text},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]

def call_ollama(prompt: str):
    """Call Ollama LLM (Mistral-7B) with strict system prompt."""
    payload = {
        "model": OLLAMA_LLM,
        "prompt": prompt,
        "stream": False
    }
    resp = requests.post("http://ollama:11434/api/generate", json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return data.get("response", "").strip()

@app.post("/ask")
def ask(q: Query):
    # 1️⃣ Embed query
    query_vector = embed_query(q.question)

    # 2️⃣ Search top-K chunks in Qdrant
    results = qdrant.search(
        collection_name="confluence_vectors",
        query_vector=query_vector,
        limit=TOP_K,
    )

    # 3️⃣ Build formatted context
    formatted_context = ""
    for r in results:
        meta = r.payload
        formatted_context += f"- **{meta['title']}** ({meta['url']})\n\n{meta['chunk']}\n\n"

    if not formatted_context.strip():
        return {"answer": "I don't have enough information in the provided documentation to answer that question.", "sources": []}

    # 4️⃣ Build strict prompt
    prompt = STRICT_SYSTEM_PROMPT.format(
        formatted_context_with_sources=formatted_context.strip(),
        user_query=q.question
    )

    # 5️⃣ Generate LLM answer
    answer = call_ollama(prompt)

    # 6️⃣ Extract sources for transparency
    sources = []
    for r in results:
        meta = r.payload
        sources.append({"title": meta["title"], "url": meta["url"]})

    return {
        "answer": answer,
        "sources": sources
    }

@app.get("/")
def root():
    return {"message": "Confluence RAG Chat API is running"}
