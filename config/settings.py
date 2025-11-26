from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Central application settings loaded from environment variables."""

    mongo_uri: str = Field(default="mongodb://mongo:27017/", alias="MONGO_URI")
    mongo_db: str = Field(default="confluence", alias="MONGO_DB")
    base_url: str | None = Field(default=None, alias="BASE_URL")
    space_key: str | None = Field(default=None, alias="SPACE_KEY")
    pat: str | None = Field(default=None, alias="PAT")

    ollama_llm: str = Field(default="mistral:7b", alias="OLLAMA_LLM")
    embed_model: str = Field(default="nomic-embed-text", alias="EMBED_MODEL")
    ollama_url: str = Field(
        default="http://ollama:11434", env=["OLLAMA_URL_HOST", "OLLAMA_URL"]
    )

    qdrant_url: str = Field(
        default="http://qdrant:6333", env=["QDRANT_URL_HOST", "QDRANT_URL"]
    )
    qdrant_collection: str = Field(default="confluence_vectors", alias="QDRANT_COLLECTION")

    top_k: int = Field(default=4, alias="TOP_K")
    reranker_model: str | None = Field(default=None, alias="OLLAMA_RERANKER")

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore",
    }

    @property
    def ollama_base_url(self) -> str:
        return self.ollama_url.rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


settings = get_settings()