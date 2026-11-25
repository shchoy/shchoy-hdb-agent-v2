"""Conversations: who owns which thread, and runs that outlive their HTTP connection.

The conversation itself lives in the LangGraph checkpoint (same SQLite file); this module holds only what the
checkpoint doesn't: thread ownership, title and group (the officer's own groups too), and the events of the latest run per thread, so a browser that
dropped or refreshed can pick the answer up again from the last event sequence number it saw.
"""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from plg.actions.model import ApprovalDecision
from plg.events import CancelledEvent, DoneEvent, ErrorEvent, NodeEvent, RunEvent
from plg.graph.state import PLGGraph
from plg.identity import UserCtx
from plg.runs import stream_run
from plg.tracing import Tracer


class ThreadSummary(BaseModel):
    thread_id: str
    title: str
    updated_at: str
    group_id: str | None = None
    """The officer's group it is in (#100); None: under Recent."""


class Group(BaseModel):
    """One of an officer's own, flat conversation groups (#100)."""

    group_id: str
    name: str


class GroupNotFound(Exception):
    """No such group, or someone else's."""


class ThreadStore:
    """Thread ownership in SQLite. A thread is listed once it has been asked something."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS plg_threads (thread_id TEXT PRIMARY KEY, staff_id TEXT NOT NULL, "
                "title TEXT, updated_at TEXT NOT NULL)"
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(plg_threads)")}
            if "group_id" not in columns:  # a threads.sqlite from before #100
                db.execute("ALTER TABLE plg_threads ADD COLUMN group_id TEXT")
            db.execute(
                "CREATE TABLE IF NOT EXISTS plg_groups (group_id TEXT PRIMARY KEY, staff_id TEXT NOT NULL, "
                "name TEXT NOT NULL, created_at TEXT NOT NULL)"
            )

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=30)) as db, db:
            yield db

    def create(self, staff_id: str) -> str:
        thread_id = str(uuid.uuid4())
        with self._db() as db:
            db.execute(
                "INSERT INTO plg_threads (thread_id, staff_id, title, updated_at) VALUES (?, ?, NULL, ?)",
                (thread_id, staff_id, _now()),
            )
        return thread_id

    def owns(self, thread_id: str, staff_id: str) -> bool:
        with self._db() as db:
            row = db.execute("SELECT 1 FROM plg_threads WHERE thread_id = ? AND staff_id = ?", (thread_id, staff_id)).fetchone()
        return row is not None

    def asked(self, thread_id: str, question: str) -> None:
        title = " ".join(question.split())[:80]
        with self._db() as db:
            db.execute(
                "UPDATE plg_threads SET title = COALESCE(title, ?), updated_at = ? WHERE thread_id = ?",
                (title, _now(), thread_id),
            )

    def rename(self, thread_id: str, title: str) -> ThreadSummary:
        """The officer's own title: later questions keep it (`asked` only fills a missing title)."""
        with self._db() as db:
            db.execute("UPDATE plg_threads SET title = ? WHERE thread_id = ?", (title, thread_id))
        return self._summary(thread_id)

    def move(self, thread_id: str, staff_id: str, group_id: str | None) -> ThreadSummary:
        """Put the officer's thread in one of their groups (None: back to Recent). Raises GroupNotFound."""
        with self._db() as db:
            # One statement, so a group deleted meanwhile can't be left as a dangling group_id.
            moved = db.execute(
                "UPDATE plg_threads SET group_id = ? WHERE thread_id = ? AND (? IS NULL OR EXISTS "
                "(SELECT 1 FROM plg_groups WHERE group_id = ? AND staff_id = ?))",
                (group_id, thread_id, group_id, group_id, staff_id),
            ).rowcount
        if not moved:
            raise GroupNotFound
        return self._summary(thread_id)

    def _summary(self, thread_id: str) -> ThreadSummary:
        with self._db() as db:
            row = db.execute(
                "SELECT thread_id, COALESCE(title, ''), updated_at, group_id FROM plg_threads WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        return ThreadSummary(thread_id=row[0], title=row[1], updated_at=row[2], group_id=row[3])

    def groups(self, staff_id: str) -> list[Group]:
        """The officer's groups, in the order they were created."""
        with self._db() as db:
            rows = db.execute(
                "SELECT group_id, name FROM plg_groups WHERE staff_id = ? ORDER BY created_at, rowid", (staff_id,)
            ).fetchall()
        return [Group(group_id=r[0], name=r[1]) for r in rows]

    def create_group(self, staff_id: str, name: str) -> Group:
        group = Group(group_id=str(uuid.uuid4()), name=name)
        with self._db() as db:
            db.execute("INSERT INTO plg_groups VALUES (?, ?, ?, ?)", (group.group_id, staff_id, name, _now()))
        return group

    def rename_group(self, group_id: str, staff_id: str, name: str) -> Group:
        """Raises GroupNotFound."""
        with self._db() as db:
            if not _owns_group(db, group_id, staff_id):
                raise GroupNotFound
            db.execute("UPDATE plg_groups SET name = ? WHERE group_id = ?", (name, group_id))
        return Group(group_id=group_id, name=name)

    def delete_group(self, group_id: str, staff_id: str) -> None:
        """Its conversations go back to Recent; none is deleted. Raises GroupNotFound."""
        with self._db() as db:
            if not _owns_group(db, group_id, staff_id):
                raise GroupNotFound
            db.execute("UPDATE plg_threads SET group_id = NULL WHERE group_id = ?", (group_id,))
            db.execute("DELETE FROM plg_groups WHERE group_id = ?", (group_id,))

    def delete(self, thread_id: str) -> None:
        """Forget the thread's owner and title: from now on it is not found, for everyone."""
        with self._db() as db:
            db.execute("DELETE FROM plg_threads WHERE thread_id = ?", (thread_id,))

    def all_asked(self) -> list[ThreadSummary]:
        """Every asked thread, whoever owns it: only for finding actions others decide on (glossary curators)."""
        with self._db() as db:
            rows = db.execute(
                "SELECT thread_id, title, updated_at FROM plg_threads WHERE title IS NOT NULL ORDER BY rowid"
            ).fetchall()
        return [ThreadSummary(thread_id=r[0], title=r[1], updated_at=r[2]) for r in rows]

    def list(self, staff_id: str) -> list[ThreadSummary]:
        with self._db() as db:
            rows = db.execute(
                "SELECT thread_id, title, updated_at, group_id FROM plg_threads WHERE staff_id = ? AND title IS NOT NULL "
                "ORDER BY updated_at DESC, rowid DESC",
                (staff_id,),
            ).fetchall()
        return [ThreadSummary(thread_id=r[0], title=r[1], updated_at=r[2], group_id=r[3]) for r in rows]


def _owns_group(db: sqlite3.Connection, group_id: str, staff_id: str) -> bool:
    return db.execute(
        "SELECT 1 FROM plg_groups WHERE group_id = ? AND staff_id = ?", (group_id, staff_id)
    ).fetchone() is not None


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RunBuffer:
    """Every event of one run, kept so that any number of clients can follow it, or join late."""

    def __init__(self, question: str) -> None:
        self.question = question
        self.events: list[RunEvent] = []
        self.finished = False
        self.answered = False
        """merge has finished: the turn (and anything it proposed) is checkpointed, so the run can't be undone."""
        self.task: asyncio.Task[None] | None = None
        """The background task producing the events."""
        self._changed = asyncio.Condition()

    @property
    def stoppable(self) -> bool:
        """A question still being answered: stopping it now leaves no trace. A decision (empty question) never is: its
        side effect and audit entry must not be split."""
        return bool(self.question) and not self.answered and not self.finished

    async def add(self, event: RunEvent) -> None:
        async with self._changed:
            self.events.append(event)
            self.finished = isinstance(event, DoneEvent | ErrorEvent | CancelledEvent)
            if isinstance(event, NodeEvent) and event.node == "merge" and event.status == "finished":
                self.answered = True
            self._changed.notify_all()

    async def close(self) -> None:
        async with self._changed:
            self.finished = True
            self._changed.notify_all()

    async def follow(self, after: int = 0) -> AsyncIterator[RunEvent]:
        """Events with a sequence number above `after`, live until the run ends."""
        position = 0
        while True:
            async with self._changed:
                await self._changed.wait_for(lambda: position < len(self.events) or self.finished)
                batch = self.events[position:]
                position = len(self.events)
                finished = self.finished
            for event in batch:
                if event.seq > after:
                    yield event
            if finished and position >= len(self.events):
                return


class RunInProgress(Exception):
    """The thread is still answering its last question."""


class NothingToStop(Exception):
    """The thread has no run that can still be stopped: none running, already answered, or carrying out a decision."""


class RunRegistry:
    """The latest run of each thread. A run goes on when its client goes away."""

    def __init__(self, tracer: Tracer | None = None) -> None:
        """`tracer`: each run is traced to LangSmith through it (None: not traced)."""
        self._tracer = tracer
        self._runs: dict[str, RunBuffer] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def latest(self, thread_id: str) -> RunBuffer | None:
        return self._runs.get(thread_id)

    def running(self, thread_id: str) -> bool:
        current = self._runs.get(thread_id)
        return current is not None and not current.finished

    def forget(self, thread_id: str) -> None:
        """Drop a deleted thread's finished run, so its events can't be replayed."""
        self._runs.pop(thread_id, None)

    def start(
        self, graph: PLGGraph, thread_id: str, message: str, user: UserCtx, decision: ApprovalDecision | None = None
    ) -> RunBuffer:
        """Answer `message` (or carry out `decision`, with an empty `message`) in the background."""
        if self.running(thread_id):
            raise RunInProgress
        buffer = self._runs[thread_id] = RunBuffer(message)
        run_id = uuid.uuid4()

        async def pump() -> None:
            try:
                async for event in stream_run(
                    graph, thread_id, message, user, decision=decision, tracer=self._tracer, run_id=run_id
                ):
                    await buffer.add(event)
            except asyncio.CancelledError:
                # Stopped by the officer before merge answered (`cancel` checks), so the checkpoint holds no turn and
                # no proposal, as with a failed run. The stream ends saying so.
                seq = buffer.events[-1].seq + 1 if buffer.events else 1
                await buffer.add(CancelledEvent(seq=seq, run_id=str(run_id)))
            finally:
                await buffer.close()  # followers never hang, and the thread can be asked again

        task = buffer.task = asyncio.get_running_loop().create_task(pump())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return buffer

    async def cancel(self, thread_id: str) -> None:
        """Stop the thread's question still being answered, and wait until it has stopped, so the thread can be asked
        again at once. Raises NothingToStop otherwise (see RunBuffer.stoppable)."""
        buffer = self._runs.get(thread_id)
        if buffer is None or buffer.task is None or not buffer.stoppable:
            raise NothingToStop
        buffer.task.cancel()  # no await since the check: merge can't have finished in between
        await asyncio.wait({buffer.task})
