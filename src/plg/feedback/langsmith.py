"""The LangSmith side of feedback: `create_feedback(run_id, ...)`, and thumbs-down runs into an annotation queue.

Best-effort: without LANGSMITH_API_KEY (or when LangSmith fails) the feedback is still recorded locally; the receipt
says it wasn't forwarded. Text is PII-masked before it leaves.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from plg.feedback.model import Score
from plg.memory.store import mask

log = logging.getLogger(__name__)

KEY = "user_score"


class LangSmithFeedback:
    def __init__(self, client: Any | None, queue_name: str) -> None:
        """`client`: a `langsmith.Client` (or a stand-in); None opens one on first use if an API key is set."""
        self._client = client
        self._queue_name = queue_name
        self._queue_id: str | None = None
        self._lock = threading.Lock()

    def _open(self) -> Any | None:
        if self._client is None and os.environ.get("LANGSMITH_API_KEY"):
            from langsmith import Client

            self._client = Client()
        return self._client

    def send(self, run_id: str, score: Score, comment: str, correction: str) -> bool:
        client = self._open()
        if client is None:
            return False
        extra: dict[str, Any] = {"correction": {"answer": mask(correction)}} if correction.strip() else {}
        try:
            client.create_feedback(
                run_id, KEY, score=1 if score == "up" else 0, comment=mask(comment) if comment.strip() else None, **extra,
            )
        except Exception:
            log.exception("LangSmith feedback for run %s failed", run_id)
            return False
        return True

    def queue(self, run_id: str) -> bool:
        """Put a thumbs-down run in the review queue (created on first use)."""
        client = self._open()
        if client is None:
            return False
        try:
            client.add_runs_to_annotation_queue(self._queue(client), run_ids=[run_id])
        except Exception:
            log.exception("Queueing run %s for review failed", run_id)
            return False
        return True

    def _queue(self, client: Any) -> str:
        with self._lock:
            if self._queue_id is None:
                found = next(iter(client.list_annotation_queues(name=self._queue_name)), None)
                queue = found or client.create_annotation_queue(
                    name=self._queue_name, description="Answers PLG officers gave a thumbs-down, for review."
                )
                self._queue_id = str(queue.id)
            return self._queue_id
