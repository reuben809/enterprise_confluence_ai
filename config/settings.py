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
    fastembed_cache_path: str = Field(default="./models_cache", alias="FASTEMBED_CACHE_PATH")

    # Params
    top_k: int = Field(default=5, alias="TOP_K")

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