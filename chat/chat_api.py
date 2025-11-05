# from fastapi import FastAPI
# from pydantic import BaseModel
# from qdrant_client import QdrantClient
# from pymongo import MongoClient
# import requests, os, json
# from dotenv import load_dotenv
# from .prompt_template import STRICT_SYSTEM_PROMPT
#
# load_dotenv()
#
# MONGO_URI = os.getenv("MONGO_URI")
# MONGO_DB = os.getenv("MONGO_DB")
# QDRANT_URL = os.getenv("QDRANT_URL")
# OLLAMA_LLM = os.getenv("OLLAMA_LLM")
# TOP_K = int(os.getenv("TOP_K", 4))
#
# # Connect to MongoDB & Qdrant
# mongo_client = MongoClient(MONGO_URI)
# mongo_db = mongo_client[MONGO_DB]
# pages_collection = mongo_db["pages"]
# qdrant = QdrantClient(url=QDRANT_URL)
#
# app = FastAPI(title="Enterprise Confluence Chat API")
#
# class Query(BaseModel):
#     question: str
#
# def embed_query(text: str):
#     """Generate embedding for a query using Ollama."""
#     resp = requests.post(
#         "http://ollama:11434/api/embeddings",
#         json={"model": os.getenv("EMBED_MODEL"), "prompt": text},
#         timeout=60,
#     )
#     resp.raise_for_status()
#     return resp.json()["embedding"]
#
# def call_ollama(prompt: str):
#     """Call Ollama LLM (Mistral-7B) with strict system prompt."""
#     payload = {
#         "model": OLLAMA_LLM,
#         "prompt": prompt,
#         "stream": False
#     }
#     resp = requests.post("http://ollama:11434/api/generate", json=payload, timeout=120)
#     resp.raise_for_status()
#     data = resp.json()
#     return data.get("response", "").strip()
#
# @app.post("/ask")
# def ask(q: Query):
#     # 1️⃣ Embed query
#     query_vector = embed_query(q.question)
#
#     # 2️⃣ Search top-K chunks in Qdrant
#     results = qdrant.search(
#         collection_name="confluence_vectors",
#         query_vector=query_vector,
#         limit=TOP_K,
#     )
#
#     # 3️⃣ Build formatted context
#     formatted_context = ""
#     for r in results:
#         meta = r.payload
#         formatted_context += f"- **{meta['title']}** ({meta['url']})\n\n{meta['chunk']}\n\n"
#
#     if not formatted_context.strip():
#         return {"answer": "I don't have enough information in the provided documentation to answer that question.", "sources": []}
#
#     # 4️⃣ Build strict prompt
#     prompt = STRICT_SYSTEM_PROMPT.format(
#         formatted_context_with_sources=formatted_context.strip(),
#         user_query=q.question
#     )
#
#     # 5️⃣ Generate LLM answer
#     answer = call_ollama(prompt)
#
#     # 6️⃣ Extract sources for transparency
#     sources = []
#     for r in results:
#         meta = r.payload
#         sources.append({"title": meta["title"], "url": meta["url"]})
#
#     return {
#         "answer": answer,
#         "sources": sources
#     }
#
# @app.get("/")
# def root():
#     return {"message": "Confluence RAG Chat API is running"}


import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from qdrant_client import QdrantClient
from pymongo import MongoClient
import httpx, os, json
from dotenv import load_dotenv
from .prompt_template import CHAT_SYSTEM_PROMPT_TEMPLATE
from typing import List, Dict, Any, AsyncGenerator
from contextlib import asynccontextmanager

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB")
QDRANT_URL = os.getenv("QDRANT_URL")
OLLAMA_LLM = os.getenv("OLLAMA_LLM")
EMBED_MODEL = os.getenv("EMBED_MODEL")
TOP_K = int(os.getenv("TOP_K", 4))
OLLAMA_BASE_URL = "http://ollama:11434"

# --- Database Clients ---
mongo_client = MongoClient(MONGO_URI)
mongo_db = mongo_client[MONGO_DB]
pages_collection = mongo_db["pages"]
feedback_collection = mongo_db["feedback"]
qdrant = QdrantClient(url=QDRANT_URL)


