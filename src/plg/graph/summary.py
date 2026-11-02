"""Long conversations: fold older turns into a summary that keeps entity IDs verbatim."""

from __future__ import annotations

from plg.agents.runtime import CACHE
from plg.entities.ids import find_ids
from plg.llm import Block, LLMClient, Message

NODE = "summarise_history"

SYSTEM = """\
You condense the earlier part of a conversation between a PLG officer and an assistant, so it can continue \
without the full text. Keep what the officer asked, what was established, and any open thread. Copy every \
entity ID (units, tenancies, tenants, policies and the like) exactly as written. Do not add anything new. \
Reply with the summary only."""

SUMMARY_LEAD = "Summary of the earlier conversation (older turns, folded):\n"


def estimate_tokens(messages: list[Message], summary: str = "") -> int:
    return (len(summary) + sum(len(m["content"]) for m in messages)) // 4


def transcript(messages: list[Message]) -> str:
    return "\n\n".join(f"{'Officer' if m['role'] == 'user' else 'Assistant'}: {m['content']}" for m in messages)


def with_ids(summary: str, folded: list[Message], previous: str = "") -> str:
    """The summary, plus any entity ID in the folded text that it dropped."""
    seen = f"{summary}\n{previous}"
    missing = [i for i in dict.fromkeys(find_ids(transcript(folded))) if i not in seen]
    return summary if not missing else f"{summary}\nEntity IDs mentioned: {', '.join(missing)}"


async def fold(llm: LLMClient, folded: list[Message], previous: str) -> str:
    prompt = transcript(folded)
    if previous:
        prompt = f"Summary so far:\n{previous}\n\nNew turns to fold in:\n\n{prompt}"
    reply = await llm.complete(
        node=NODE, tier="haiku", system=[{"type": "text", "text": SYSTEM, "cache_control": CACHE}],
        messages=[{"role": "user", "content": prompt}], tools=[],
    )
    summary = "".join(b["text"] for b in reply.content if b["type"] == "text").strip()
    return with_ids(summary, folded, previous)
