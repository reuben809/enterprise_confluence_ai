from qdrant_client import QdrantClient

from config.settings import settings

QDRANT_URL_HOST = settings.qdrant_url
COLLECTION_NAME = settings.qdrant_collection

try:
    client = QdrantClient(url=QDRANT_URL_HOST)

    print(f"Connecting to Qdrant at {QDRANT_URL_HOST}...")

    # 1. Get collection info
    collection_info = client.get_collection(collection_name=COLLECTION_NAME)

    print("\n--- COLLECTION INFO ---")
    print(f"Status: {collection_info.status}")
    print(f"Vector size: {collection_info.config.params.vectors.size}")

    # 2. Get the total count of vectors
    # This is the most important part
    count = client.count(collection_name=COLLECTION_NAME, exact=True)
    print(f"\nTotal elements (vectors): {count.count}")

    # 3. Get one point to inspect its payload
    if count.count > 0:
        print("\n--- SAMPLE ELEMENT PAYLOAD ---")
        sample = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=1,
            with_payload=True,
            with_vectors=False  # We don't need to see the giant vector
        )
        print(sample[0].payload)
    else:
        print("\nDatabase is empty. Please run the ingestion script:")
        print("python -m ingestion.run_ingestion")

except Exception as e:
    print(f"\n❌ Error connecting or fetching data: {e}")
    print("Please ensure your docker-compose services are running.")
    print(f"Failed to connect to {QDRANT_URL_HOST}")