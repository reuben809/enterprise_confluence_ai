from __future__ import annotations

import logging
import uuid
import sys
import os
import ssl
from typing import List, Dict, Any

# --- MANUAL MODEL LOADING ---
# Since HuggingFace is blocked, models are loaded from local cache
# Path is configurable via FASTEMBED_CACHE_PATH in .env
# ----------------------------

from dotenv import load_dotenv
from pymongo import MongoClient
from qdrant_client import QdrantClient
from qdrant_client.http import models
from fastembed import TextEmbedding, SparseTextEmbedding

from config.settings import settings
from ingestion.text_cleaner import hierarchical_chunks

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

# Constants
# BAAI/bge-small-en-v1.5 = 384 dimensions
DENSE_MODEL_NAME = settings.embedding_model or "BAAI/bge-small-en-v1.5"
SPARSE_MODEL_NAME = "prithivida/Splade_PP_en_v1" 
BATCH_SIZE = 64  # Increased batch size as FastEmbed is efficient
CONFLUENCE_NAMESPACE = uuid.UUID("1b671a64-40d5-491e-99b0-da01ff1f3341")

def init_qdrant(qdrant: QdrantClient, collection_name: str):
    """Initialize Qdrant collection with Dense and Sparse configurations."""
    if not qdrant.collection_exists(collection_name):
        logger.info(f"Creating collection {collection_name}...")
        qdrant.create_collection(
            collection_name=collection_name,
            vectors_config={
                "dense": models.VectorParams(
                    size=384,  # bge-small-en-v1.5 dimension
                    distance=models.Distance.COSINE
                )
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(
                    index=models.SparseIndexParams(
                        on_disk=False,
                    )
                )
            }
        )
        logger.info("Collection created.")
    else:
        logger.info(f"Collection {collection_name} exists.")

def run():
    """
    Synchronous embedding pipeline using FastEmbed (CPU optimized).
    Generates both Dense and Sparse vectors locally.
    """
    # 1. Connect to DBs
    mongo = MongoClient(settings.mongo_uri)[settings.mongo_db]["pages"]
    qdrant = QdrantClient(url=settings.qdrant_url)
    COLLECTION_NAME = settings.qdrant_collection  # Should be 'confluence_vectors_fastembed'

    init_qdrant(qdrant, COLLECTION_NAME)

    # DEBUG: List directories to understand what FastEmbed sees
    cache_path = settings.fastembed_cache_path
    logger.info(f"DEBUG: Inspecting {cache_path}...")
    if os.path.exists(cache_path):
        for root, dirs, files in os.walk(cache_path):
            logger.info(f"Found: {root} -> {dirs}, {files}")
    else:
        logger.warning(f"Cache path does not exist: {cache_path}")

    # 2. Initialize Models (Lazy loading)
    # Using configurable cache path from settings
    dense_model = TextEmbedding(
        model_name="BAAI/bge-small-en-v1.5", 
        cache_dir=settings.fastembed_cache_path, 
        local_files_only=True
    )
    
    logger.info("Loading Sparse Model: prithivida/Splade_PP_en_v1...")
    sparse_model = SparseTextEmbedding(
        model_name="prithivida/Splade_PP_en_v1", 
        cache_dir=settings.fastembed_cache_path, 
        local_files_only=True
    )

    # 3. Collect Data
    logger.info("Reading docs from MongoDB...")
    all_chunks = []
    chunk_metadata = []

    # Iterate over all pages
    cursor = mongo.find({})
    for doc in cursor:
        # Create chunks
        for chunk in hierarchical_chunks(doc["content_text"]):
            # Deterministic UUID
            chunk_uuid = str(
                uuid.uuid5(
                    CONFLUENCE_NAMESPACE,
                    f"{doc['page_id']}_{chunk['parent_index']}_{chunk['child_index']}"
                )
            )
            
            chunk_text = chunk["child_text"]
            all_chunks.append(chunk_text)
            
            # Extract link metadata from MongoDB document
            linked_page_ids = doc.get("internal_links", [])
            if isinstance(linked_page_ids, list):
                # Extract page IDs from URLs if needed
                linked_page_ids = [str(link) for link in linked_page_ids[:10]]  # Limit to 10
            else:
                linked_page_ids = []
            
            # Detect if chunk contains table data
            has_table = "| " in chunk_text or "|-" in chunk_text
            
            chunk_metadata.append({
                "id": chunk_uuid,
                "payload": {
                    "page_id": doc["page_id"],
                    "title": doc["title"],
                    "url": doc["url"],
                    "chunk": chunk_text,
                    "parent_text": chunk["parent_text"],
                    "parent_index": chunk["parent_index"],
                    "child_index": chunk["child_index"],
                    # New metadata
                    "linked_page_ids": linked_page_ids,
                    "has_table": has_table,
                }
            })

    total_chunks = len(all_chunks)
    logger.info(f"Found {total_chunks} chunks to embed.")

    if total_chunks == 0:
        logger.warning("No chunks found. Exiting.")
        return

    # 4. Batch Processing
    # FastEmbed is efficient, but we process in batches to control memory and Qdrant upsert size
    for i in range(0, total_chunks, BATCH_SIZE):
        batch_end = min(i + BATCH_SIZE, total_chunks)
        batch_texts = all_chunks[i:batch_end]
        batch_meta = chunk_metadata[i:batch_end]
        
        logger.info(f"Processing batch {i}/{total_chunks}...")

        # Generate Dense Embeddings (Generator -> List)
        # list(dense_model.embed(batch_texts)) returns list of numpy arrays
        batch_dense = list(dense_model.embed(batch_texts))

        # Generate Sparse Embeddings
        # list(sparse_model.embed(batch_texts)) returns list of SparseEmbedding objects
        batch_sparse = list(sparse_model.embed(batch_texts))

        points = []
        for idx, (meta, dense, sparse) in enumerate(zip(batch_meta, batch_dense, batch_sparse)):
            
            # Convert SparseEmbedding to Qdrant format
            # sparse object has .indices and .values
            sparse_vector = models.SparseVector(
                indices=sparse.indices.tolist(),
                values=sparse.values.tolist()
            )

            points.append(
                models.PointStruct(
                    id=meta["id"],
                    vector={
                        "dense": dense.tolist(),
                        "sparse": sparse_vector
                    },
                    payload=meta["payload"]
                )
            )

        # Upsert to Qdrant
        qdrant.upsert(
            collection_name=COLLECTION_NAME,
            points=points
        )
    
    logger.info("Ingestion complete! 🚀")

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"FATAL ERROR: {e}")
        sys.exit(1)
