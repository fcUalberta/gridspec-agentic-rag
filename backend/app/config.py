from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    fireworks_api_key: str = ""
    fireworks_chat_model: str = "accounts/fireworks/routers/glm-5p2-fast"
    fireworks_strong_model: str = "accounts/fireworks/models/glm-5p3"
    fireworks_embedding_model: str = "fireworks/qwen3-embedding-8b"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_candidate_model: str = "llama3.1:8b"
    ollama_compliance_model: str = "llama3.1:8b"
    compliance_retrieval_limit: int = 10
    compliance_evidence_limit: int = 4
    compliance_vector_threshold: float = 0.52
    compliance_lexical_threshold: float = 0.16
    mcp_server_url: str = "http://127.0.0.1:8001/mcp"
    database_path: str = "data/gridspec.db"
    upload_dir: str = "data/uploads"
    qdrant_path: str = "data/qdrant"
    mcp_port: int = 8001
    api_port: int = 8000
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def ensure_directories(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.upload_dir).mkdir(parents=True, exist_ok=True)
        Path(self.qdrant_path).mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
