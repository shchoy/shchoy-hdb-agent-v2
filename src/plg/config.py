"""Model IDs, paths and thresholds. Every value can be overridden with a `PLG_*` env var."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel

Tier = Literal["haiku", "sonnet", "opus"]


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
