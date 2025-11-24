from functools import lru_cache
from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    """Central application settings loaded from environment variables."""

    mongo_uri: str = Field("mongodb://localhost:27017/", env="MONGO_URI")
    mongo_db: str = Field("confluence", env="MONGO_DB")
    base_url: str | None = Field(default=None, env="BASE_URL")
    space_key: str | None = Field(default=None, env="SPACE_KEY")
    pat: str | None = Field(default=None, env="PAT")

    ollama_llm: str = Field("llama3", env="OLLAMA_LLM")
    embed_model: str = Field("nomic-embed-text", env="EMBED_MODEL")
    ollama_url: str = Field(
        "http://[::1]:11434", env=["OLLAMA_URL_HOST", "OLLAMA_URL"]
    )

    qdrant_url: str = Field(
        "http://[::1]:6333", env=["QDRANT_URL_HOST", "QDRANT_URL"]
    )
    qdrant_collection: str = Field("confluence_vectors", env="QDRANT_COLLECTION")

    top_k: int = Field(4, env="TOP_K")
    reranker_model: str | None = Field(default=None, env="OLLAMA_RERANKER")

    class Config:
        env_file = ".env"
        case_sensitive = False

    @property
    def ollama_base_url(self) -> str:
        return self.ollama_url.rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""

    return Settings()


settings = get_settings()
