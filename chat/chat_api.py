import logging
import time
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from qdrant_client import QdrantClient

from config.settings import settings
from retrieval import HybridRetriever, LocalReranker
from utils.llm_client import LLMClient
from chat.prompt_template import CHAT_SYSTEM_PROMPT_TEMPLATE

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Confluence RAG API")

# --- Initialization ---
# 1. Database & Vector Store
qdrant_client = QdrantClient(url=settings.qdrant_url)

# 2. Components
retriever = HybridRetriever(
    qdrant=qdrant_client, 
    collection_name=settings.qdrant_collection
)
reranker = LocalReranker(model_name=settings.ollama_rerank_model or "ms-marco-TinyBERT-L-2-v2")
llm_client = LLMClient(base_url=settings.ollama_base_url) # Reusing 'ollama_base_url' config key for LLM URL for now

logger.info("✅ System Components Initialized")


# --- Data Models ---
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    question: str
    history: List[ChatMessage] = []

class FeedbackRequest(BaseModel):
    question: str
    answer: str
    sources: List[dict]
    feedback: str  # positive/negative


# --- Helper ---
def format_chat_history(messages: List[ChatMessage]) -> str:
    return "\n".join([f"{m.role.title()}: {m.content}" for m in messages])

def build_context(candidates: List[dict]) -> str:
    context = ""
    for c in candidates:
        meta = c["payload"]
        # Format: [1] **Title** (URL)
        # Content...
        context += f"Source: [{meta.get('title')}]({meta.get('url')})\n"
        context += f"{meta.get('chunk')}\n\n"
    return context


# --- Endpoints ---

@app.get("/health")
def health_check():
    return {"status": "ok", "components": ["fastapi", "qdrant", "fastembed", "flashrank"]}

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    start_time = time.time()
    logger.info(f"Received question: {request.question}")

    # 1. Retrieval (Hybrid: Dense + Sparse)
    # Get more candidates for reranking
    hybrid_results = retriever.search(request.question, limit=20)
    
    if not hybrid_results:
        return JSONResponse(content={"answer": "I couldn't find any relevant documents.", "sources": []})

    # 2. Reranking (FlashRank)
    # Rerank top 20 -> top 5
    reranked = reranker.rerank(request.question, hybrid_results, top_n=settings.top_k)
    
    # 3. Context Construction
    context_text = build_context(reranked)
    sources = [
        {"title": r["payload"].get("title"), "url": r["payload"].get("url")} 
        for r in reranked
    ]
    # Deduplicate sources
    unique_sources = []
    seen_urls = set()
    for s in sources:
        if s["url"] not in seen_urls:
            unique_sources.append(s)
            seen_urls.add(s["url"])

    # 4. Prompt Assembly
    full_prompt = CHAT_SYSTEM_PROMPT_TEMPLATE.format(
        formatted_context_with_sources=context_text,
        formatted_chat_history=format_chat_history(request.history),
        user_query=request.question
    )

    # 5. Streaming Generation
    async def response_generator():
        # First yield sources
        import json
        yield json.dumps({"type": "sources", "data": unique_sources}) + "\n"
        
        full_answer = ""
        async for token in llm_client.generate_stream(full_prompt, model=settings.ollama_llm):
            if token:
                full_answer += token
                yield json.dumps({"type": "token", "data": token}) + "\n"
        
        yield json.dumps({"type": "end"}) + "\n"
        
        logger.info(f"Chat processing took {time.time() - start_time:.2f}s")

    return StreamingResponse(response_generator(), media_type="application/x-ndjson")


@app.post("/feedback")
def feedback_endpoint(feedback: FeedbackRequest):
    # Log feedback to file or DB (Placeholder)
    logger.info(f"Feedback received: {feedback.feedback} for Q: {feedback.question}")
    return {"status": "received"}
