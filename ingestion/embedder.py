import os, logging, uuid, requests

from qdrant_client import QdrantClient

from qdrant_client.http import models

from pymongo import MongoClient

from dotenv import load_dotenv

# NEW: LangChain text splitter for context-aware chunks

from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")

MONGO_DB = os.getenv("MONGO_DB")

QDRANT_URL = os.getenv("QDRANT_URL")

EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

# Mongo

mongo = MongoClient(MONGO_URI)[MONGO_DB]["pages"]

# Qdrant

qdrant = QdrantClient(url=QDRANT_URL)

COLL = "confluence_vectors"

# Vector size for nomic-embed-text is 768 (adjust if you change models)

if COLL not in [c.name for c in qdrant.get_collections().collections]:
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

        # Prefer standard format: {"model": ..., "input": "text or [texts]"}

        r = requests.post(

            "http://[::1]:11434/api/embeddings",

            json={"model": EMBED_MODEL, "input": text},

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

    except Exception as e:

        logging.error(f"Embedding call failed: {e}")

        return None


# ---------- Main run ----------

def run():
    total_chunks = 0

    for doc in mongo.find({}, projection={"page_id": 1, "title": 1, "url": 1, "content_text": 1}):

        page_id = doc["page_id"]

        text = doc.get("content_text", "") or ""

        chunks = chunk_text_with_context(text, chunk_size=800, chunk_overlap=150)

        if not chunks:
            logging.info(f"⚠️ No text to embed for page {page_id} ({doc.get('title')})")

            continue

        for i, chunk in enumerate(chunks):

            vec = embed_once(chunk)

            if vec is None:
                logging.warning(f"Skipping chunk {i} for doc '{doc.get('title')}' due to embedding error.")

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

        logging.info(f"✅ Embedded {len(chunks)} chunks for: {doc.get('title')} ({page_id})")

    logging.info(f"🏁 Embedding complete. Total chunks embedded: {total_chunks}")


if __name__ == "__main__":
    run()

