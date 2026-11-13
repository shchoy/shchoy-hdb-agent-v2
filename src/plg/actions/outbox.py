"""The `Outbox` adapter: where approved letters go. The POC writes them to local storage; nothing is delivered."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


class OutboxItem(BaseModel):
    item_id: str
    action_id: str
    version: int
    """The version sent: one above the approved version when the officer edited it."""
    template_id: str
    recipient: str
    title: str
    slots: dict[str, str]
    html: str
    approver: str
    sent_at: str


class Outbox(Protocol):
    def send(self, item: OutboxItem) -> None: ...

    def items(self) -> list[OutboxItem]: ...

    def item(self, item_id: str) -> OutboxItem | None: ...


class LocalOutbox:
    """One JSON file per item. Sending the same item again overwrites it, so a retried step can't send twice."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def send(self, item: OutboxItem) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        target = self.path / f"{item.item_id}.json"
        partial = target.with_suffix(".part")
        partial.write_text(item.model_dump_json(indent=2), encoding="utf-8")
        partial.replace(target)

    def item(self, item_id: str) -> OutboxItem | None:
        path = self.path / f"{item_id}.json"
        return OutboxItem.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None

    def items(self) -> list[OutboxItem]:
        if not self.path.exists():
            return []
        found = [OutboxItem.model_validate_json(p.read_text(encoding="utf-8")) for p in self.path.glob("*.json")]
        return sorted(found, key=lambda i: (i.sent_at, i.item_id))
