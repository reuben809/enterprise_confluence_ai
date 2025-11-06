import os, logging, uuid, requests
from qdrant_client import QdrantClient
from qdrant_client.http import models
from pymongo import MongoClient
from dotenv import load_dotenv

# NEW: LangChain text splitter for context-aware chunks
from langchain_text_splitters import RecursiveCharacterTextSplitter

# --- THIS IS THE FIX ---
# Add logging configuration so the script outputs logs when run standalone
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
# -----------------------

# Load environment variables based on RUN_MODE
if os.getenv("RUN_MODE") == "local":
    load_dotenv(dotenv_path=".env.local")
else:
    load_dotenv()  # Loads .env by default if it exists

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB")
QDRANT_URL = os.getenv("QDRANT_URL")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

# Load the correct Ollama URL from the environment
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")

# Mongo
mongo = MongoClient(MONGO_URI)[MONGO_DB]["pages"]

# Qdrant
qdrant = QdrantClient(url=QDRANT_URL)
COLL = "confluence_vectors"

# Vector size for nomic-embed-text is 768 (adjust if you change models)
if COLL not in [c.name for c in qdrant.get_collections().collections]:
    logging.info(f"Creating Qdrant collection: {COLL}")
    qdrant.create_collection(
        collection_name=COLL,
        vectors_config=models.VectorParams(size=768, distance=models.Distance.COSINE)
    )

# Deterministic namespace for IDs
CONFLUENCE_NAMESPACE = uuid.UUID("1b671a64-40d5-491e-99b0-da01ff1f3341")


# ---------- NEW: Context-aware chunking ----------
def chunk_text_with_context(text: str, chunk_size: int = 800, chunk_overlap: int = 150):
    """
    Split text into chunks with overlap to preserve context continuity.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(text or "")


# ---------- Robust embedding against Ollama ----------
def embed_once(text: str):
    """
    Call Ollama embeddings endpoint. Supports both single and batched responses.
    Endpoint format differs across versions; handle both.
    """
    try:
        # The key is 'prompt', not 'input'
        r = requests.post(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
            timeout=60
        )
        r.raise_for_status()
        js = r.json()

        # Possible shapes:
        # 1) {"embedding": [...]}  (single)
        # 2) {"data":[{"embedding":[...]} , ...]} (batch)
        if isinstance(js, dict) and "embedding" in js:
            return js["embedding"]
        if isinstance(js, dict) and "data" in js and js["data"]:
            return js["data"][0]["embedding"]

        logging.error(f"Unexpected embeddings response: {js}")
        return None

    except requests.exceptions.ConnectionError as conn_err:
        # Log the URL it tried to connect to for easier debugging
        logging.error(f"Connection error occurred connecting to {OLLAMA_BASE_URL}: {conn_err}")
        return None
    except Exception as e:
        logging.error(f"Embedding call failed: {e}")
        return None


# ---------- Main run ----------
def run():
    logging.info("📚 Starting embedding generation...")
    total_chunks = 0
    for doc in mongo.find({}, projection={"page_id": 1, "title": 1, "url": 1, "content_text": 1}):
        page_id = doc["page_id"]
        text = doc.get("content_text", "") or ""

        chunks = chunk_text_with_context(text, chunk_size=800, chunk_overlap=150)

        if not chunks:
            logging.info(f"⚠️ No text to embed for page {page_id} ({doc.get('title')})")
            continue

        doc_chunks_embedded = 0
        for i, chunk in enumerate(chunks):
            if not chunk.strip():
                logging.warning(f"Skipping empty chunk {i} for doc '{doc.get('title')}'")
                continue

            vec = embed_once(chunk)

            # 'if not vec:' checks for both None AND an empty list []
            if not vec:
                logging.warning(
                    f"Skipping chunk {i} for doc '{doc.get('title')}' due to embedding error or empty vector.")
                continue

            # Deterministic per-page/chunk ID (stable upserts)
            chunk_id_str = f"{page_id}:{i}"
            chunk_uuid = str(uuid.uuid5(CONFLUENCE_NAMESPACE, chunk_id_str))

            qdrant.upsert(
                collection_name=COLL,
                points=[models.PointStruct(
                    id=chunk_uuid,
                    vector=vec,
                    payload={
                        "page_id": page_id,
                        "title": doc.get("title"),
                        "url": doc.get("url"),
                        "chunk_index": i,
                        "chunk": chunk
                    }
                )]
            )
            total_chunks += 1
            doc_chunks_embedded += 1

        if doc_chunks_embedded > 0:
            logging.info(f"✅ Embedded {doc_chunks_embedded} chunks for: {doc.get('title')} ({page_id})")

    logging.info(f"🏁 Embedding complete. Total chunks embedded: {total_chunks}")


if __name__ == "__main__":
    run()