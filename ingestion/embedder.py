# import os, logging
# from qdrant_client import QdrantClient
# from qdrant_client.http import models
# from pymongo import MongoClient
# from ingestion.text_cleaner import chunk_text
# from dotenv import load_dotenv
# import requests
#
# load_dotenv()
# MONGO_URI=os.getenv("MONGO_URI"); MONGO_DB=os.getenv("MONGO_DB")
# QDRANT_URL=os.getenv("QDRANT_URL")
# EMBED_MODEL=os.getenv("EMBED_MODEL")
#
# mongo=MongoClient(MONGO_URI)[MONGO_DB]["pages"]
# qdrant=QdrantClient(url=QDRANT_URL)
# COLL="confluence_vectors"
# if COLL not in [c.name for c in qdrant.get_collections().collections]:
#     qdrant.create_collection(
#         collection_name=COLL,
#         vectors_config=models.VectorParams(size=4096, distance=models.Distance.COSINE)
#     )
#
# def embed(texts):
#     # r=requests.post("http://ollama:11434/api/embeddings",
#     #                 json={"model":EMBED_MODEL,"input":texts})
#     r = requests.post("http://[::1]:11434/api/embeddings",
#                       json={"model": EMBED_MODEL, "input": texts})
#     return [v["embedding"] for v in r.json()["data"]]
#
# def run():
#     for doc in mongo.find({}):
#         for i,chunk in enumerate(chunk_text(doc["content_text"])):
#             vec=embed([chunk])[0]
#             qdrant.upsert(collection_name=COLL, points=[models.PointStruct(
#                 id=f"{doc['page_id']}_{i}",
#                 vector=vec,
#                 payload={
#                     "page_id":doc["page_id"],
#                     "title":doc["title"],
#                     "url":doc["url"],
#                     "chunk":chunk
#                 }
#             )])
#             logging.info(f"Embedded {doc['title']} chunk {i}")



import os, logging
import uuid
from qdrant_client import QdrantClient
from qdrant_client.http import models
from pymongo import MongoClient
from ingestion.text_cleaner import chunk_text
from dotenv import load_dotenv
import requests

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI");
MONGO_DB = os.getenv("MONGO_DB")
QDRANT_URL = os.getenv("QDRANT_URL")
EMBED_MODEL = os.getenv("EMBED_MODEL")

mongo = MongoClient(MONGO_URI)[MONGO_DB]["pages"]
qdrant = QdrantClient(url=QDRANT_URL)
COLL = "confluence_vectors"
if COLL not in [c.name for c in qdrant.get_collections().collections]:
    qdrant.create_collection(
        collection_name=COLL,
        vectors_config=models.VectorParams(size=768, distance=models.Distance.COSINE)
    )

# --- NEW: Define a constant UUID namespace for generating deterministic IDs ---
CONFLUENCE_NAMESPACE = uuid.UUID('1b671a64-40d5-491e-99b0-da01ff1f3341')


def embed(text_to_embed: str):
    """
    Robustly gets a single embedding from Ollama, with error checking.
    """
    try:
        r = requests.post("http://[::1]:11434/api/embeddings",
                          json={"model": EMBED_MODEL, "prompt": text_to_embed},
                          timeout=60)

        r.raise_for_status()
        json_response = r.json()

        if "error" in json_response:
            logging.error(f"Ollama API Error: {json_response['error']}")
            return None

        if "embedding" in json_response:
            return json_response["embedding"]
        else:
            logging.error(f"Ollama response missing 'embedding' key. Response: {json_response}")
            return None

    except requests.exceptions.HTTPError as http_err:
        logging.error(f"HTTP error occurred: {http_err} - Response: {r.text}")
        return None
    except requests.exceptions.ConnectionError as conn_err:
        logging.error(f"Connection error occurred: {conn_err}")
        return None
    except Exception as e:
        logging.error(f"An error occurred in embed function: {e} - Response: {r.text}")
        return None


def run():
    for doc in mongo.find({}):
        for i, chunk in enumerate(chunk_text(doc["content_text"])):

            vec = embed(chunk)

            if vec is None:
                logging.warning(f"Skipping chunk {i} for doc '{doc['title']}' due to embedding error.")
                continue

                # --- THIS IS THE FIX ---
            # Create a unique, deterministic UUID for the chunk ID
            chunk_id_str = f"{doc['page_id']}_{i}"
            chunk_uuid = str(uuid.uuid5(CONFLUENCE_NAMESPACE, chunk_id_str))

            qdrant.upsert(collection_name=COLL, points=[models.PointStruct(
                id=chunk_uuid,  # Use the new UUID
                vector=vec,
                payload={
                    "page_id": doc["page_id"],
                    "title": doc["title"],
                    "url": doc["url"],
                    "chunk": chunk
                }
            )])
            logging.info(f"Embedded {doc['title']} chunk {i}")