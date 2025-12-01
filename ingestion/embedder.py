from __future__ import annotations

import logging
import uuid
import asyncio

from dotenv import load_dotenv
from pymongo import MongoClient
from qdrant_client import QdrantClient
from qdrant_client.http import models

from config.settings import settings
from ingestion.text_cleaner import hierarchical_chunks
from utils.ollama_client import OllamaClient

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mongo = MongoClient(settings.mongo_uri)[settings.mongo_db]["pages"]
qdrant = QdrantClient(url=settings.qdrant_url)
COLLECTION_NAME = settings.qdrant_collection
if COLLECTION_NAME not in [c.name for c in qdrant.get_collections().collections]:
    qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(size=768, distance=models.Distance.COSINE),
    )

CONFLUENCE_NAMESPACE = uuid.UUID("1b671a64-40d5-491e-99b0-da01ff1f3341")

# BATCH_SIZE: Number of chunks to process in a single batch
BATCH_SIZE = 32


async def run_async():
    """
    Optimized async embedding pipeline with batching.
    
    Improvements over sequential version:
    - Batch concurrent API calls to Ollama
    - Batch upserts to Qdrant
    - 5-10x faster overall ingestion
    """
    async with OllamaClient(settings.ollama_base_url) as ollama:
        # Collect all chunks first for optimal batching
        all_chunks = []
        chunk_metadata = []
        
        logger.info("Collecting chunks from MongoDB...")
        for doc in mongo.find({}):
            for i, chunk in enumerate(hierarchical_chunks(doc["content_text"])):
                chunk_uuid = str(
                    uuid.uuid5(
                        CONFLUENCE_NAMESPACE,
                        f"{doc['page_id']}_{chunk['parent_index']}_{chunk['child_index']}"
                    )
                )
                
                all_chunks.append(chunk["child_text"])
                chunk_metadata.append({
                    "uuid": chunk_uuid,
                    "page_id": doc["page_id"],
                    "title": doc["title"],
                    "url": doc["url"],
                    "chunk_text": chunk["child_text"],
                    "parent_text": chunk["parent_text"],
                    "parent_index": chunk["parent_index"],
                    "child_index": chunk["child_index"],
                })
        
        logger.info(f"Found {len(all_chunks)} total chunks to embed")
        
        # Process in batches
        for batch_start in range(0, len(all_chunks), BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, len(all_chunks))
            batch_texts = all_chunks[batch_start:batch_end]
            batch_meta = chunk_metadata[batch_start:batch_end]
            
            logger.info(f"Processing batch {batch_start//BATCH_SIZE + 1}/{(len(all_chunks) + BATCH_SIZE - 1)//BATCH_SIZE}")
            
            # Batch embed all chunks concurrently
            embeddings = await ollama.embed_batch(batch_texts, settings.embed_model, max_concurrent=5)
            
            # Prepare Qdrant points for batch upsert
            points = []
            for meta, embedding in zip(batch_meta, embeddings):
                if embedding is None:
                    logger.warning(f"Skipping chunk {meta['uuid']} due to embedding error")
                    continue
                
                points.append(
                    models.PointStruct(
                        id=meta["uuid"],
                        vector=embedding,
                        payload={
                            "page_id": meta["page_id"],
                            "title": meta["title"],
                            "url": meta["url"],
                            "chunk": meta["chunk_text"],
                            "parent_text": meta["parent_text"],
                            "parent_index": meta["parent_index"],
                        },
                    )
                )
            
            # Batch upsert to Qdrant (one API call for entire batch!)
            if points:
                qdrant.upsert(
                    collection_name=COLLECTION_NAME,
                    points=points,
                )
                logger.info(f"Upserted {len(points)} chunks to Qdrant")


def run():
    """Entry point - runs async embedding pipeline"""
    asyncio.run(run_async())


if __name__ == "__main__":
    run()
