"""The LangSmith side of feedback: `create_feedback(run_id, ...)`, and thumbs-down runs into an annotation queue.

Best-effort: without LANGSMITH_API_KEY (or when LangSmith fails) the feedback is still recorded locally; the receipt
says it wasn't forwarded. Text is PII-masked before it leaves.

SmithDB (https://docs.langchain.com/langsmith/smithdb-sdk-migration-feedback): LangSmith finds a run by its ID plus
its project UUID and start time. A queue item needs all three, so only a traced run (one whose turn kept its
`started_at`) can join the queue; feedback carries them when known.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from datetime import datetime
from typing import Any

from plg.feedback.model import Score
from plg.memory.store import mask

log = logging.getLogger(__name__)

KEY = "user_score"


class LangSmithFeedback:
    def __init__(self, client: Any | None, queue_name: str, project: str | None = None) -> None:
        """`client`: a `langsmith.Client` (or a stand-in); None opens one on first use if an API key is set.
        `project`: the LangSmith project the runs are traced to (default LANGSMITH_PROJECT, else "default")."""
        self._client = client
        self._queue_name = queue_name
        self._project = project or os.environ.get("LANGSMITH_PROJECT") or "default"
        self._queue_id: str | None = None
        self._project_id: str | None = None
        self._lock = threading.Lock()

    def _open(self) -> Any | None:
        if self._client is None and os.environ.get("LANGSMITH_API_KEY"):
            from langsmith import Client

            self._client = Client()
        return self._client

    def send(self, run_id: str, score: Score, comment: str, correction: str, started_at: str | None = None) -> bool:
        client = self._open()
        if client is None:
            return False
        extra: dict[str, Any] = {"correction": {"answer": mask(correction)}} if correction.strip() else {}
        try:
            if started_at is not None:  # the run's lookup key, so LangSmith finds it without a scan
                extra |= {"session_id": self._project_of(client), "start_time": datetime.fromisoformat(started_at)}
            client.create_feedback(
                run_id, KEY, score=1 if score == "up" else 0, comment=mask(comment) if comment.strip() else None, **extra,
            )
        except Exception:
            log.exception("LangSmith feedback for run %s failed", run_id)
            return False
        return True

    async def queue(self, run_id: str, started_at: str | None) -> bool:
        """Put a thumbs-down run in the review queue (created on first use). A run that wasn't traced (no start
        time) can't be found by LangSmith, so it isn't queued."""
        client = self._open()
        if client is None:
            return False
        if started_at is None:
            log.info("Run %s was not traced: not queued for review", run_id)
            return False
        try:
            queue_id, project_id, items = await asyncio.to_thread(self._lookup, client)
            await items.create(
                queue_id,
                items=[{"item_type": "RUN", "run_id": run_id, "project_id": project_id, "start_time": started_at}],
            )
        except Exception:
            log.exception("Queueing run %s for review failed", run_id)
            return False
        return True

    def _lookup(self, client: Any) -> tuple[str, str, Any]:
        """The queue ID, the project UUID and the queue items resource (its first access checks the server version)."""
        return self._queue(client), self._project_of(client), client.annotation_queues.items

    def _project_of(self, client: Any) -> str:
        with self._lock:
            if self._project_id is None:
                self._project_id = str(client.read_project(project_name=self._project).id)
            return self._project_id

    def _queue(self, client: Any) -> str:
        with self._lock:
            if self._queue_id is None:
                found = next(iter(client.list_annotation_queues(name=self._queue_name)), None)
                queue = found or client.create_annotation_queue(
                    name=self._queue_name, description="Answers PLG officers gave a thumbs-down, for review."
                )
                self._queue_id = str(queue.id)
            return self._queue_id
