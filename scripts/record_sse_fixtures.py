"""Record SSE streams and source-viewer responses from an in-process plg-api for the web tests to replay (MSW).

    uv run python scripts/record_sse_fixtures.py

Writes `web/src/test/fixtures/*.sse` and `documents/*.json` (a document and a cited span's location, per file type). Streams come from the real API and graph with a scripted
LLMClient, and the knowledge agent searches the poc-data corpus synced into a temporary index
(offline hashing embeddings, real cross-encoder), so they match what the BFF receives from `plg serve`.
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from plg.api.app import create_app
from plg.config import REPO_ROOT, Settings
from plg.entities.local import LocalGraphStore
from plg.entities.spine import write_spine
from plg.entities.writer import GraphWriter
from plg.ingest.lineage import NODE, extract_lineage
from plg.ingest.metadata import load_entity_spine
from plg.ingest.sources import LotusNotesSource, SharePointSource
from plg.ingest.sync import sync
from plg.llm import AgentMessage, AgentTurn, ScriptedLLMClient, text, tool_call, turn
from plg.memory.store import MemoryStore
from plg.search.embed import HashingEmbedder
from plg.search.lance import LanceSearchStore
from plg.search.rerank import CrossEncoderReranker, Searcher

OUT = REPO_ROOT / "web" / "src" / "test" / "fixtures"
USER = {"X-PLG-User": "S05"}
QUESTION = "When do we issue a letter of demand?"
POLICY_QUESTION = "How far can a tenant display goods beyond the shopfront?"
DRAFT_QUESTION = "Draft an update reply to the member of public who gave feedback FB-2025-00002"


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


def draft(llm: ScriptedLLMClient) -> None:
    """A feedback reply with an open slot and a tenant's phone number in it, so the preview shows both flags."""
    llm.script_turns("route", DRAFT_QUESTION, turn(tool_call("route", intents=["drafting"])))
    llm.script_turns(
        "drafting", DRAFT_QUESTION,
        turn(tool_call("submit_draft", template_id="TPL-FBK-03", slots={
            "feedback_id": "FB-2025-00002", "reply_date": "30 September 2026", "provider_name": "Sir/Madam",
            "received_date": "2 October 2025", "location": "Blk 675 #02-07", "issue_summary": "a leaking ceiling",
            "ticket_reference": "IEMS-2510-0002",
            "next_steps": "If it recurs, call the shop on +65 9138 9404.", "officer_name": "Siti Aishah Yusof",
        }, unfilled=[{"slot": "action_taken", "reason": "The case record doesn't say what was done."}])),
        turn(text("Drafted the feedback reply.")),
    )
    llm.script("merge", DRAFT_QUESTION, "I drafted the reply from TPL-FBK-03. Nothing has been sent.")


def policy_stance(llm: ScriptedLLMClient) -> None:
    """The display-area limit (POL-001 v3.0 cl. 7.3 overridden for NC units by Circular 07/2026), plus POL-003, whose v1.0 was superseded."""
    llm.script_turns("route", POLICY_QUESTION, turn(tool_call("route", intents=["knowledge"])))
    llm.script_turns(
        "knowledge", POLICY_QUESTION,
        turn(tool_call("policy_lineage", policy_id="PLG-POL-001"), tool_call("policy_lineage", policy_id="PLG-POL-003")),
        cite("overrides clause 7.3", "Circular 07/2026 raises the limit to 1.0 m for NC units from 1 August 2026."),
    )
    llm.script("merge", POLICY_QUESTION, "NC units: 1.0 m from 1 Aug 2026 [1]. Void-deck shops: still 0.6 m.")


class LineageHaiku(ScriptedLLMClient):
    """Scripted Haiku for lineage extraction: reads the supersedes line of POL-003 v2.0 and Circular 07's override."""

    async def complete(self, *, node: str, **kwargs: Any) -> AgentTurn:
        if node != NODE:
            return await super().complete(node=node, **kwargs)
        prompt = str(kwargs["messages"][-1]["content"])
        title = prompt.split("\n", 1)[0]
        shown = re.findall(r'<chunk id="([^"]+)" location="[^"]*">\n(.*?)\n</chunk>', prompt, flags=re.S)

        def find(needle: str) -> tuple[str, str]:
            return next((c, line.strip()) for c, t in shown for line in t.splitlines() if needle in line)

        def edge(kind: str, src: tuple[str, str], dst: tuple[str, str], chunk: str, quote: str, **extra: str) -> dict[str, Any]:
            return {"type": kind, "source_id": src[0], "source_label": src[1], "target_id": dst[0],
                    "target_label": dst[1], "evidence_chunk_id": chunk, "evidence_quote": quote, **extra}

        edges: list[dict[str, Any]] = []
        if "Rental Arrears Management Policy (v2.0)" in title:
            chunk, line = find("Supersedes")
            edges = [edge("SUPERSEDES", ("PLG-POL-003 v2.0", "Policy"), ("PLG-POL-003 v1.0", "Policy"), chunk, line)]
        elif "Circular 07" in title:
            chunk, _ = find("replaces the 0.6 m limit")
            quote = "replaces the 0.6 m limit in clause 7.3 of PLG-POL-001 Trade Mix & Usage Policy v3.0 for NC units"
            edges = [edge("OVERRIDES", ("Circular 07/2026", "Circular"), ("PLG-POL-001 v3.0 cl. 7.3", "Clause"),
                          chunk, quote, scope="NC units only")]
        return turn(tool_call("record_edges", edges=edges))


