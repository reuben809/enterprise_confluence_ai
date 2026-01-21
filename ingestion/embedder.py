"""
Embedder with Deduplication and Memory Optimization

Features:
- Deduplication: Checks if chunk exists before upserting
- Memory Streaming: Processes chunks directly from MongoDB cursor
- Configurable: All parameters from settings.py
"""

from __future__ import annotations

import logging
import uuid
import sys
import os
from typing import List, Dict, Any, Iterator

from dotenv import load_dotenv
from pymongo import MongoClient
from qdrant_client import QdrantClient
from qdrant_client.http import models
from fastembed import TextEmbedding, SparseTextEmbedding
from qdrant_client.models import PointIdsList

from config.settings import settings
from ingestion.text_cleaner import hierarchical_chunks

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

# Constants from settings
DENSE_MODEL_NAME = settings.embedding_model
SPARSE_MODEL_NAME = settings.sparse_model
BATCH_SIZE = settings.batch_size
EMBEDDING_DIM = settings.embedding_dimension
CONFLUENCE_NAMESPACE = uuid.UUID("1b671a64-40d5-491e-99b0-da01ff1f3341")


def init_qdrant(qdrant: QdrantClient, collection_name: str):
    """Initialize Qdrant collection with Dense and Sparse configurations."""
    if not qdrant.collection_exists(collection_name):
        logger.info(f"Creating collection {collection_name}...")
        qdrant.create_collection(
            collection_name=collection_name,
            vectors_config={
                "dense": models.VectorParams(
                    size=EMBEDDING_DIM,
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


def get_existing_chunk_ids(qdrant: QdrantClient, collection_name: str, chunk_ids: List[str]) -> set:
    """Check which chunk IDs already exist in Qdrant."""
    if not chunk_ids:
        return set()
    
    try:
        # Use scroll to check existing points
        existing = set()
        result = qdrant.retrieve(
            collection_name=collection_name,
            ids=chunk_ids,
            with_payload=False,
            with_vectors=False
        )
        existing = {str(point.id) for point in result}
        return existing
    except Exception as e:
        logger.warning(f"Could not check existing chunks: {e}")
        return set()


def stream_chunks_from_mongo(mongo_col) -> Iterator[Dict[str, Any]]:
    """
    Stream chunks directly from MongoDB cursor.
    Memory efficient - doesn't load all pages into memory.
    """
    cursor = mongo_col.find({})
    
    for doc in cursor:
        page_id = doc["page_id"]
        title = doc.get("title", "")
        url = doc.get("url", "")
        content_text = doc.get("content_text", "")
        
        # Extract linked pages
        linked_page_ids = doc.get("internal_links", [])
        if isinstance(linked_page_ids, list):
            linked_page_ids = [str(link) for link in linked_page_ids[:10]]
        else:
            linked_page_ids = []
        
        # NEW: Extract hierarchy metadata
        parent_page_id = doc.get("parent_page_id")
        breadcrumb = doc.get("breadcrumb", [])
        breadcrumb_titles = [b.get("title", "") for b in breadcrumb] if breadcrumb else []
        
        # NEW: Extract labels and author
        labels = doc.get("labels", [])
        author = doc.get("author", "Unknown")
        
        # Generate chunks for this page
        for chunk in hierarchical_chunks(
            content_text,
            parent_chunk_size=settings.parent_chunk_size,
            child_chunk_size=settings.child_chunk_size,
            parent_overlap=settings.parent_overlap,
            child_overlap=settings.child_overlap
        ):
            # Deterministic UUID
            chunk_uuid = str(
                uuid.uuid5(
                    CONFLUENCE_NAMESPACE,
                    f"{page_id}_{chunk['parent_index']}_{chunk['child_index']}"
                )
            )
            
            chunk_text = chunk["child_text"]
            has_table = "| " in chunk_text or "|-" in chunk_text
            
            # CONTEXTUAL PREFIX: Prepend title + breadcrumb for better embedding context
            # This helps the embedding model understand WHERE the chunk comes from
            if breadcrumb_titles:
                context_prefix = f"{title} > {' > '.join(breadcrumb_titles)}\n\n"
            else:
                context_prefix = f"{title}\n\n"
            
            # Text for embedding includes context; payload stores original chunk
            embedding_text = context_prefix + chunk_text
            
            yield {
                "id": chunk_uuid,
                "text": embedding_text,  # Contextual text for embedding
                "payload": {
                    "page_id": page_id,
                    "title": title,
                    "url": url,
                    "chunk": chunk_text,
                    "parent_text": chunk["parent_text"],
                    "parent_index": chunk["parent_index"],
                    "child_index": chunk["child_index"],
                    "linked_page_ids": linked_page_ids,
                    "has_table": has_table,
                    # NEW: Hierarchy for filtering/context
                    "parent_page_id": parent_page_id,
                    "breadcrumb": breadcrumb_titles,
                    # NEW: Labels for filtering
                    "labels": labels,
                    # NEW: Author for attribution
                    "author": author,
                }
            }


def run(skip_existing: bool = True):
    """
    Optimized embedding pipeline.
    
    Args:
        skip_existing: If True, skip chunks that already exist in Qdrant
    """
    # 1. Connect to DBs
    mongo = MongoClient(settings.mongo_uri)[settings.mongo_db]["pages"]
    qdrant = QdrantClient(url=settings.qdrant_url)
    COLLECTION_NAME = settings.qdrant_collection

    init_qdrant(qdrant, COLLECTION_NAME)

    # 2. Initialize Models
    cache_path = settings.fastembed_cache_path
    logger.info(f"Loading models from {cache_path}...")
    
    dense_model = TextEmbedding(
        model_name=DENSE_MODEL_NAME,
        cache_dir=cache_path,
        local_files_only=True
    )
    
    logger.info(f"Loading Sparse Model: {SPARSE_MODEL_NAME}...")
    sparse_model = SparseTextEmbedding(
        model_name=SPARSE_MODEL_NAME,
        cache_dir=cache_path,
        local_files_only=True
    )

    # 3. Process in batches (streaming from MongoDB)
    logger.info("Processing chunks from MongoDB...")
    
    batch_texts = []
    batch_meta = []
    total_processed = 0
    total_skipped = 0
    total_upserted = 0

    for chunk_data in stream_chunks_from_mongo(mongo):
        batch_texts.append(chunk_data["text"])
        batch_meta.append({"id": chunk_data["id"], "payload": chunk_data["payload"]})
        
        if len(batch_texts) >= BATCH_SIZE:
            # Process batch
            upserted, skipped = process_batch(
                qdrant, COLLECTION_NAME,
                dense_model, sparse_model,
                batch_texts, batch_meta,
                skip_existing
            )
            total_upserted += upserted
            total_skipped += skipped
            total_processed += len(batch_texts)
            
            logger.info(f"Processed {total_processed} chunks (upserted: {total_upserted}, skipped: {total_skipped})")
            
            batch_texts = []
            batch_meta = []
    
    # Process remaining batch
    if batch_texts:
        upserted, skipped = process_batch(
            qdrant, COLLECTION_NAME,
            dense_model, sparse_model,
            batch_texts, batch_meta,
            skip_existing
        )
        total_upserted += upserted
        total_skipped += skipped
        total_processed += len(batch_texts)
    
    logger.info(f"🚀 Ingestion complete!")
    logger.info(f"   📄 Total chunks: {total_processed}")
    logger.info(f"   ✅ Upserted: {total_upserted}")
    logger.info(f"   ⏭️ Skipped (existing): {total_skipped}")


def process_batch(
    qdrant: QdrantClient,
    collection_name: str,
    dense_model,
    sparse_model,
    batch_texts: List[str],
    batch_meta: List[Dict],
    skip_existing: bool
) -> tuple[int, int]:
    """
    Process a batch of chunks.
    
    Returns:
        Tuple of (upserted_count, skipped_count)
    """
    # Check for existing chunks if deduplication enabled
    if skip_existing:
        chunk_ids = [m["id"] for m in batch_meta]
        existing_ids = get_existing_chunk_ids(qdrant, collection_name, chunk_ids)
        
        if existing_ids:
            # Filter out existing chunks
            filtered_texts = []
            filtered_meta = []
            for text, meta in zip(batch_texts, batch_meta):
                if meta["id"] not in existing_ids:
                    filtered_texts.append(text)
                    filtered_meta.append(meta)
            
            skipped = len(existing_ids)
            batch_texts = filtered_texts
            batch_meta = filtered_meta
        else:
            skipped = 0
    else:
        skipped = 0
    
    if not batch_texts:
        return 0, skipped
    
    # Generate embeddings
    batch_dense = list(dense_model.embed(batch_texts))
    batch_sparse = list(sparse_model.embed(batch_texts))
    
    # Create points
    points = []
    for meta, dense, sparse in zip(batch_meta, batch_dense, batch_sparse):
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
        collection_name=collection_name,
        points=points
    )
    
    return len(points), skipped


if __name__ == "__main__":
    try:
        # Parse command line args
        skip_existing = "--force" not in sys.argv
        if not skip_existing:
            logger.info("Force mode: will re-embed existing chunks")
        
        run(skip_existing=skip_existing)
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"FATAL ERROR: {e}")
        sys.exit(1)
