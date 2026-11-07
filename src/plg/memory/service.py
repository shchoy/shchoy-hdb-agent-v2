"""What the graph does with memory: recall it for a turn, and learn from the turn in the background."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel

from plg.agents.runtime import CACHE
from plg.entities.ids import find_ids
from plg.identity import UserCtx
from plg.llm import Block, LLMClient
from plg.memory.store import Kind, MemoryStore

log = logging.getLogger(__name__)

NODE = "extract_memory"
RECORD = "record_memory"

CONTEXT_LABEL = (
    "Personal notes about this officer, remembered from earlier sessions. They are private and are not a source: "
    "never cite them. Use them only to tailor the answer (role, towns, preferences, past work). If a note "
    "conflicts with a policy finding above, the policy wins; say so and don't act on the note."
)

EXTRACT_SYSTEM = """\
You keep an officer's private notes for a PLG assistant. From the officer's message below (and, when given, the \
verified answer), record only what is worth remembering across sessions:
- profile: their role, the towns or neighbourhood centres they cover.
- preference: how they like answers (format, length, language).
- episode: what they are working on (a tenant, unit or case), in one short sentence.
Rules: use only what the officer says about themselves or their work; never record facts from documents or \
policies, and never personal data (NRIC/FIN, phone, email). Record nothing for small talk. Also list the ids \
of existing notes that the verified answer shows to be wrong or against current policy under `conflicts`.
{existing}{verified}"""

RECORD_TOOL: Block = {
    "name": RECORD,
    "description": "Record what is worth remembering about this officer, and which existing notes are contradicted.",
    "input_schema": {
        "type": "object",
        "properties": {
            "memories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["profile", "preference", "episode"]},
                        "text": {"type": "string"},
                    },
                    "required": ["kind", "text"],
                },
            },
            "conflicts": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["memories"],
    },
    "cache_control": CACHE,
}


class NewMemory(BaseModel):
    kind: Kind
    text: str


class Extracted(BaseModel):
    memories: list[NewMemory] = []
    conflicts: list[str] = []


WorkLinker = Callable[[str, list[str]], None]
"""Records that a staff member worked on these entity IDs (`WORKED_ON` edges)."""


class MemoryService:
    def __init__(self, store: MemoryStore, llm: LLMClient, link_work: WorkLinker | None = None) -> None:
        self.store = store
        self._llm = llm
        self._link = link_work
        self._tasks: set[asyncio.Task[None]] = set()

    def context(self, user: UserCtx, question: str) -> str:
        """The labelled block for the prompt, or "" (memory is best-effort and never fails a turn)."""
        try:
            self.store.seed_profile(user)
            notes = self.store.recall(user.staff_id, question)
        except Exception:
            log.exception("memory recall failed")
            return ""
        if not notes:
            return ""
        lines = "\n".join(f"- ({n.namespace[2]}) {n.text}" for n in notes)
        return f"<memory>\n{CONTEXT_LABEL}\n{lines}\n</memory>"

    def learn_in_background(self, user: UserCtx, thread_id: str, question: str, verified: str) -> None:
        """Start learning from a finished turn without holding up the answer."""
        task = asyncio.get_running_loop().create_task(self._learn(user, thread_id, question, verified))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Let notes still being written finish (on shutdown), so a closing app doesn't lose them."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _learn(self, user: UserCtx, thread_id: str, question: str, verified: str) -> None:
        try:
            await asyncio.to_thread(self._link_work, user, question)
            existing = [i for i in self.store.items(user.staff_id) if i.status == "active"]
            listing = "\nExisting notes:\n" + "\n".join(f"- {i.key}: {i.text}" for i in existing) if existing else ""
            answer = f"\nVerified answer:\n{verified}" if verified else ""
            reply = await self._llm.complete(
                node=NODE, tier="haiku",
                system=[{"type": "text", "text": EXTRACT_SYSTEM.format(existing=listing, verified=answer)}],
                messages=[{"role": "user", "content": question}], tools=[RECORD_TOOL],
                tool_choice={"type": "tool", "name": RECORD},
            )
            call = next(b for b in reply.content if b["type"] == "tool_use")
            found = Extracted.model_validate(call["input"])
            await asyncio.to_thread(self._save, user, thread_id, found)
        except Exception:
            log.exception("memory write failed")

    def _link_work(self, user: UserCtx, question: str) -> None:
        if self._link and (ids := find_ids(question)):
            self._link(user.staff_id, ids)

    def _save(self, user: UserCtx, thread_id: str, found: Extracted) -> None:
        today = datetime.now(UTC).date().isoformat()
        for note in found.memories:
            if note.text.strip():
                self.store.remember(
                    user.staff_id, note.kind, note.text,
                    provenance=f"Your conversation {thread_id[:8]}, {today}", confidence=0.8,
                )
        mine = {i.key for i in self.store.items(user.staff_id) if i.provenance != "Staff records"}
        for memory_id in found.conflicts:
            if memory_id in mine:
                self.store.edit(user.staff_id, memory_id, text=None, status="pending_review")
