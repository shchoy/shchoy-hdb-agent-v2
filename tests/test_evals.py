"""Golden datasets and quality evals (#31), offline: `plg eval` with a scripted Claude and a stand-in LangSmith.

The real experiments (`plg eval run`) and the pytest regression gate (tests/evals/) run real Claude; here the
datasets, the harness, the evaluators and the pass/fail verdicts are checked at the CLI seam."""

from __future__ import annotations

import json
import uuid
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from plg import cli
from plg.evals.evaluators import CORRECTNESS, JUDGE, correctness_request
from plg.evals.golden import dataset
from plg.llm import AgentMessage, AgentTurn, ScriptedLLMClient, tool_call, turn
from tests.conftest import CORPUS, route
from tests.test_doc_check_api import SCANS, is_scan, name
from plg.doccheck.identify import IDENTIFY_NODE, identify_prompt

GROUND_TRUTH = CORPUS / "_master"


def master(name: str) -> Any:
    return json.loads((GROUND_TRUTH / f"{name}.json").read_text())


# ---------------------------------------------------------------- a stand-in LangSmith

@dataclass
class FakeDataset:
    id: uuid.UUID
    name: str
    description: str | None


@dataclass
class FakeExample:
    id: uuid.UUID
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    metadata: dict[str, Any]


@dataclass
class FakeLangSmith:
    """The datasets API `plg eval seed` uses, in memory."""

    datasets: dict[str, FakeDataset] = field(default_factory=dict)
    examples: dict[uuid.UUID, dict[uuid.UUID, FakeExample]] = field(default_factory=dict)

    def has_dataset(self, *, dataset_name: str) -> bool:
        return dataset_name in self.datasets

    def read_dataset(self, *, dataset_name: str) -> FakeDataset:
        return self.datasets[dataset_name]

    def create_dataset(self, dataset_name: str, *, description: str | None = None) -> FakeDataset:
        ds = self.datasets[dataset_name] = FakeDataset(uuid.uuid4(), dataset_name, description)
        self.examples[ds.id] = {}
        return ds

    def list_examples(self, *, dataset_id: uuid.UUID) -> list[FakeExample]:
        return list(self.examples[dataset_id].values())

    def create_examples(self, *, dataset_id: uuid.UUID, examples: list[dict[str, Any]]) -> None:
        for e in examples:
            assert e["id"] not in self.examples[dataset_id]
            self.examples[dataset_id][e["id"]] = FakeExample(e["id"], e["inputs"], e["outputs"], e["metadata"])

    def update_examples(self, *, dataset_id: uuid.UUID, updates: list[dict[str, Any]]) -> None:
        for e in updates:
            self.examples[dataset_id][e["id"]] = FakeExample(e["id"], e["inputs"], e["outputs"], e["metadata"])

    def delete_examples(self, ids: list[uuid.UUID]) -> None:
        for examples in self.examples.values():
            for i in ids:
                examples.pop(i, None)

    def of(self, dataset_name: str) -> dict[str, FakeExample]:
        """A dataset's examples by golden ID."""
        return {e.metadata["golden_id"]: e for e in self.examples[self.datasets[dataset_name].id].values()}


class NoSearch:
    def search(self, *_: Any, **__: Any) -> list[Any]:
        return []


