"""Record SSE streams from an in-process plg-api for the web tests to replay (MSW).

    uv run python scripts/record_sse_fixtures.py

Writes `web/src/test/fixtures/*.sse`. Streams come from the real API and graph with a scripted
LLMClient, and the knowledge agent searches the poc-data corpus synced into a temporary index
(offline hashing embeddings, real cross-encoder), so they match what the BFF receives from `plg serve`.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from plg.api.app import create_app
from plg.config import REPO_ROOT, Settings
from plg.ingest.metadata import load_entity_spine
from plg.ingest.sources import LotusNotesSource, SharePointSource
from plg.ingest.sync import sync
from plg.llm import AgentMessage, AgentTurn, ScriptedLLMClient, text, tool_call, turn
from plg.search.embed import HashingEmbedder
from plg.search.lance import LanceSearchStore
from plg.search.rerank import CrossEncoderReranker, Searcher

OUT = REPO_ROOT / "web" / "src" / "test" / "fixtures"
USER = {"X-PLG-User": "S05"}
QUESTION = "When do we issue a letter of demand?"


def cite(phrase: str, answer: str) -> Callable[[list[AgentMessage]], AgentTurn]:
    """Claude's final turn, citing the first search-result sentence containing `phrase`."""

    def reply(messages: list[AgentMessage]) -> AgentTurn:
        results = [
            b
            for m in messages if m["role"] == "user" and not isinstance(m["content"], str)
            for r in m["content"] if r["type"] == "tool_result" and isinstance(r["content"], list)
            for b in r["content"]
        ]
        for index, result in enumerate(results):
            for i, block in enumerate(result["content"]):
                if phrase in block["text"]:
                    return turn(text(answer, {
                        "type": "search_result_location", "source": result["source"], "title": result["title"],
                        "cited_text": block["text"], "search_result_index": index,
                        "start_block_index": i, "end_block_index": i + 1,
                    }))
        raise LookupError(f"No search result contains {phrase!r}")

    return reply


def answer(llm: ScriptedLLMClient) -> None:
    llm.script_turns("route", QUESTION, turn(tool_call("route", intents=["knowledge"])))
    llm.script_turns(
        "knowledge", QUESTION,
        turn(tool_call("search_corpus", query="letter of demand arrears")),
        cite("60 days", "A letter of demand is issued once arrears reach 60 days."),
    )
    llm.script("merge", QUESTION, "Under **POL-003 v2.0**, a letter of demand is issued once arrears reach 60 days [1].")


def not_covered(llm: ScriptedLLMClient) -> None:
    llm.script_turns("route", QUESTION, turn(tool_call("route", intents=["knowledge"])))
    llm.script_turns(
        "knowledge", QUESTION,
        turn(tool_call("search_corpus", query="letter of demand arrears")),
        turn(text("The sources don't say.")),
    )


def error(llm: ScriptedLLMClient) -> None:
    llm.script_turns("route", QUESTION, turn(tool_call("route", intents=[])))
    llm.script("merge", QUESTION, "Under POL-003 v2.0, a letter of", error=ConnectionError("Claude unavailable"))


SCRIPTS: dict[str, Callable[[ScriptedLLMClient], None]] = {
    "answer": answer, "not_covered": not_covered, "error": error,
}


def searcher(index: Path) -> Searcher:
    settings = Settings()
    embedder = HashingEmbedder(dim=128)
    store = LanceSearchStore(index, dim=embedder.dim)
    entities, tagger = load_entity_spine(settings.records_db)
    sources: list[Any] = [SharePointSource(settings.corpus_dir), LotusNotesSource(settings.corpus_dir)]
    sync(store, embedder, sources, entities, tagger)
    return Searcher(store, embedder, CrossEncoderReranker(settings))


def record(search: Searcher, script: Callable[[ScriptedLLMClient], None]) -> str:
    llm = ScriptedLLMClient()
    script(llm)
    with TestClient(create_app(Settings(), llm=llm, searcher=search)) as client:
        thread_id = client.post("/threads", headers=USER).json()["thread_id"]
        with client.stream(
            "POST", f"/threads/{thread_id}/runs", json={"message": QUESTION}, headers=USER
        ) as response:
            return response.read().decode()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as index:
        search = searcher(Path(index))
        for name, script in SCRIPTS.items():
            path = OUT / f"{name}.sse"
            path.write_text(record(search, script))
            print(f"wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
