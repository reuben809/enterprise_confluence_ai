from __future__ import annotations

import logging
import uuid

import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from qdrant_client import QdrantClient
from qdrant_client.http import models

from config.settings import settings
from ingestion.text_cleaner import hierarchical_chunks

load_dotenv()

logging.basicConfig(level=logging.INFO)

mongo = MongoClient(settings.mongo_uri)[settings.mongo_db]["pages"]
qdrant = QdrantClient(url=settings.qdrant_url)
COLLECTION_NAME = settings.qdrant_collection
if COLLECTION_NAME not in [c.name for c in qdrant.get_collections().collections]:
    qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(size=768, distance=models.Distance.COSINE),
    )

CONFLUENCE_NAMESPACE = uuid.UUID("1b671a64-40d5-491e-99b0-da01ff1f3341")


def embed(text_to_embed: str):
    """Robustly gets a single embedding from Ollama, with error checking."""

    try:
        r = requests.post(
            f"{settings.ollama_base_url}/api/embeddings",
            json={"model": settings.embed_model, "prompt": text_to_embed},
            timeout=60,
        )

        r.raise_for_status()
        json_response = r.json()

        if "error" in json_response:
            logging.error(f"Ollama API Error: {json_response['error']}")
            return None

        if "embedding" in json_response:
            return json_response["embedding"]
        logging.error(
            "Ollama response missing 'embedding' key. Response: %s", json_response
        )
        return None

    except requests.exceptions.HTTPError as http_err:
        logging.error("HTTP error occurred: %s - Response: %s", http_err, r.text)
        return None
    except requests.exceptions.ConnectionError as conn_err:
        logging.error("Connection error occurred: %s", conn_err)
        return None
    except Exception as e:  # pylint: disable=broad-except
        logging.error("An error occurred in embed function: %s", e)
        return None
def run():
    for doc in mongo.find({}):
        for i, chunk in enumerate(hierarchical_chunks(doc["content_text"])):
            vec = embed(chunk["child_text"])

            if vec is None:
                logging.warning(
                    "Skipping chunk %s for doc '%s' due to embedding error.",
                    i,
                    doc["title"],
                )
                continue

            chunk_uuid = str(
                uuid.uuid5(
                    CONFLUENCE_NAMESPACE, f"{doc['page_id']}_{chunk['parent_index']}_{chunk['child_index']}"
                )
            )

            qdrant.upsert(
                collection_name=COLLECTION_NAME,
                points=[
                    models.PointStruct(
                        id=chunk_uuid,
                        vector=vec,
                        payload={
                            "page_id": doc["page_id"],
                            "title": doc["title"],
                            "url": doc["url"],
                            "chunk": chunk["child_text"],
                            "parent_text": chunk["parent_text"],
                            "parent_index": chunk["parent_index"],
                        },
                    )
                ],
            )
            logging.info(
                "Embedded %s chunk %s.%s",
                doc["title"],
                chunk["parent_index"],
                chunk["child_index"],
            )


if __name__ == "__main__":
    run()
