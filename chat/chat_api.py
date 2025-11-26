import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from pymongo import MongoClient
from qdrant_client import QdrantClient

from config.settings import settings
from retrieval import HybridRetriever, Reranker, SelfRagFilter
from .prompt_template import CHAT_SYSTEM_PROMPT_TEMPLATE

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

MONGO_URI = settings.mongo_uri
MONGO_DB = settings.mongo_db
QDRANT_URL = settings.qdrant_url
OLLAMA_LLM = settings.ollama_llm
EMBED_MODEL = settings.embed_model
TOP_K = settings.top_k
OLLAMA_BASE_URL = settings.ollama_base_url

# --- Database Clients ---
try:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    mongo_db = mongo_client[MONGO_DB]
    pages_collection = mongo_db["pages"]
    feedback_collection = mongo_db["feedback"]
    logger.info("Successfully connected to MongoDB")
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {e}")
    raise

try:
    qdrant = QdrantClient(url=QDRANT_URL, timeout=10)
    retriever = HybridRetriever(qdrant, settings.qdrant_collection)
    logger.info("Successfully connected to Qdrant")
except Exception as e:
    logger.error(f"Failed to connect to Qdrant: {e}")
    raise

reranker = Reranker(OLLAMA_BASE_URL, settings.reranker_model or OLLAMA_LLM)
self_rag_filter = SelfRagFilter(OLLAMA_BASE_URL, OLLAMA_LLM)


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
        logger.info(f"Successfully embedded query (length: {len(text)} chars)")
        return resp.json()["embedding"]
    except httpx.TimeoutException:
        logger.error("Timeout while embedding query")
        return None
    except Exception as e:
        logger.error(f"Error embedding query: {e}")
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
    except httpx.TimeoutException:
        logger.error("Timeout while streaming from Ollama")
        yield "Error: Request timed out. Please try again with a shorter question."
    except Exception as e:
        logger.error(f"Error streaming from Ollama: {e}")
        yield f"Error: Could not get response from LLM. {e}"


def format_chat_history(messages: List[Message]):
    """Format history for the prompt."""
    history = ""
    for msg in messages:
        history += f"{msg.role.title()}: {msg.content}\n"
    return history.strip()


def build_context_and_sources(candidates: List[dict]):
    formatted_context = ""
    sources: List[Dict[str, Any]] = []
    seen_parents = set()
    seen_urls = set()
    source_number = 1

    for candidate in candidates:
        payload = candidate["payload"]
        parent_key = f"{payload.get('page_id')}:{payload.get('parent_index')}"
        if parent_key in seen_parents:
            continue
        parent_text = payload.get("parent_text") or payload.get("chunk") or ""
        
        # Add numbered source reference
        url = payload.get("url")
        title = payload['title']
        formatted_context += (
            f"[{source_number}] **{title}** ({url})\n\n{parent_text}\n\n"
        )
        seen_parents.add(parent_key)

        if url and url not in seen_urls:
            sources.append({"number": source_number, "title": title, "url": url})
            seen_urls.add(url)
            source_number += 1

        if len(seen_parents) >= TOP_K:
            break

    return formatted_context.strip() or "No relevant context found.", sources


# --- API Endpoints ---

@app.get("/")
def root():
    return {"message": "Confluence RAG Chat API is running"}


@app.get("/health")
async def health_check(request: Request):
    """Health check endpoint to verify all services are accessible."""
    health_status = {"status": "healthy"}
    
    # Check Qdrant
    try:
        qdrant.get_collections()
        health_status["qdrant"] = "ok"
        logger.info("Health check: Qdrant OK")
    except Exception as e:
        health_status["qdrant"] = f"error: {str(e)}"
        health_status["status"] = "unhealthy"
        logger.warning(f"Health check: Qdrant failed - {e}")
    
    # Check Ollama
    try:
        client = request.app.state.httpx_client
        resp = await client.get("/api/tags", timeout=5.0)
        resp.raise_for_status()
        health_status["ollama"] = "ok"
        logger.info("Health check: Ollama OK")
    except Exception as e:
        health_status["ollama"] = f"error: {str(e)}"
        health_status["status"] = "unhealthy"
        logger.warning(f"Health check: Ollama failed - {e}")
    
    # Check MongoDB
    try:
        mongo_client.server_info()
        health_status["mongodb"] = "ok"
        logger.info("Health check: MongoDB OK")
    except Exception as e:
        health_status["mongodb"] = f"error: {str(e)}"
        health_status["status"] = "unhealthy"
        logger.warning(f"Health check: MongoDB failed - {e}")
    
    status_code = 200 if health_status["status"] == "healthy" else 503
    return JSONResponse(content=health_status, status_code=status_code)


@app.post("/chat")
async def chat(q: ChatQuery, request: Request):
    """Main chat endpoint with comprehensive error handling."""
    logger.info(f"Received chat request: {q.question[:100]}...")
    
    # Get the client from app state
    client = request.app.state.httpx_client

    # 1️⃣ Embed query
    query_vector = await embed_query(q.question, client)
    if query_vector is None:
        # If embedding fails, return a valid event stream with the error
        async def error_stream():
            error_data = json.dumps({"type": "token", "data": "Error: Could not embed the user query."})
            yield f"data: {error_data}\n\n"
            end_data = json.dumps({"type": "end"})
            yield f"data: {end_data}\n\n"
        
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    # 2️⃣ Hybrid search + rerank + self-RAG filtering
    try:
        hybrid_candidates = retriever.hybrid_search(
            q.question, query_vector, limit=TOP_K * 3
        )
        logger.info(f"Retrieved {len(hybrid_candidates)} candidates from hybrid search")
        
        reranked = await asyncio.to_thread(
            reranker.rerank, q.question, hybrid_candidates, TOP_K * 2
        )
        logger.info(f"Reranked to {len(reranked)} candidates")
        
        filtered = await asyncio.to_thread(
            self_rag_filter.filter, q.question, reranked
        )
        logger.info(f"Filtered to {len(filtered)} final candidates")
    except Exception as e:
        logger.error(f"Error during retrieval pipeline: {e}")
        async def error_stream():
            error_data = json.dumps({"type": "token", "data": f"Error during document retrieval: {str(e)}"})
            yield f"data: {error_data}\n\n"
            end_data = json.dumps({"type": "end"})
            yield f"data: {end_data}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    # 3️⃣ Build context and extract sources
    formatted_context, sources = build_context_and_sources(filtered)

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
        raise HTTPException(status_code=500, detail=str(e)) from e
