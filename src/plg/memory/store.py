"""`MemoryStore`: an officer's private long-term memory, a LangGraph `BaseStore` over the `memory` table.

Namespace is `("memory", staff_id, kind)`; every read is scoped to a staff ID, so one officer never sees
another's items. Values carry `text` (embedded for recall) plus optional `provenance`, `confidence`, `status`.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from langgraph.store.base import (
    BaseStore, GetOp, Item, ListNamespacesOp, Op, PutOp, Result, SearchItem, SearchOp,
)
from pydantic import BaseModel

from plg.drafting.pii import EMAIL, NRIC, PHONE
from plg.identity import UserCtx
from plg.search.embed import Embedder
from plg.search.models import MemoryItem, MemoryStatus
from plg.search.store import SearchStore

ROOT = "memory"
Kind = Literal["profile", "preference", "episode"]
KINDS: tuple[Kind, ...] = ("profile", "preference", "episode")
EPISODE_DAYS = 180
SAME = 0.9
"""Cosine similarity from which two memories of one officer count as the same thing."""



def mask(text: str) -> str:
    """Personal data never enters memory: identity numbers, emails and phone numbers are masked."""
    text = NRIC.sub("[NRIC]", text)
    text = EMAIL.sub("[email]", text)
    return PHONE.sub("[phone]", text)


class FlaggedByPolicy(ValueError):
    """A note that conflicts with current policy loses: it can be reworded or forgotten, not switched back on."""

    def __init__(self) -> None:
        super().__init__("This note conflicts with current policy, so it can't be used as it is. Edit or forget it.")


class MemoryView(BaseModel):
    """One memory as the officer sees it."""

    id: str
    kind: Kind
    text: str
    status: MemoryStatus
    provenance: str
    confidence: float
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None


def namespace(staff_id: str, kind: Kind) -> tuple[str, ...]:
    return (ROOT, staff_id, kind)


def cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0


def key_for(kind: Kind, text: str) -> str:
    return f"{kind}-{hashlib.sha1(' '.join(text.lower().split()).encode()).hexdigest()[:10]}"


def view(item: MemoryItem) -> MemoryView:
    return MemoryView(
        id=item.key, kind=item.namespace[2],  # type: ignore[arg-type]
        text=item.text, status=item.status, provenance=item.provenance, confidence=item.confidence,
        created_at=item.created_at, updated_at=item.updated_at, expires_at=item.expires_at,
    )


class MemoryStore(BaseStore):
    def __init__(self, index: SearchStore | Any, embedder: Embedder) -> None:
        """`index` may be a callable returning the SearchStore, so it opens on first use."""
        self._index = index
        self._embedder = embedder

    @property
    def index(self) -> SearchStore:
        if callable(self._index):
            self._index = self._index()
        return self._index

    # ------------------------------------------------------------------ typed access for the app
    def remember(
        self, staff_id: str, kind: Kind, text: str, *, provenance: str, confidence: float = 1.0,
        key: str | None = None, now: datetime | None = None,
    ) -> MemoryView:
        """Store a memory (PII masked). A near-duplicate of one the officer already has is merged into it."""
        now = now or datetime.now(UTC)
        text = mask(text.strip())
        vector = self._embedder.embed_query(text)
        for other in self.index.list_memory((ROOT, staff_id, kind), now=now):
            if other.key in (key, key_for(kind, text)) or cosine(vector, other.vector) >= SAME:
                if other.status == "retired":
                    return view(other)  # the officer stopped using this note; learning it again doesn't revive it
                merged = other.model_copy(update={
                    "updated_at": now, "confidence": max(other.confidence, confidence),
                    "expires_at": _expiry(kind, now),
                })
                self.index.put_memory(merged)
                return view(merged)
        item = MemoryItem(
            namespace=namespace(staff_id, kind), key=key or key_for(kind, text), value={"text": text}, text=text,
            vector=vector, provenance=provenance, confidence=confidence, created_at=now, updated_at=now,
            expires_at=_expiry(kind, now),
        )
        self.index.put_memory(item)
        return view(item)

    def items(self, staff_id: str, *, now: datetime | None = None) -> list[MemoryItem]:
        return self.index.list_memory((ROOT, staff_id), now=now or datetime.now(UTC))

    def find(self, staff_id: str, memory_id: str) -> MemoryItem | None:
        return next((i for i in self.items(staff_id) if i.key == memory_id), None)

    def edit(self, staff_id: str, memory_id: str, *, text: str | None, status: MemoryStatus | None) -> MemoryItem | None:
        """Reword and/or change status. Rewording a flagged note clears the flag (later turns check it again);
        switching a flagged note back on without rewording raises `FlaggedByPolicy`."""
        item = self.find(staff_id, memory_id)
        if item is None:
            return None
        if item.status == "pending_review" and status == "active" and text is None:
            raise FlaggedByPolicy()
        update: dict[str, Any] = {"updated_at": datetime.now(UTC)}
        if text is not None:
            text = mask(text.strip())
            update |= {"text": text, "value": {**item.value, "text": text}, "vector": self._embedder.embed_query(text),
                       "provenance": "edited by you", "confidence": 1.0}
            if item.status == "pending_review":
                update["status"] = "active"
        if status is not None:
            update["status"] = status
        edited = item.model_copy(update=update)
        self.index.put_memory(edited)
        return edited

    def forget(self, staff_id: str, memory_id: str) -> bool:
        item = self.find(staff_id, memory_id)
        if item is None:
            return False
        self.index.delete_memory(item.namespace, item.key)
        return True

    def seed_profile(self, user: UserCtx) -> None:
        """The officer's profile from the `staff` table, written once."""
        if self.index.get_memory(namespace(user.staff_id, "profile"), "profile-staff") is not None:
            return
        now = datetime.now(UTC)
        text = f"{user.name} is a {user.title} in {user.dept} (role: {user.role.replace('_', ' ')})."
        self.index.put_memory(MemoryItem(
            namespace=namespace(user.staff_id, "profile"), key="profile-staff", value={"text": text}, text=text,
            vector=self._embedder.embed_query(text), provenance="Staff records", created_at=now, updated_at=now,
        ))

    def recall(self, staff_id: str, question: str, *, limit: int = 5) -> list[MemoryItem]:
        """Active profile and preferences, plus the episodes nearest the question."""
        now = datetime.now(UTC)
        standing = [i for i in self.items(staff_id, now=now) if i.status == "active" and i.namespace[2] != "episode"]
        episodes = self.index.search_memory(
            namespace(staff_id, "episode"), self._embedder.embed_query(question), now=now, limit=limit
        )
        return [*standing, *episodes]

    # ------------------------------------------------------------------ BaseStore
    def batch(self, ops: Iterable[Op]) -> list[Result]:
        return [self._apply(op) for op in ops]

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        return await asyncio.to_thread(self.batch, list(ops))

    def _apply(self, op: Op) -> Result:
        now = datetime.now(UTC)
        if isinstance(op, GetOp):
            found = self.index.get_memory(op.namespace, op.key)
            return _as_item(found) if found and (found.expires_at is None or found.expires_at > now) else None
        if isinstance(op, SearchOp):
            query = self._embedder.embed_query(op.query) if op.query else [0.0] * self._embedder.dim
            hits = self.index.search_memory(op.namespace_prefix, query, now=now, limit=op.limit + op.offset)
            return [_as_search_item(h) for h in hits[op.offset:]]
        if isinstance(op, PutOp):
            if op.value is None:
                self.index.delete_memory(op.namespace, op.key)
                return None
            text = str(op.value.get("text", ""))
            expires = now + timedelta(minutes=op.ttl) if op.ttl else None
            earlier = self.index.get_memory(op.namespace, op.key)
            self.index.put_memory(MemoryItem(
                namespace=op.namespace, key=op.key, value=dict(op.value), text=text, vector=self._embedder.embed_query(text),
                status=op.value.get("status", "active"), provenance=op.value.get("provenance", "store"),
                confidence=op.value.get("confidence", 1.0), created_at=earlier.created_at if earlier else now, updated_at=now,
                expires_at=expires,
            ))
            return None
        if isinstance(op, ListNamespacesOp):
            return []
        raise TypeError(f"Unsupported store operation {op!r}")


def _expiry(kind: Kind, now: datetime) -> datetime | None:
    return now + timedelta(days=EPISODE_DAYS) if kind == "episode" else None


def _as_item(m: MemoryItem) -> Item:
    return Item(value=m.value, key=m.key, namespace=m.namespace, created_at=m.created_at, updated_at=m.updated_at)


def _as_search_item(m: MemoryItem) -> SearchItem:
    return SearchItem(
        namespace=m.namespace, key=m.key, value=m.value, created_at=m.created_at, updated_at=m.updated_at, score=None
    )
