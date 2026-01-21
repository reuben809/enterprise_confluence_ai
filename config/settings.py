from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Central application settings loaded from environment variables."""

    # Mongo
    mongo_uri: str = Field(default="mongodb://mongo:27017/", alias="MONGO_URI")
    mongo_db: str = Field(default="confluence", alias="MONGO_DB")
    
    # Confluence
    base_url: str | None = Field(default=None, alias="BASE_URL")
    space_key: str | None = Field(default=None, alias="SPACE_KEY")
    pat: str | None = Field(default=None, alias="PAT")

    # Qdrant
    qdrant_url: str = Field(
        default="http://qdrant:6333", env=["QDRANT_URL_HOST", "QDRANT_URL"]
    )
    qdrant_collection: str = Field(default="confluence_vectors_fastembed", alias="QDRANT_COLLECTION")

    # LLM & Embeddings (New Schema)
    ollama_base_url: str = Field(default="http://localhost:1234/v1", alias="LLM_BASE_URL")
    ollama_llm: str = Field(default="local-model", alias="LLM_MODEL") 
    ollama_rerank_model: str = Field(default="ms-marco-TinyBERT-L-2-v2", alias="RERANK_MODEL")
    
    # FastEmbed uses local strings, mapped from config/env
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5", alias="EMBEDDING_MODEL")
    sparse_model: str = Field(default="prithivida/Splade_PP_en_v1", alias="SPARSE_MODEL")
    fastembed_cache_path: str = Field(default="./models_cache", alias="FASTEMBED_CACHE_PATH")

    # Retrieval Params
    top_k: int = Field(default=5, alias="TOP_K")
    retrieval_limit: int = Field(default=20, alias="RETRIEVAL_LIMIT")
    mmr_lambda: float = Field(default=0.7, alias="MMR_LAMBDA")
    embedding_dimension: int = Field(default=384, alias="EMBEDDING_DIMENSION")
    query_cache_size: int = Field(default=100, alias="QUERY_CACHE_SIZE")

    # Ingestion Params
    max_pages_to_crawl: int = Field(default=3000, alias="MAX_PAGES")
    crawl_delay_seconds: float = Field(default=0.1, alias="CRAWL_DELAY")
    batch_size: int = Field(default=64, alias="BATCH_SIZE")
    enable_incremental_sync: bool = Field(default=True, alias="INCREMENTAL_SYNC")

    # Chunking Params
    parent_chunk_size: int = Field(default=1400, alias="PARENT_CHUNK_SIZE")
    child_chunk_size: int = Field(default=400, alias="CHILD_CHUNK_SIZE")
    parent_overlap: int = Field(default=200, alias="PARENT_OVERLAP")
    child_overlap: int = Field(default=80, alias="CHILD_OVERLAP")

    model_config = {
        # Load .env first, then .env.local overrides (last file wins in pydantic-settings)
        "env_file": [".env", ".env.local"],
        "case_sensitive": False,
        "extra": "ignore",
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


settings = get_settings()