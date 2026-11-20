"""Corpus audit report (issue #30): `plg audit` finds conflicting documents, duplicates, stale SOPs, report figures
using superseded definitions, PLG Records rule violations and gaps; `GET /audit/reports/latest` serves the report.

The corpus is the session's synced poc-data index (hashing embedder), copied so the audit's graph writes never touch
the shared one. Candidate generation, rule checks and gaps are real; Opus is scripted: it confirms the planted
conflicts (C1-C6 of `_master/planned_conflicts.json`) and duplicates (`_report.md` §2) quoting the chunks it was
shown, and says "none" to every other candidate.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from plg import cli
from plg.audit import judge
from plg.audit.audit import thresholds_for
from plg.audit.candidates import Candidates, Corpus, PairCandidate, RecordPassage, candidates
from plg.audit.model import AuditReport
from plg.audit.questions import QuestionEntry, QuestionLog
from plg.audit.rules import check_rules
from plg.config import Settings
from plg.entities.local import LocalGraphStore
from plg.llm import AgentMessage, AgentTurn, ScriptedLLMClient, text, tool_call, turn
from plg.ontology.glossary import load_glossary
from plg.ontology.vocab import load_vocab
from plg.search.lance import LanceSearchStore
from plg.search.models import DocumentMeta
from tests.conftest import USER, Api, CountingEmbedder, open_store, route
from tests.test_knowledge_api import answer_citing

POL_001 = "docs/PLG-POL-001_Trade_Mix_and_Usage_Policy_v3.0.docx"
POL_002 = "docs/PLG-POL-002_Tenancy_Renewal_and_Security_Deposit_Policy_v2.1.docx"
POL_003_V2 = "docs/PLG-POL-003_Rental_Arrears_Management_Policy_v2.0.docx"
SOP_014 = "docs/PLG-SOP-014_Rental_Arrears_Recovery_SOP_v1.2.docx"
SOP_011_V1 = "docs/PLG-SOP-011_Commercial_Unit_Inspection_SOP_v1.0.docx"
SOP_011_V2 = "docs/PLG-SOP-011_Commercial_Unit_Inspection_SOP_v1.1.docx"
FAQ = "pdfs/Tenant_FAQ_Commercial_2025.pdf"
FAQ_COPY = "pdfs/Tenant_FAQ_Commercial_2025_final(1).pdf"
CIRCULAR_03 = "pdfs/PLG_Circular_03-2026_Revised_Arrears_Policy.pdf"
CIRCULAR_03_TXT = "docs/notes/PLG_Circular_03-2026.txt"
CIRCULAR_07 = "pdfs/PLG_Circular_07-2026_NC_Display_Area_Pilot.pdf"
ONBOARDING = "docs/notes/onboarding_guide_new_officers.md"
WELLCARE_REPLY = "emails/renewal_wellcare/02_20260916.eml"
QBR = "decks/PLG_QBR_Q3_2026.pptx"
OPS_AUG = "pdfs/PLG_Monthly_Ops_Report_2026-08.pdf"
AUDIT_REPORT = "pdfs/Internal_Audit_Report_IA-2026-07_Tenancy_Management.pdf"
HENG_ANN_SCAN = "pdfs/Scan_TA_TA-2024-00451_HengAnn.pdf"
HENG_ANN = "record:TA-2024-00451"

DUPLICATES = {
    (FAQ, FAQ_COPY): "near_duplicate", (SOP_011_V1, SOP_011_V2): "earlier_version",
    (CIRCULAR_03, CIRCULAR_03_TXT): "same_content",
}


@dataclass(frozen=True)
class Clash:
    """A scripted conflict: the topic, a phrase each side states (quoted verbatim from the chunk that has it)."""

    topic: str
    a_says: str
    b_says: str
    resolution: str
    prevails: str


# Keyed by the two sources' paths as `candidates` orders them (a record side is its chunk ID).
CONFLICTS = {
    (SOP_014, POL_003_V2): Clash(
        "Letter of demand trigger", "Refer to HEB Legal to issue Letter of Demand", "60 days overdue",
        "PLG-POL-003 v2.0 prevails (LOD at 60 days); SOP-014 v1.2 was not updated after the revision.", "b"),
    (POL_002, FAQ): Clash(
        "Security deposit amount", "three (3) months' rent", "two (2) months' rent",
        "The policy prevails: 3 months' rent. The FAQ is outdated.", "a"),
    (POL_002, ONBOARDING): Clash(
        "Renewal application lead time", "at least six (6) months before the tenancy expires",
        "Tenants should apply **3 months** before expiry", "The policy prevails: at least 6 months.", "a"),
    (CIRCULAR_07, POL_001): Clash(
        "Display area beyond shopfront", "up to 1.0 m beyond the shopfront line",
        "Tenants may display goods up to 0.6 m beyond the shopfront line",
        "Circular 07/2026 replaces cl. 7.3 for NC units from 1 Aug 2026; 0.6 m still applies to void-deck shops.", "a"),
    (AUDIT_REPORT, HENG_ANN): Clash(
        "Monthly rent of TA-2024-00451", "signed agreement states S$4,580.00/month", "Monthly rent: S$4,850.00",
        "The signed agreement is the legal source: PLG Records has a transposition error.", "a"),
    (HENG_ANN_SCAN, HENG_ANN): Clash(
        "Monthly rent of TA-2024-00451", "The monthly rent is S$4,580", "Monthly rent: S$4,850.00",
        "The signed agreement is the legal source: PLG Records has a transposition error.", "a"),
}
UNVERIFIED = (QBR, OPS_AUG)
"""Opus "quotes" something neither chunk says for this pair: the conflict must be dropped."""

_SOURCE = re.compile(r'<source side="(a|b)" id="[^"]+">(.*?)</source>', re.S)
_CHUNK = re.compile(r'<chunk id="([^"]+)" location="[^"]*">\n(.*?)\n</chunk>', re.S)


def squash(value: str) -> str:
    return " ".join(value.split())


def listing(messages: list[AgentMessage]) -> str:
    content = messages[-1]["content"]
    assert not isinstance(content, str)
    return str(content[1]["text"])


def shown(messages: list[AgentMessage]) -> dict[str, list[tuple[str, str]]]:
    """The chunks (ID, text) shown for each side of a pair."""
    return {side: _CHUNK.findall(body) for side, body in _SOURCE.findall(listing(messages))}


def cite(chunks: list[tuple[str, str]], phrase: str) -> str:
    """The ID of the first chunk shown that says `phrase`."""
    for chunk_id, body in chunks:
        if squash(phrase) in squash(body):
            return chunk_id
    raise AssertionError(f"No chunk shown says {phrase!r}")


def conflict_turn(clash: Clash) -> Callable[[list[AgentMessage]], AgentTurn]:
    def reply(messages: list[AgentMessage]) -> AgentTurn:
        sides = shown(messages)
        return turn(tool_call(judge.PAIR_TOOL, relation="conflict", conflicts=[{
            "topic": clash.topic, "a_chunk_id": cite(sides["a"], clash.a_says), "a_quote": clash.a_says,
            "b_chunk_id": cite(sides["b"], clash.b_says), "b_quote": clash.b_says,
            "resolution": clash.resolution, "prevails": clash.prevails,
        }]))
    return reply


def made_up_turn(messages: list[AgentMessage]) -> AgentTurn:
    sides = shown(messages)
    return turn(tool_call(judge.PAIR_TOOL, relation="conflict", conflicts=[{
        "topic": "Vacant units", "a_chunk_id": sides["a"][0][0], "a_quote": "61 vacant units",
        "b_chunk_id": sides["b"][0][0], "b_quote": "47 vacant units", "resolution": "Recount.", "prevails": "none",
    }]))


def qbr_vacancy(messages: list[AgentMessage]) -> AgentTurn:
    chunks = _CHUNK.findall(listing(messages))
    quote = "52 vacant units as at 31 Aug 2026"
    return turn(tool_call(judge.DEFINITION_TOOL, findings=[{
        "concept": "plg:Vacant", "used_version": "plg:Vacant_v1", "chunk_id": cite(chunks, quote), "quote": quote,
        "explanation": "The QBR counts the 5 units under tender as vacant (pre-April definition); under the current "
                       "definition it is 47.",
    }]))


NONE = turn(tool_call(judge.PAIR_TOOL, relation="none"))
NO_FINDINGS = turn(tool_call(judge.DEFINITION_TOOL, findings=[]))


def clash_for(paths: tuple[str, str]) -> Clash | None:
    """The scripted conflict for a pair, whichever way round the candidates put its sources."""
    if clash := CONFLICTS.get(paths):
        return clash
    if clash := CONFLICTS.get((paths[1], paths[0])):
        flipped = {"a": "b", "b": "a"}.get(clash.prevails, clash.prevails)
        return Clash(clash.topic, clash.b_says, clash.a_says, clash.resolution, flipped)
    return None


def side_path(side: DocumentMeta | RecordPassage) -> str:
    return side.source_path if isinstance(side, DocumentMeta) else side.chunk_id


def pair_paths(pair: PairCandidate) -> tuple[str, str]:
    return side_path(pair.a), side_path(pair.b)


def audit_llm(found: Candidates) -> ScriptedLLMClient:
    """Opus, scripted for every candidate the audit will judge."""
    llm = ScriptedLLMClient()
    for d in found.duplicates:
        kind = DUPLICATES.get((d.a.source_path, d.b.source_path))
        reply = turn(tool_call(judge.PAIR_TOOL, relation="duplicate", duplicate_kind=kind,
                               note=f"{d.b.title} repeats {d.a.title}.")) if kind else NONE
        llm.script_turns(judge.NODE, judge.duplicate_request(d), reply)
    for p in found.conflicts:
        paths = pair_paths(p)
        clash = clash_for(paths)
        scripted = conflict_turn(clash) if clash else made_up_turn if set(paths) == set(UNVERIFIED) else NONE
        llm.script_turns(judge.NODE, judge.pair_request(p), scripted)
    for d in found.definitions:
        llm.script_turns(judge.NODE, judge.definition_request(d), qbr_vacancy if d.doc.source_path == QBR else NO_FINDINGS)
    return llm


# ---------------------------------------------------------------- fixtures


@dataclass
class Audited:
    root: Path
    index: Path
    embedder: CountingEmbedder
    output: str = ""

    def env(self) -> dict[str, str]:
        return {
            "PLG_SEARCH_DB": str(self.index), "PLG_EMBED_DIM": str(self.embedder.dim),
            "PLG_GRAPH_DIR": str(self.root / "graph"), "PLG_AUDIT_REPORTS_DIR": str(self.root / "reports"),
            "PLG_QUESTION_LOG": str(self.root / "questions.jsonl"), "PLG_FEEDBACK_LOG": str(self.root / "feedback.jsonl"),
            "PLG_GLOSSARY_CHANGES": str(self.root / "glossary_changes.jsonl"),
        }

    def store(self) -> LanceSearchStore:
        return open_store(self.index, self.embedder)

    def candidates(self) -> Candidates:
        return candidates(Corpus.of(self.store()), Settings().records_db, load_glossary(), thresholds_for(Settings()))

    def run(self, llm: ScriptedLLMClient | None = None, **env: str) -> Result:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(cli, "make_llm", lambda _settings: llm or audit_llm(self.candidates()))
            result = CliRunner().invoke(cli.app, ["audit"], env={**self.env(), **env})
        assert result.exit_code == 0, result.output
        return result

    def graph(self) -> LocalGraphStore:
        return LocalGraphStore.from_dirs(self.root / "graph" / "spine", self.root / "graph" / "delta")


ASKED = datetime(2026, 11, 2, 9, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def audited(
    synced_corpus: tuple[Path, CountingEmbedder, str], tmp_path_factory: pytest.TempPathFactory
) -> Audited:
    source, embedder, _ = synced_corpus
    root = tmp_path_factory.mktemp("audited")
    shutil.copytree(source, root / "index")
    log = QuestionLog(root / "questions.jsonl")
    for n, (question, score, not_covered) in enumerate([
        ("What is the parking fee for loading bays?", None, True),
        ("What is the parking fee for loading bays", None, True),
        ("Who approves a bubble tea kiosk?", 0.05, False),
        ("When is the LOD issued?", 0.9, False),
    ]):
        log.record(QuestionEntry(at=ASKED + timedelta(minutes=n), thread_id="t", run_id=f"run-{n}", staff_id="S05",
                                 question=question, intents=["knowledge"], top_score=score, not_covered=not_covered))
    run = Audited(root, root / "index", embedder)
    run.output = run.run().output
    return run


@pytest.fixture
def audit_api(make_api: Callable[..., Api], audited: Audited) -> Api:
    return make_api(store=audited.store(), audit_reports_dir=audited.root / "reports")


def latest(api: Api) -> dict[str, Any]:
    response = api.client.get("/audit/reports/latest", headers=USER)
    assert response.status_code == 200, response.text
    return dict(response.json())


def doc_id(store: LanceSearchStore, path: str) -> str:
    return next(d.doc_id for d in store.documents() if d.source_path == path)


# ---------------------------------------------------------------- candidates (recall before Opus)


def test_candidates_surface_every_planted_conflict_and_duplicate(store: LanceSearchStore) -> None:
    found = candidates(Corpus.of(store), Settings().records_db, load_glossary(), thresholds_for(Settings()))

    pairs = {frozenset(pair_paths(p)): p for p in found.conflicts}
    assert "lineage" in pairs[frozenset((SOP_014, POL_003_V2))].found_by  # C1
    assert frozenset((POL_002, FAQ)) in pairs  # C2
    assert frozenset((POL_002, ONBOARDING)) in pairs or frozenset((WELLCARE_REPLY, POL_002)) in pairs  # C3
    assert frozenset((CIRCULAR_07, POL_001)) in pairs  # C5
    assert pairs[frozenset((AUDIT_REPORT, HENG_ANN))].found_by == ["records"]  # C6
    assert pairs[frozenset((HENG_ANN_SCAN, HENG_ANN))].found_by == ["records"]
    assert QBR in {d.doc.source_path for d in found.definitions}  # C4
    qbr = next(d for d in found.definitions if d.doc.source_path == QBR)
    assert "plg:Vacant" in qbr.concepts and any("52 vacant units" in c.text for c in qbr.chunks)
    assert set(DUPLICATES) <= {(d.a.source_path, d.b.source_path) for d in found.duplicates}
    assert len(found.duplicates) <= 6  # few pairs besides the planted ones
    assert [s.doc.source_path for s in found.stale] == [SOP_014]
    assert len(found.conflicts) <= Settings().audit_max_pairs


def test_a_document_is_never_paired_with_its_copy_or_another_version_of_itself(store: LanceSearchStore) -> None:
    found = candidates(Corpus.of(store), Settings().records_db, load_glossary(), thresholds_for(Settings()))

    paths = {frozenset(pair_paths(p)) for p in found.conflicts}
    assert frozenset((FAQ, FAQ_COPY)) not in paths and frozenset((CIRCULAR_03, CIRCULAR_03_TXT)) not in paths
    assert not any(FAQ_COPY in p or CIRCULAR_03_TXT in p for p in paths)  # their originals stand for them
    for p in found.conflicts:
        if isinstance(p.b, DocumentMeta):
            assert not (p.a.policy_id and p.a.policy_id == p.b.policy_id)
            assert "superseded" not in {p.a.status, p.b.status} or "lineage" in p.found_by


# ---------------------------------------------------------------- plg audit -> GET /audit/reports/latest


def test_conflicts_are_reported_with_both_sides_cited_verbatim(audited: Audited, audit_api: Api) -> None:
    report = latest(audit_api)
    store = audited.store()

    by_docs = {frozenset((c["a"]["doc_id"], c["b"]["doc_id"] or c["b"]["chunk_id"])): c for c in report["conflicts"]}

    def between(x: str, y: str) -> dict[str, Any]:
        return by_docs[frozenset((doc_id(store, x) if "/" in x else x, doc_id(store, y) if "/" in y else y))]

    c1 = between(SOP_014, POL_003_V2)
    assert c1["a"]["doc_id"] == doc_id(store, SOP_014) and c1["prevails"] == "b" and "lineage" in c1["found_by"]
    assert c1["a"]["quote"] == "Refer to HEB Legal to issue Letter of Demand" and c1["b"]["version"] == "2.0"
    assert between(POL_002, FAQ) and between(POL_002, ONBOARDING) and between(CIRCULAR_07, POL_001)
    c6 = between(AUDIT_REPORT, HENG_ANN)
    assert c6["b"] == {"doc_id": None, "title": "PLG Records: tenancies TA-2024-00451", "chunk_id": HENG_ANN,
                       "location": "PLG Records", "version": None, "quote": "Monthly rent: S$4,850.00"}
    assert c6["found_by"] == ["records"] and c6["resolution"]
    for conflict in report["conflicts"]:
        assert conflict["id"].startswith("CF-")
        for side in (conflict["a"], conflict["b"]):
            if side["doc_id"]:
                chunk = store.get_chunk(side["chunk_id"])
                assert chunk is not None and squash(side["quote"]) in squash(chunk.text)
                assert side["location"] == chunk.location and side["title"] == chunk.title


def test_a_judged_quote_that_isnt_verbatim_is_dropped(audited: Audited, audit_api: Api) -> None:
    report = latest(audit_api)
    store = audited.store()

    pair = {doc_id(store, QBR), doc_id(store, OPS_AUG)}
    assert not [c for c in report["conflicts"] if {c["a"]["doc_id"], c["b"]["doc_id"]} == pair]
    assert any("Vacant units" in d and "not a verbatim span" in d for d in report["dropped"])


def test_duplicates_stale_sops_and_superseded_definitions_are_reported(audited: Audited, audit_api: Api) -> None:
    report = latest(audit_api)
    store = audited.store()

    duplicates = {(d["a"]["doc_id"], d["b"]["doc_id"]): d for d in report["duplicates"]}
    for (original, copy), kind in DUPLICATES.items():
        found = duplicates[(doc_id(store, original), doc_id(store, copy))]
        assert found["kind"] == kind and 0.5 <= found["similarity"] <= 1
    assert len(duplicates) == len(DUPLICATES)  # Opus said the other candidates aren't duplicates

    [stale] = report["stale"]
    assert stale["doc"]["doc_id"] == doc_id(store, SOP_014) and stale["policy_id"] == "PLG-POL-003"
    assert "PLG-POL-003" in stale["quote"] and stale["current_version"] == "PLG-POL-003 v2.0"
    assert stale["current_from"] == "2026-04-01" and "v1.0" in stale["relies_on"]

    [used] = report["superseded_definitions"]
    assert used["doc"]["doc_id"] == doc_id(store, QBR) and used["quote"] == "52 vacant units as at 31 Aug 2026"
    assert (used["concept"], used["used_version"], used["current_version"]) == ("plg:Vacant", "plg:Vacant_v1", "plg:Vacant_v2")
    assert used["current_from"] == "2026-04-15" and used["location"].startswith("Slide 4")


def test_ontology_rule_violations_in_plg_records_are_reported(audit_api: Api) -> None:
    violations = latest(audit_api)["rule_violations"]

    by_rule = {v["rule"]: v for v in violations}
    assert set(by_rule) == {"overlapping_tenancies", "duplicate_tenants"}
    assert {"TA-2024-00079", "TA-2026-00614"} <= set(by_rule["overlapping_tenancies"]["entity_ids"])
    assert by_rule["duplicate_tenants"]["entity_ids"] == ["T-10514", "T-19807"]


def test_gaps_come_from_the_question_log(audit_api: Api) -> None:
    gaps = latest(audit_api)["gaps"]

    assert [(g["question"], g["asked"], g["reasons"]) for g in gaps] == [
        ("What is the parking fee for loading bays", 2, ["not_covered"]),
        ("Who approves a bubble tea kiosk?", 1, ["low_score"]),
    ]
    assert gaps[0]["last_asked"].startswith("2026-11-02T09:31")


def test_conflicts_and_duplicates_are_edges_between_library_documents(audited: Audited) -> None:
    graph, store = audited.graph(), audited.store()

    sop, policy = doc_id(store, SOP_014), doc_id(store, POL_003_V2)
    context = graph.entity_context(sop, hops=1)
    assert context is not None
    [edge] = [e for e in context.edges if e.type == "CONFLICTS_WITH" and e.start == sop]
    assert edge.end == policy  # from the SOP that doesn't prevail to the policy that does
    assert edge.props["evidence_quote"] == "Refer to HEB Legal to issue Letter of Demand"
    node = graph.node(policy)
    assert node is not None and node.label == "LibraryDocument"
    copy, original = doc_id(store, FAQ_COPY), doc_id(store, FAQ)
    context = graph.entity_context(copy, hops=1)
    assert context is not None
    assert [(e.start, e.end) for e in context.edges if e.type == "DUPLICATE_OF"] == [(copy, original)]
    assert "conflicts" in audited.output.casefold() and "Report: " in audited.output


def test_re_running_the_audit_adds_no_edges_and_keeps_the_earlier_report(audited: Audited, audit_api: Api) -> None:
    edges = len(list((audited.root / "graph" / "delta").glob("edges*.csv")))
    before = (audited.root / "graph" / "delta" / "edges.csv").read_text()
    first = latest(audit_api)

    audited.run()

    assert (audited.root / "graph" / "delta" / "edges.csv").read_text() == before
    assert len(list((audited.root / "graph" / "delta").glob("edges*.csv"))) == edges
    second = latest(audit_api)
    assert second["generated_at"] > first["generated_at"]
    assert [c["id"] for c in second["conflicts"]] == [c["id"] for c in first["conflicts"]]
    assert len(list((audited.root / "reports").glob("*.json"))) >= 2


def test_tenant_pii_in_what_opus_wrote_is_masked(audited: Audited, tmp_path: Path) -> None:
    found = audited.candidates()
    llm = audit_llm(found)
    pair = next(p for p in found.conflicts if set(pair_paths(p)) == {POL_002, FAQ})
    leaky = Clash("Deposit for Devi Nair (9391 3713)", "three (3) months' rent", "two (2) months' rent",
                  "Tell devi@nanyangmart.example.com the policy prevails.", "a")
    llm.script_turns(judge.NODE, judge.pair_request(pair), conflict_turn(leaky))
    fresh = Audited(tmp_path, audited.index, audited.embedder)

    fresh.run(llm)

    reports = sorted((tmp_path / "reports").glob("*.json"))
    report = AuditReport.model_validate_json(reports[-1].read_text())
    [conflict] = [c for c in report.conflicts if c.topic.startswith("Deposit")]
    assert "[tenant contact]" in conflict.topic and "[phone]" in conflict.topic and "[email]" in conflict.resolution
    assert "Devi Nair" not in conflict.model_dump_json()


def test_opus_is_never_forced_to_a_tool_and_a_plain_text_reply_is_asked_again(
    audited: Audited, tmp_path: Path
) -> None:
    """The Opus models reject tool_choice "tool"/"any" (invalid_request_error), so the judges offer the tool with
    "auto"; a judge that answers in prose is asked once more for the tool call."""
    found = audited.candidates()
    llm = audit_llm(found)
    pair = next(p for p in found.conflicts if set(pair_paths(p)) == {POL_002, FAQ})
    clash = clash_for(pair_paths(pair))
    assert clash is not None
    first = conflict_turn(clash)

    def after_prose(messages: list[AgentMessage]) -> AgentTurn:
        content = messages[0]["content"]
        assert not isinstance(content, str)
        return first([{"role": "user", "content": content}])  # quote from the listing shown first

    llm.script_turns(judge.NODE, judge.pair_request(pair), turn(text("They conflict on the deposit.")), after_prose)

    Audited(tmp_path, audited.index, audited.embedder).run(llm)

    assert llm.tool_choices and all(choice == {"type": "auto"} for choice in llm.tool_choices)
    nudged = [m for m in llm.sent if len(m) == 3]
    assert nudged and "record_judgement tool" in str(nudged[0][-1]["content"][-1]["text"])
    report = AuditReport.model_validate_json(sorted((tmp_path / "reports").glob("*.json"))[-1].read_text())
    assert any(c.topic == clash.topic for c in report.conflicts)


# ---------------------------------------------------------------- access


def test_before_any_audit_the_latest_report_is_404(make_api: Callable[..., Api], tmp_path: Path) -> None:
    api = make_api(audit_reports_dir=tmp_path / "none")

    response = api.client.get("/audit/reports/latest", headers=USER)

    assert response.status_code == 404 and "plg audit" in response.json()["detail"]


def test_the_report_is_only_for_signed_in_officers(audit_api: Api) -> None:
    assert audit_api.client.get("/audit/reports/latest").status_code == 401


def test_the_approvals_audit_trail_is_unchanged(audit_api: Api) -> None:
    response = audit_api.client.get("/audit", headers=USER)
    assert response.status_code == 200 and response.json() == []


def test_audit_without_an_index_says_to_sync_first(tmp_path: Path) -> None:
    result = CliRunner().invoke(cli.app, ["audit"], env={"PLG_SEARCH_DB": str(tmp_path / "empty"), "PLG_EMBED_DIM": "128"})

    assert result.exit_code == 1 and "plg sync" in result.stderr


# ---------------------------------------------------------------- the question log and gaps


@pytest.fixture
def asking_api(make_api: Callable[..., Api], searcher: Any, langsmith_stub: Any) -> Api:
    return make_api(searcher=searcher, langsmith=langsmith_stub)


class _LangSmithStub:
    def create_feedback(self, *_: Any, **__: Any) -> None: ...

    def list_annotation_queues(self, **_: Any) -> list[Any]:
        return [type("Queue", (), {"id": "q", "name": "PLG thumbs-down review"})()]

    def read_project(self, **_: Any) -> Any:
        return type("Project", (), {"id": "p"})()

    @property
    def annotation_queues(self) -> Any:
        async def create(*_: Any, **__: Any) -> dict[str, Any]:
            return {"items": []}

        return type("Queues", (), {"items": type("Items", (), {"create": staticmethod(create)})()})()


@pytest.fixture
def langsmith_stub() -> _LangSmithStub:
    return _LangSmithStub()


def test_answered_questions_are_logged_and_a_thumbs_down_makes_a_gap(
    asking_api: Api, llm: ScriptedLLMClient, tmp_path: Path, audited: Audited
) -> None:
    covered, uncovered = "When do we issue a letter of demand?", "What colour are the NC bins? Call Devi Nair."
    route(llm, covered, "knowledge")
    llm.script_turns(
        "knowledge", covered, turn(tool_call("search_corpus", query="letter of demand trigger")),
        answer_citing("60 days", "At 60 days overdue."),
    )
    llm.script("merge", covered, "At 60 days overdue [1].")
    route(llm, uncovered, "knowledge")
    llm.script_turns("knowledge", uncovered, turn(text("The sources don't cover this.")))
    thread = asking_api.create_thread()

    first = asking_api.run(thread, covered)
    second = asking_api.run(thread, uncovered)

    entries = QuestionLog(tmp_path / "questions.jsonl").entries()
    assert [(e.question, e.not_covered, e.intents, e.thread_id) for e in entries] == [
        (covered, False, ["knowledge"], thread), ("What colour are the NC bins? Call [tenant contact].", True, ["knowledge"], thread),
    ]
    assert entries[0].top_score is not None and entries[1].top_score is None
    assert [e.run_id for e in entries] == [first.of_type("done")[0]["run_id"], second.of_type("done")[0]["run_id"]]
    assert entries[0].staff_id == "S05"

    down = asking_api.client.post("/feedback", headers=USER, json={
        "thread_id": thread, "run_id": entries[0].run_id, "score": "down", "comment": "Missed the hardship call.",
    })
    assert down.status_code == 201

    found = audited.candidates()
    result = audited.run(audit_llm(found), PLG_QUESTION_LOG=str(tmp_path / "questions.jsonl"),
                         PLG_FEEDBACK_LOG=str(tmp_path / "feedback.jsonl"), PLG_GAP_MIN_SCORE="-1000",
                         PLG_AUDIT_REPORTS_DIR=str(tmp_path / "reports"))
    assert "Gaps: 2" in result.output
    report = AuditReport.model_validate_json(sorted((tmp_path / "reports").glob("*.json"))[-1].read_text())
    reasons = {g.question: g.reasons for g in report.gaps}
    assert reasons == {covered: ["thumbs_down"], "What colour are the NC bins? Call [tenant contact].": ["not_covered"]}


def test_a_question_log_that_cannot_be_written_never_fails_the_run(
    make_api: Callable[..., Api], llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    blocked = tmp_path / "file"
    blocked.write_text("not a directory")
    api = make_api(question_log=blocked / "questions.jsonl")
    question = "hello"
    route(llm, question)
    llm.script("merge", question, "Hello!")

    stream = api.run(api.create_thread(), question)

    assert stream.text == "Hello!" and not stream.of_type("error")


# ---------------------------------------------------------------- rules over data the corpus lacks


@pytest.fixture
def small_records(tmp_path: Path) -> Iterator[Path]:
    db = tmp_path / "records.db"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE units (unit_id TEXT PRIMARY KEY, unit_type TEXT);
            CREATE TABLE tenants (tenant_id TEXT PRIMARY KEY, name TEXT, brn TEXT);
            CREATE TABLE tenancies (tenancy_id TEXT PRIMARY KEY, unit_id TEXT, tenant_id TEXT, trade TEXT,
                                    start_date TEXT, end_date TEXT, monthly_rent REAL, status TEXT);
            INSERT INTO units VALUES ('U-AA001-01-01', 'Shop with Living Quarters'), ('U-AA001-01-02', 'Shop'),
                                     ('U-AA001-01-03', 'Kiosk');
            INSERT INTO tenants VALUES ('T-00001', 'A', 'B1'), ('T-00002', 'B', 'B2');
            INSERT INTO tenancies VALUES
              ('TA-2026-00001', 'U-AA001-01-01', 'T-00001', 'Hair Salon', '2026-01-01', '2028-12-31', 3000, 'Active'),
              ('TA-2026-00002', 'U-AA001-01-02', 'T-00002', 'Hair Salon', '2026-01-01', '2028-12-31', 3000, 'Active'),
              ('TA-2026-00003', 'U-AA001-01-03', 'T-00002', 'Hair Salon', '2020-01-01', '2022-12-31', 3000, 'Expired');
        """)
    yield db


