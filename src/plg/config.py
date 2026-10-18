"""Model IDs, paths and thresholds. Every value can be overridden with a `PLG_*` env var."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

Tier = Literal["haiku", "sonnet", "opus"]

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseModel):
    # Haiku: screening, routing, classification, summaries. Sonnet: agents, merge. Opus: hard analysis, judges.
    model_haiku: str = "claude-haiku-5-5"
    model_sonnet: str = "claude-sonnet-5-5"
    model_opus: str = "claude-opus-5-5"
    max_tokens: int = 2048
    # Seconds between SSE heartbeat comments, so proxies don't cut long runs.
    heartbeat_seconds: float = 15.0
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    # PLG Records (SQLite). Read-only; the source of staff personas for mock sign-in.
    records_db: Path = REPO_ROOT / "poc-data" / "plg_records.db"
    # The corpus `plg sync` reads through the SharePoint and Lotus Notes mocks.
    corpus_dir: Path = REPO_ROOT / "poc-data"
    # SearchStore (LanceDB) directory: chunks, entities and memory tables.
    search_db: Path = REPO_ROOT / ".plg" / "lancedb"
    embed_model: str = "voyage-3.5"
    embed_dim: int = 1024
    voyage_base_url: str = "https://api.voyageai.com/v1"
    # Final rerank: Voyage's hosted reranker, or a local cross-encoder (below).
    rerank_backend: Literal["voyage", "local"] = "voyage"
    voyage_rerank_model: str = "rerank-2.5"
    # Local cross-encoder for the final rerank, cached under model_cache after the first download.
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    model_cache: Path = REPO_ROOT / ".plg" / "models"
    # Hybrid candidates passed to the cross-encoder, and the weight of the vector score in the hybrid mix.
    search_candidates: int = 50
    vector_weight: float = 0.7

    def model_for(self, tier: Tier) -> str:
        return {"haiku": self.model_haiku, "sonnet": self.model_sonnet, "opus": self.model_opus}[tier]

    @classmethod
    def from_env(cls) -> Settings:
        overrides = {
            name: os.environ[f"PLG_{name.upper()}"]
            for name in cls.model_fields
            if f"PLG_{name.upper()}" in os.environ
        }
        return cls.model_validate(overrides)
