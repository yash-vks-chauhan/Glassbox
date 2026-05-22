from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    llm_model: str = Field(
        default="meta-llama/llama-3.3-70b-instruct:free", alias="LLM_MODEL"
    )
    llm_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="LLM_BASE_URL"
    )
    llm_temperature: float = Field(default=0.1, alias="LLM_TEMPERATURE")
    local_llm: bool = Field(default=True, alias="GLASSBOX_LOCAL_LLM")

    embed_model: str = Field(default="BAAI/bge-small-en-v1.5", alias="EMBED_MODEL")
    chroma_dir: str = Field(default="./backend/chroma_store", alias="CHROMA_DIR")
    embedding_backend: str = Field(
        default="hash", alias="GLASSBOX_EMBEDDING_BACKEND"
    )

    database_url: str = Field(
        default="sqlite:///./backend/glassbox_local.db", alias="DATABASE_URL"
    )
    backend_port: int = Field(default=8000, alias="BACKEND_PORT")
    frontend_api_base: str = Field(
        default="http://localhost:8000", alias="FRONTEND_API_BASE"
    )
    rate_limit_per_min: int = Field(default=10, alias="RATE_LIMIT_PER_MIN")
    determinism_runs: int = Field(default=5, alias="DETERMINISM_RUNS")

    aws_region: str = Field(default="ap-south-1", alias="AWS_REGION")
    s3_corpus_bucket: str = Field(default="glassbox-corpus", alias="S3_CORPUS_BUCKET")

    @property
    def resolved_chroma_dir(self) -> Path:
        path = Path(self.chroma_dir)
        if path.is_absolute():
            return path
        return PROJECT_ROOT / path

    @property
    def resolved_database_url(self) -> str:
        if not self.database_url.startswith("sqlite:///./"):
            return self.database_url
        relative = self.database_url.replace("sqlite:///./", "", 1)
        return f"sqlite:///{PROJECT_ROOT / relative}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
