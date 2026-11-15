"""Answer feedback (issue #26): what an officer said about one answer, and the answer it was about."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

Score = Literal["up", "down"]


class AnsweredTurn(BaseModel):
    """One answered turn of a thread, kept in graph state so feedback can name it by its run ID."""

    run_id: str
    """The LangSmith run ID of the run that answered it."""
    message_index: int
    """The answer's index in the thread's `messages`."""
    question: str
    intents: list[str]
    answer: str
    sql: str | None = None
    """The last query that ran for it (the data specialist's), if any."""
    flagged: bool = False
    """The turn met a prompt injection: feedback on it is recorded but teaches the team nothing."""


class Feedback(BaseModel):
    """One officer's 👍/👎 on one answer, as recorded (append-only)."""

    feedback_id: str
    thread_id: str
    run_id: str
    staff_id: str
    score: Score
    comment: str
    correction: str
    team_fact: str
    at: str
    forwarded: bool
    """Sent to LangSmith (`create_feedback`)."""
    queued: bool
    """Added to the thumbs-down annotation queue."""
    proposals: list[str]
    """Action IDs of what it proposed to the curators."""


class FeedbackLog:
    """JSON lines, only ever appended to."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def record(self, feedback: Feedback) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as log:
                log.write(feedback.model_dump_json() + "\n")

    def entries(self) -> list[Feedback]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [Feedback.model_validate_json(line) for line in lines if line.strip()]
