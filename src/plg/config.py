"""Model IDs, paths and thresholds. Every value can be overridden with a `PLG_*` env var."""

from __future__ import annotations

import datetime as dt
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
    # The corpus's Excel trackers, cleaned into DuckDB tables by `plg sync`; the data agent reads them as trackers.<table>.
    trackers_db: Path = REPO_ROOT / ".plg" / "trackers.duckdb"
    # SearchStore (LanceDB) directory: chunks, entities and memory tables.
    search_db: Path = REPO_ROOT / ".plg" / "lancedb"
    # Entity graph: spine CSVs (Neptune openCypher bulk-load format) and delta CSVs written by GraphWriter.
    graph_dir: Path = REPO_ROOT / ".plg" / "graph"
    # Conversations: LangGraph checkpoints and thread ownership (SQLite).
    threads_db: Path = REPO_ROOT / ".plg" / "threads.sqlite"
    # Approved actions: the local Outbox adapter (one JSON file per letter) and the append-only audit log.
    outbox_dir: Path = REPO_ROOT / ".plg" / "outbox"
    audit_log: Path = REPO_ROOT / ".plg" / "audit.jsonl"
    iems_dir: Path = REPO_ROOT / ".plg" / "iems"
    """The i-EMS mock: raised tickets, one JSON file each."""
    glossary_changes: Path = REPO_ROOT / ".plg" / "glossary_changes.jsonl"
    """Approved glossary changes (append-only), layered over the generated glossary and semantic layer."""
    tasks_today: dt.date = dt.date(2026, 9, 30)
    """The day tasks are ranked on (overdue, due this week): PLG Records is a snapshot taken on 30 Sep 2026."""
    # Above this many (estimated) tokens of history, older turns are folded into a summary, keeping the last
    # `history_keep_messages` messages verbatim.
    history_token_threshold: int = 6000
    history_keep_messages: int = 4
    # `route` asks a clarifying question instead of fanning out when it is less sure than this (0-1) that a
    # question needs one of the specialists it named.
    route_min_confidence: float = 0.6
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

    @property
    def submissions_dir(self) -> Path:
        """Application submission bundles, one folder of PDFs per application ID (the document check reads them)."""
        return self.corpus_dir / "pdfs" / "submissions"

    @property
    def transcripts_dir(self) -> Path:
        """Saved transcripts of scanned PDFs, beside the index (`plg sync --full` keeps them)."""
        return self.search_db.with_name(f"{self.search_db.name}-transcripts")

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
