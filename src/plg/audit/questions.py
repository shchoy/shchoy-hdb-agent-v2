"""The question log: every answered question, how well the corpus matched it and whether it was covered. Written after
`merge` answers a turn (append-only JSONL, the question PII-masked); read by the audit to find gaps."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel


class QuestionEntry(BaseModel):
    at: datetime
    thread_id: str
    run_id: str
    staff_id: str | None
    question: str
    intents: list[str]
    top_score: float | None
    """The best retrieval score of the passages the knowledge specialist was shown (None if it didn't search)."""
    not_covered: bool
    """The answer was the fixed "not covered" answer: no finding had a source."""


class QuestionLog:
    """JSON lines, only ever appended to. `mask` scrubs PII from the question before it is written."""

    def __init__(self, path: Path, mask: Callable[[str], str] = lambda text: text) -> None:
        self.path = path
        self.mask = mask
        self._lock = threading.Lock()

    def record(self, entry: QuestionEntry) -> None:
        masked = entry.model_copy(update={"question": self.mask(entry.question)})
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as log:
                log.write(masked.model_dump_json() + "\n")

    def entries(self) -> list[QuestionEntry]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [QuestionEntry.model_validate_json(line) for line in lines if line.strip()]