def policy(doc_id: str, version: str, status: str = "current") -> DocumentMeta:
    return DocumentMeta(doc_id=doc_id, doc_type="policy", title=f"PLG-POL-009 v{version}", source_system="sharepoint",
                        source_path=f"docs/{doc_id}.docx", policy_id="PLG-POL-009", version=version,
                        status=status, content_hash=doc_id)  # type: ignore[arg-type]


def test_a_trade_in_a_unit_type_the_ontology_does_not_allow_is_a_violation(small_records: Path) -> None:
    violations = check_rules(small_records, load_vocab(), [])

    # "Shop" must not match "Shop with Living Quarters"; an expired tenancy is no longer trading there.
    assert [(v.rule, v.entity_ids[0]) for v in violations] == [("trade_not_allowed", "TA-2026-00001")]


def test_two_current_versions_of_one_policy_are_a_violation(small_records: Path) -> None:
    documents = [policy("SP-1", "1.0", "superseded"), policy("SP-2", "2.0"), policy("SP-3", "2.1")]

    [violation] = [v for v in check_rules(small_records, load_vocab(), documents)
                   if v.rule == "two_current_policy_versions"]

    assert violation.entity_ids == ["PLG-POL-009", "SP-2", "SP-3"]
    assert check_rules(small_records, load_vocab(), documents[:2]) == check_rules(small_records, load_vocab(), [])
