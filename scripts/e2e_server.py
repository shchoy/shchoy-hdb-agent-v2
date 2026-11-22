"""plg-api for the browser end-to-end tests (web/e2e, Playwright): the real API and graph, with a scripted LLMClient.

    uv run python scripts/e2e_server.py [--port 8100]

The poc-data corpus is synced into a temporary index (offline hashing embeddings, real local cross-encoder) and every
store the API writes (threads, memory, graph, outbox, i-EMS, audit log, ...) lives in scratch space, deleted on exit:
the real .plg/ stores are never touched and no API key is needed. Claude's replies are scripted per question (below);
each script replays for every run of its question, so a test can be retried against the same server.
"""

from __future__ import annotations

import argparse
import copy
import tempfile
from pathlib import Path
from typing import Any

import uvicorn
from record_sse_fixtures import (
    INBOX_QUESTION,
    QUESTION,
    REMINDER_QUESTION,
    RecordingLangSmith,
    cite,
    injection_email,
    routed,
    scratch_memory,
    scratch_settings,
    searcher,
)

from plg.api.app import create_app
from plg.llm import AgentMessage, AgentTurn, Block, ScriptedLLMClient, Tier, _latest_question, text, tool_call, turn

FOLLOW_UP = "And how long does the tenant have to pay after that?"
REMINDER_GOLDEN_LEAF = REMINDER_QUESTION
REMINDER_HOMETOWN = "Draft a first reminder letter for Hometown Minimart Pte Ltd's overdue rent"


class ReplayingLLMClient(ScriptedLLMClient):
    """A ScriptedLLMClient whose scripted turns start over with each run, so a question can be asked again (even after
    a run that was cut off part-way through its script)."""

    def __init__(self) -> None:
        super().__init__()
        self.originals: dict[tuple[str, str], list[Any]] = {}

    def script_turns(self, node: str, user_input: str, *turns: Any) -> None:
        super().script_turns(node, user_input, *turns)
        self.originals[(node, user_input)] = list(turns)

    async def complete(
        self, *, node: str, tier: Tier, system: list[Block], messages: list[AgentMessage], tools: list[Block],
        tool_choice: Block | None = None, max_tokens: int | None = None,
    ) -> AgentTurn:
        key = (node, _latest_question(messages))
        if key in self.originals and not _has_tool_results(messages):  # the node's first call in this run
            self.turns[key] = copy.copy(self.originals[key])
        # Only the browser's runs are kept: a long-lived server must not grow without bound.
        self.sent.clear()
        self.requests.clear()
        self.tool_choices.clear()
        self.streamed.clear()
        return await super().complete(
            node=node, tier=tier, system=system, messages=messages, tools=tools, tool_choice=tool_choice,
            max_tokens=max_tokens,
        )


def _has_tool_results(messages: list[AgentMessage]) -> bool:
    return any(
        not isinstance(m["content"], str) and any(b.get("type") == "tool_result" for b in m["content"])
        for m in messages if m["role"] == "user"
    )


def reminder(llm: ScriptedLLMClient, question: str, slots: dict[str, str]) -> None:
    """A complete arrears reminder (TPL-REM-01; it warns of a Letter of Demand): approvable as proposed."""
    llm.script_turns("route", question, routed("drafting"))
    llm.script_turns(
        "drafting", question,
        turn(tool_call("submit_draft", template_id="TPL-REM-01", slots={
            "letter_date": "30 September 2026", "notice_level": "FIRST", "pay_by_date": "14 October 2026",
            "officer_name": "Siti Aishah Yusof", "officer_phone": "+65 6100 2058", **slots,
        })),
        turn(text("Drafted the reminder.")),
    )
    llm.script("merge", question, f"I drafted the reminder to {slots['tenant_name']} from TPL-REM-01. It waits for your approval.")


def e2e_llm() -> ReplayingLLMClient:
    llm = ReplayingLLMClient()
    # Ask with citations, then a follow-up in the same thread.
    llm.script_turns("route", QUESTION, routed("knowledge"))
    llm.script_turns(
        "knowledge", QUESTION,
        turn(tool_call("search_corpus", query="letter of demand arrears")),
        cite("60 days", "A letter of demand is issued once arrears reach 60 days."),
    )
    llm.script("merge", QUESTION, "Under **POL-003 v2.0**, a letter of demand is issued once arrears reach 60 days [1].")
    llm.script_turns("route", FOLLOW_UP, routed("knowledge"))
    llm.script_turns(
        "knowledge", FOLLOW_UP,
        turn(tool_call("search_corpus", query="letter of demand payment deadline")),
        cite("60 days", "The letter of demand follows 60 days of arrears."),
    )
    llm.script("merge", FOLLOW_UP, "The letter of demand follows 60 days of arrears [1]; the policy sets the deadline in the letter.")
    # Two arrears letters to approve and reject.
    reminder(llm, REMINDER_GOLDEN_LEAF, {
        "letter_ref": "PLG/REM/2026/001", "tenant_name": "Golden Leaf Minimart Pte Ltd",
        "tenant_address": "#01-32, Blk 214 Bayshore Vale Drive, Singapore 460214",
        "unit_address": "Blk 214 Bayshore Vale Drive #01-32", "tenancy_id": "TA-2024-00542",
        "invoice_table": "INV-1 | 2026-08 | due 2026-08-01 | S$3,924.00", "total_due": "S$3,924.00",
    })
    reminder(llm, REMINDER_HOMETOWN, {
        "letter_ref": "PLG/REM/2026/002", "tenant_name": "Hometown Minimart Pte Ltd",
        "tenant_address": "#01-05, Blk 229 Bayshore Vale Drive, Singapore 460229",
        "unit_address": "Blk 229 Bayshore Vale Drive #01-05", "tenancy_id": "TA-2023-00005",
        "invoice_table": "INV-1 | 2026-08 | due 2026-08-01 | S$3,290.00", "total_due": "S$3,290.00",
    })
    # The planted refund email, read by the knowledge agent and flagged.
    injection_email(llm)
    return llm


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="plg-e2e-") as scratch:
        root = Path(scratch)
        print("Syncing the poc-data corpus into a temporary index...", flush=True)
        search, store = searcher(root / "index")
        app = create_app(
            scratch_settings(root), llm=e2e_llm(), searcher=search, store=store,
            memory=scratch_memory(root / "memory"), langsmith=RecordingLangSmith(),
        )
        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