@pytest.fixture
def evals(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[ScriptedLLMClient, FakeLangSmith]:
    llm, langsmith = ScriptedLLMClient(), FakeLangSmith()
    monkeypatch.setattr(cli, "make_llm", lambda settings: llm)
    monkeypatch.setattr(cli, "make_eval_client", lambda settings: langsmith)
    monkeypatch.setattr(cli, "make_eval_index", lambda settings, audit: (NoSearch(), None))
    monkeypatch.setenv("PLG_GRAPH_DIR", str(tmp_path / "graph"))
    monkeypatch.setenv("PLG_TRACKERS_DB", str(tmp_path / "trackers.duckdb"))
    return llm, langsmith


def plg(*args: str, exit_code: int = 0) -> Result:
    result = CliRunner().invoke(cli.app, list(args))
    assert result.exit_code == exit_code, result.output
    return result


# ---------------------------------------------------------------- datasets

def test_the_golden_datasets_are_listed_with_their_gate_subset_and_poc_target() -> None:
    output = plg("eval", "list").output
    for line in [
        "route        29 examples", "doc_check    20 examples", "audit         1 examples", "e2e          28 examples",
        "intent_accuracy >= 90%", "faithfulness >= 85%", "execution_accuracy >= 80%", "slot_accuracy >= 90%",
        "macro_f1 >= 85%", "recall >= 90%", "conflict_recall >= 80%", "guarded >= 100%",
    ]:
        assert line in output


def test_seeding_mirrors_the_ground_truth_into_langsmith_datasets_and_is_idempotent(
    evals: tuple[ScriptedLLMClient, FakeLangSmith],
) -> None:
    _, langsmith = evals
    first = plg("eval", "seed").output
    assert "plg-route: 29 created, 0 updated, 0 removed" in first
    assert "plg-e2e: 28 created" in first
    assert sorted(langsmith.datasets) == sorted(f"plg-{n}" for n in [
        "route", "knowledge", "data", "drafting", "defect", "doc_check", "tasks", "glossary", "guardrails", "audit", "e2e"])

    # §5's 28 questions, end to end and routed
    e2e = langsmith.of("plg-e2e")
    assert e2e["e2e-q11"].inputs["question"] == "What are Golden Leaf Minimart's arrears now?"
    assert e2e["e2e-q11"].outputs["answer"] == "S$22,672.00, 121 days, 4.0 months of rent."
    assert langsmith.of("plg-route")["route-q16"].outputs["intents"] == ["doc_check"]
    assert langsmith.of("plg-route")["route-q23"].inputs["user"] == "S01"  # a director may rank a colleague's tasks
    # planned conflicts C1-C6
    knowledge = langsmith.of("plg-knowledge")
    for c in master("planned_conflicts"):
        assert c["resolution"] in knowledge[f"knowledge-{c['id'].lower()}"].outputs["answer"]
    assert set(langsmith.of("plg-audit")["audit-corpus"].outputs["conflicts"]) == {"C1", "C2", "C3", "C4", "C5", "C6"}
    # submission bundles: every one, missing documents and problems as the ground truth has them
    doc_check = langsmith.of("plg-doc_check")
    for b in master("submission_bundles_ground_truth"):
        ref = doc_check[f"doc-check-{b['application_id'].lower()}"].outputs
        assert ref["missing"] == sorted(b["missing_mandatory"])
        assert b["problems"].items() <= ref["problems"].items()
    assert doc_check["doc-check-app-2026-0228"].outputs["missing"] == ["GIRO", "INS"]
    # data-quality issues and key entities
    data = langsmith.of("plg-data")
    issues = master("data_quality_issues")
    assert data["data-dq-null-floor-area"].outputs["values"] == issues["null_floor_area"]
    assert data["data-dq-outlier-rent"].outputs["values"] == ["TA-2022-00400", 63100]
    assert langsmith.of("plg-drafting")["drafting-q18"].outputs["slots"] == {
        "feedback_id": "FB-2026-00707", "ticket_reference": "IEMS-2608-0022"}
    assert data["data-q11"].metadata["gate"] is True

    again = plg("eval", "seed").output
    assert "plg-route: 0 created, 29 updated, 0 removed" in again
    assert len(langsmith.of("plg-route")) == 29


def test_seeding_one_dataset_leaves_the_others_alone(evals: tuple[ScriptedLLMClient, FakeLangSmith]) -> None:
    _, langsmith = evals
    assert "plg-doc_check: 20 created" in plg("eval", "seed", "doc_check").output
    assert list(langsmith.datasets) == ["plg-doc_check"]
    assert "Unknown dataset(s) nope" in plg("eval", "seed", "nope", exit_code=1).output


# ---------------------------------------------------------------- experiments

def script_routes(llm: ScriptedLLMClient, name: str, *, wrong: AbstractSet[str] = frozenset()) -> None:
    """Route every gate question of `name` as the golden reference expects, except `wrong` ones (sent to tasks)."""
    for g in dataset(name):
        if g.gate:
            intents = ["tasks"] if g.id in wrong else g.reference["intents"]
            route(llm, g.question, *intents)


def test_route_accuracy_over_the_gate_subset_passes_its_target(evals: tuple[ScriptedLLMClient, FakeLangSmith]) -> None:
    llm, _ = evals
    script_routes(llm, "route")

    output = plg("eval", "run", "route", "--gate", "--offline").output

    assert "PASS route: intent_accuracy 100% (target 90%, 10 examples)" in output
    assert not llm.streamed  # a routing eval stops at the fan-out: no answer is written


def test_routing_below_90_percent_fails_and_names_the_misrouted_questions(
    evals: tuple[ScriptedLLMClient, FakeLangSmith],
) -> None:
    llm, _ = evals
    script_routes(llm, "route", wrong={"route-q01", "route-q09"})

    output = plg("eval", "run", "route", "--gate", "--offline", exit_code=1).output

    assert "FAIL route: intent_accuracy 80% (target 90%, 10 examples)" in output
    assert "- route-q01: routed ['tasks'], expected ['knowledge']" in output
    assert "- route-q09: routed ['tasks'], expected ['data']" in output


def test_doc_check_recall_over_the_20_bundles_with_claude_reading_the_scans(
    evals: tuple[ScriptedLLMClient, FakeLangSmith],
) -> None:
    llm, _ = evals
    for b in master("submission_bundles_ground_truth"):
        question = f"Is application {b['application_id']} complete?"
        route(llm, question, "doc_check")
        for file in b["files"]:
            if is_scan(file):
                reading = SCANS["GIRO" if file["problem"] == "illegible_scan" else "NRIC"]
                llm.script_turns(IDENTIFY_NODE, identify_prompt(b["application_id"], name(file)),
                                 turn(tool_call("record_document", **reading)))
        llm.script("merge", question, "Here is the document check.")

    output = plg("eval", "run", "doc_check", "--offline").output

    assert "PASS doc_check: recall 100% (target 90%, 20 examples)" in output
    assert "    exact 100%" in output
    assert "    precision 100%" in output


def test_defect_macro_f1_is_computed_over_the_labelled_feedback(evals: tuple[ScriptedLLMClient, FakeLangSmith]) -> None:
    llm, _ = evals
    examples = dataset("defect")
    misfiled = {examples[0].id}  # a PLB case called SEP: PLB recall and SEP precision drop
    for g in examples:
        code = "SEP" if g.id in misfiled else g.reference["category_code"]
        route(llm, g.question, "defect")
        llm.script_turns("defect", g.question, turn(tool_call(
            "classify_feedback", categories=[{"code": code, "confidence": 0.9}], rationale="Because.",
            feedback=g.question.split(":", 1)[-1].strip().strip("'"))))
        llm.script("merge", g.question, "Classified.")

    output = plg("eval", "run", "defect", "--offline", "--concurrency", "8").output

    assert f"PASS defect: macro_f1 {_macro_f1_with_one_plb_as_sep(examples):.0%} (target 85%, 35 examples)" in output
    assert "    category 97%" in output  # 34 of 35


def _macro_f1_with_one_plb_as_sep(examples: list[Any]) -> float:
    gold = [g.reference["category_code"] for g in examples]
    plb, sep = gold.count("PLB"), gold.count("SEP")
    f1 = {code: 1.0 for code in set(gold)}
    f1["PLB"] = 2 * (plb - 1) / (2 * (plb - 1) + 1)
    f1["SEP"] = 2 * sep / (2 * sep + 1)
    return sum(f1.values()) / len(f1)


def test_end_to_end_answers_are_judged_by_opus_against_the_reference_answer(
    evals: tuple[ScriptedLLMClient, FakeLangSmith],
) -> None:
    llm, _ = evals
    g = dataset("e2e")[0]
    answer = "PLG issues the Letter of Demand at 60 days overdue."
    route(llm, g.question)  # answered directly by merge
    llm.script("merge", g.question, answer)
    judged: list[str] = []

    def grade(messages: list[AgentMessage]) -> AgentTurn:
        judged.append(str(messages[-1]["content"]))
        return turn(tool_call("grade", score=0.5, reasoning="Right trigger; misses the hardship call and SOP-014."))
    llm.script_turns(JUDGE, correctness_request(g.question, answer, g.reference["answer"]), grade)

    output = plg("eval", "run", "e2e", "--offline", "--limit", "1", exit_code=1).output

    assert "FAIL e2e: correctness 50% (target 80%, 1 examples)" in output
    assert "- e2e-q01: Right trigger; misses the hardship call and SOP-014." in output
    assert "60 days overdue, after a hardship call" in judged[0]  # the reference answer from §5
    assert any(CORRECTNESS in str(system) for system, _ in llm.requests)
    assert "    mentions 100%" in output


def test_a_model_override_must_name_a_tier(evals: tuple[ScriptedLLMClient, FakeLangSmith]) -> None:
    output = plg("eval", "run", "route", "--offline", "--model", "large=claude-x", exit_code=1).output
    assert "--model takes tier=model_id" in output


def test_a_run_that_fails_never_counts_as_routed_correctly(evals: tuple[ScriptedLLMClient, FakeLangSmith]) -> None:
    llm, _ = evals  # nothing scripted: every route call fails, the greeting's "no specialist" included

    output = plg("eval", "run", "route", "--gate", "--offline", exit_code=1).output

    assert "FAIL route: intent_accuracy 0% (target 90%, 10 examples)" in output
    assert "- route-greeting: the run failed: The run failed before the answer was complete." in output