def lineage_graph(store: LanceSearchStore, graph_dir: Path) -> LocalGraphStore:
    """The records spine plus lineage edges extracted (by the scripted Haiku) from the synced corpus."""
    write_spine(Settings().records_db, graph_dir / "spine")
    graph = LocalGraphStore.from_dirs(graph_dir / "spine")
    asyncio.run(extract_lineage(LineageHaiku(), store, GraphWriter(graph_dir, graph)))
    return graph


SCRIPTS: dict[str, tuple[str, Callable[[ScriptedLLMClient], None]]] = {
    "answer": (QUESTION, answer), "not_covered": (QUESTION, not_covered), "error": (QUESTION, error),
    "draft": (DRAFT_QUESTION, draft), "policy_stance": (POLICY_QUESTION, policy_stance),
}


DOCUMENTS = {
    "pdf": "pdfs/Guidelines_AA_Works_Commercial_Tenants_2025.pdf",
    "docx": "docs/PLG-POL-003_Rental_Arrears_Management_Policy_v2.0.docx",
    "email": "emails/prima_deposit/01_20260723.eml",
    "markdown": "docs/notes/onboarding_guide_new_officers.md",
}


def record_documents(store: LanceSearchStore) -> dict[str, Any]:
    """Per file type: the document and where the first line of its last chunk sits, as a citation would ask."""
    by_path = {d.source_path: d.doc_id for d in store.documents()}
    recorded: dict[str, Any] = {}
    with TestClient(create_app(Settings(), llm=ScriptedLLMClient(), store=store)) as client:
        for kind, path in DOCUMENTS.items():
            doc_id = by_path[path]
            chunk = store.chunks(doc_id)[-1]
            end = chunk.text.find("\n")
            end = len(chunk.text) if end < 0 else end
            document = client.get(f"/documents/{doc_id}", headers=USER).json()
            located = client.get(
                f"/documents/{doc_id}/chunks/{chunk.chunk_id.replace('#', '%23')}",
                params={"start": 0, "end": end}, headers=USER,
            ).json()
            recorded[kind] = {"document": document, "location": located, "start": 0, "end": end}
    return recorded


def searcher(index: Path) -> tuple[Searcher, LanceSearchStore]:
    settings = Settings()
    embedder = HashingEmbedder(dim=128)
    store = LanceSearchStore(index, dim=embedder.dim)
    entities, tagger = load_entity_spine(settings.records_db)
    sources: list[Any] = [SharePointSource(settings.corpus_dir), LotusNotesSource(settings.corpus_dir)]
    sync(store, embedder, sources, entities, tagger)
    return Searcher(store, embedder, CrossEncoderReranker(settings), candidates=50), store


def scratch_memory(directory: Path) -> MemoryStore:
    """A throwaway memory store, so recording never needs Voyage."""
    embedder = HashingEmbedder(dim=128)
    return MemoryStore(LanceSearchStore(directory, dim=embedder.dim), embedder)


def record(
    search: Searcher, question: str, script: Callable[[ScriptedLLMClient], None], graph: LocalGraphStore | None = None
) -> str:
    llm = ScriptedLLMClient()
    script(llm)
    with tempfile.TemporaryDirectory() as scratch:
        # Threads, memory and WORKED_ON links go to scratch space, never the real .plg stores.
        settings = Settings(graph_dir=Path(scratch) / "graph", threads_db=Path(scratch) / "threads.sqlite")
        app = create_app(settings, llm=llm, searcher=search, entities=graph, memory=scratch_memory(Path(scratch) / "memory"))
        return _stream(app, question)


def _stream(app: Any, question: str) -> str:
    with TestClient(app) as client:
        thread_id = client.post("/threads", headers=USER).json()["thread_id"]
        with client.stream(
            "POST", f"/threads/{thread_id}/runs", json={"message": question}, headers=USER
        ) as response:
            return response.read().decode()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as index, tempfile.TemporaryDirectory() as graph_dir:
        search, store = searcher(Path(index))
        graph = lineage_graph(store, Path(graph_dir))
        for name, (question, script) in SCRIPTS.items():
            path = OUT / f"{name}.sse"
            path.write_text(record(search, question, script, graph))
            print(f"wrote {path.relative_to(REPO_ROOT)}")
        (OUT / "documents").mkdir(exist_ok=True)
        for kind, recorded in record_documents(store).items():
            path = OUT / "documents" / f"{kind}.json"
            path.write_text(json.dumps(recorded, indent=2) + "\n")
            print(f"wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
