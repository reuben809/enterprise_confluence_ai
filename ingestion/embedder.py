import os, logging
from qdrant_client import QdrantClient
from qdrant_client.http import models
from pymongo import MongoClient
from ingestion.text_cleaner import chunk_text
from dotenv import load_dotenv
import requests

load_dotenv()
MONGO_URI=os.getenv("MONGO_URI"); MONGO_DB=os.getenv("MONGO_DB")
QDRANT_URL=os.getenv("QDRANT_URL")
EMBED_MODEL=os.getenv("EMBED_MODEL")

mongo=MongoClient(MONGO_URI)[MONGO_DB]["pages"]
qdrant=QdrantClient(url=QDRANT_URL)
COLL="confluence_vectors"
if COLL not in [c.name for c in qdrant.get_collections().collections]:
    qdrant.create_collection(
        collection_name=COLL,
        vectors_config=models.VectorParams(size=4096, distance=models.Distance.COSINE)
    )

def embed(texts):
    r=requests.post("http://ollama:11434/api/embeddings",
                    json={"model":EMBED_MODEL,"input":texts})
    return [v["embedding"] for v in r.json()["data"]]

def run():
    for doc in mongo.find({}):
        for i,chunk in enumerate(chunk_text(doc["content_text"])):
            vec=embed([chunk])[0]
            qdrant.upsert(collection_name=COLL, points=[models.PointStruct(
                id=f"{doc['page_id']}_{i}",
                vector=vec,
                payload={
                    "page_id":doc["page_id"],
                    "title":doc["title"],
                    "url":doc["url"],
                    "chunk":chunk
                }
            )])
            logging.info(f"Embedded {doc['title']} chunk {i}")
