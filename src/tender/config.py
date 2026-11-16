from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TENDER_", env_file=".env", extra="ignore")
    mode: Literal["demo", "production"] = "demo"
    database_url: str = "sqlite:///var/tender.db"
    data_dir: Path = Path("var")
    database_dir: Path = Path("database")
    drafts_dir: Path = Path("drafts")
    outputs_dir: Path = Path("outputs")
    database_tenant: str = "demo"
    seed_demo: bool = True
    api_keys: dict[str, dict[str, str]] = {}
    model_provider: Literal["offline", "anthropic", "nvidia"] = "offline"
    model_name: str = ""
    model_api_key: str = ""
    model_base_url: str = "https://api.anthropic.com"
    embedding_url: str = ""
    embedding_key: str = ""
    nvidia_api_key: str = ""
    nvidia_base_url: str = ""
    nvidia_chat_model: str = ""
    nvidia_embedding_model: str = ""
    nvidia_rerank_model: str = ""
    rag_enabled: bool = False
    tracing_enabled: bool = False
    tracing_host: str = ""
    tracing_public_key: str = ""
    tracing_secret_key: str = ""
    tracing_redact_text: bool = False
    web_enabled: bool = False
    web_search_key: str = ""
    web_allowed_hosts: list[str] = ["cpwd.gov.in", "doe.gov.in", "indianrailways.gov.in"]
    object_backend: Literal["local", "s3"] = "local"
    s3_bucket: str = ""
    s3_endpoint_url: str | None = None
    max_upload_bytes: int = 15_000_000
    max_research_documents: int = 3
    lease_seconds: int = 1800

    @model_validator(mode="after")
    def valid_deployment(self):
        if self.mode == "production":
            if not self.api_keys:
                raise ValueError("Production requires TENDER_API_KEYS with tenant, user and role mappings")
            if self.seed_demo:
                raise ValueError("Disable TENDER_SEED_DEMO for production")
        for value in self.api_keys.values():
            if (
                not value.get("tenant")
                or not value.get("user")
                or value.get("role") not in {"viewer", "engineer", "reviewer", "admin"}
            ):
                raise ValueError("API key identities require tenant, user and a supported role")
        if self.model_provider == "anthropic" and not (self.model_api_key and self.model_name):
            raise ValueError("Live models require an API key and an explicitly selected model")
        if self.model_provider == "nvidia" and not (self.nvidia_api_key and self.nvidia_chat_model):
            raise ValueError("NVIDIA chat requires TENDER_NVIDIA_API_KEY and TENDER_NVIDIA_CHAT_MODEL")
        if self.object_backend == "s3" and not self.s3_bucket:
            raise ValueError("S3 storage requires a bucket")
        return self