# --- App Lifespan for HTTPX Client ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create a persistent AsyncClient
    app.state.httpx_client = httpx.AsyncClient(base_url=OLLAMA_BASE_URL, timeout=120.0)
    yield
    # Shutdown: Close the client
    await app.state.httpx_client.aclose()


app = FastAPI(title="Enterprise Confluence Chat API", lifespan=lifespan)


# --- Pydantic Models ---

class Message(BaseModel):
    role: str
    content: str


class ChatQuery(BaseModel):
    question: str
    history: List[Message]


class Feedback(BaseModel):
    question: str
    answer: str
    feedback: str  # "positive" or "negative"
    sources: List[Dict[str, Any]]


# --- Async Helper Functions ---

async def embed_query(text: str, client: httpx.AsyncClient):
    """Generate embedding for a query using Ollama (async)."""
    try:
        resp = await client.post(
            "/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
        )
        resp.raise_for_status()
        return resp.json()["embedding"]
    except Exception as e:
        print(f"Error embedding query: {e}")
        return None


async def call_ollama_stream(prompt: str, client: httpx.AsyncClient) -> AsyncGenerator[str, None]:
    """Stream response from Ollama LLM (async)."""
    payload = {
        "model": OLLAMA_LLM,
        "prompt": prompt,
        "stream": True
    }
    try:
        async with client.stream("POST", "/api/generate", json=payload) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_lines():
                if chunk:
                    try:
                        data = json.loads(chunk)
                        if data.get("response"):
                            yield data["response"]
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        print(f"Error streaming from Ollama: {e}")
        yield f"Error: Could not get response from LLM. {e}"


def format_chat_history(messages: List[Message]):
    """Format history for the prompt."""
    history = ""
    for msg in messages:
        history += f"{msg.role.title()}: {msg.content}\n"
    return history.strip()


# --- API Endpoints ---

@app.get("/")
def root():
    return {"message": "Confluence RAG Chat API is running"}


@app.post("/chat")
async def chat(q: ChatQuery, request: Request):
    # Get the client from app state
    client = request.app.state.httpx_client

    # 1️⃣ Embed query
    query_vector = await embed_query(q.question, client)
    if query_vector is None:
        # --- THIS IS THE FIX ---
        # If embedding fails, return a valid event stream with the error
        async def error_stream():
            error_data = json.dumps({"type": "token", "data": "Error: Could not embed the user query."})
            yield f"data: {error_data}\n\n"
            end_data = json.dumps({"type": "end"})
            yield f"data: {end_data}\n\n"

        return StreamingResponse(error_stream(), media_type="text/event-stream")

    # 2️⃣ Search top-K chunks in Qdrant (this is still synchronous)
    results = qdrant.search(
        collection_name="confluence_vectors",
        query_vector=query_vector,
        limit=TOP_K,
    )

    # 3️⃣ Build context and extract sources
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
        formatted_context = "No relevant context found."

    # 4️⃣ Build prompt
    prompt = CHAT_SYSTEM_PROMPT_TEMPLATE.format(
        formatted_context_with_sources=formatted_context.strip(),
        formatted_chat_history=format_chat_history(q.history),
        user_query=q.question
    )

    # 5️⃣ Generate and stream response
    async def stream_generator() -> AsyncGenerator[str, None]:
        # First, yield the sources as a special event
        source_data = json.dumps({"type": "sources", "data": sources})
        yield f"data: {source_data}\n\n"

        # Then, yield the LLM tokens as they come
        async for token in call_ollama_stream(prompt, client):
            token_data = json.dumps({"type": "token", "data": token})
            yield f"data: {token_data}\n\n"

        # Finally, send an end event
        end_data = json.dumps({"type": "end"})
        yield f"data: {end_data}\n\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@app.post("/feedback")
def feedback(f: Feedback):
    try:
        feedback_collection.insert_one(f.dict())
        return {"status": "success", "message": "Feedback received"}
    except Exception as e:
        return {"status": "error", "message": str(e)}