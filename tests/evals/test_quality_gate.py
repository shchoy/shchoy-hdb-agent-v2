"""Quality regression gate (#31): the golden datasets' gate subset, with real Claude, through the LangSmith pytest
integration (`@pytest.mark.langsmith`: each case's inputs, outputs, reference and scores are logged to LangSmith's
`plg-quality-gate` test suite when LANGSMITH_API_KEY is set; LANGSMITH_TEST_TRACKING=false keeps them local).

Opt-in: runs only with PLG_EVALS=1 and ANTHROPIC_API_KEY (the CI `evals` job), as it calls Claude. It asks over the
session's synced poc-data index (offline hashing embedder, local cross-encoder), so it needs no Voyage key; the full
experiments (`plg eval run`) use the real `plg sync` index. Each case must meet its dataset's POC target."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest
import langsmith
from langsmith import testing as t

from plg.config import Settings
from plg.entities.open import LazyGraph
from plg.evals.evaluators import TARGETS, Judge, evaluators_for
from plg.evals.golden import DATASETS, Golden, dataset
from plg.evals.harness import Harness
from plg.llm import AnthropicLLMClient
from plg.search.embed import HashingEmbedder
from plg.search.rerank import CrossEncoderReranker, Searcher
from plg.tracing import tracing_client
from tests.conftest import CountingEmbedder, open_store

pytestmark = pytest.mark.skipif(
    os.environ.get("PLG_EVALS") != "1" or not os.environ.get("ANTHROPIC_API_KEY"),
    reason="the quality gate calls Claude: set PLG_EVALS=1 and ANTHROPIC_API_KEY",
)

GATE: list[tuple[str, Golden]] = [(name, g) for name in DATASETS if name != "audit" for g in dataset(name) if g.gate]
"""Every dataset's gate subset (the corpus audit is a whole-corpus Opus run: `plg eval run audit`)."""

PER_CASE = {"defect": "category", "doc_check": "exact"}
"""The per-case metric where a dataset's target is an experiment-level one (macro-F1, recall)."""


def required(name: str) -> tuple[str, float]:
    if name in PER_CASE:
        return PER_CASE[name], 1.0
    target = TARGETS[name]
    return target.metric, target.threshold


@pytest.fixture(scope="module", autouse=True)
def masked_langsmith() -> None:
    """The cases (inputs, answers, query rows, drafts) reach LangSmith through plg's masking client only."""
    if os.environ.get("LANGSMITH_API_KEY"):
        langsmith.configure(client=tracing_client(Settings.from_env().records_db))


@pytest.fixture
def harness(
    synced_corpus: tuple[Path, CountingEmbedder, str], reranker: CrossEncoderReranker, trackers_db: Path, tmp_path: Path,
) -> Harness:
    index, embedder, _ = synced_corpus
    settings = Settings.from_env().model_copy(update={"trackers_db": trackers_db, "graph_dir": tmp_path / "graph"})
    searcher = Searcher(open_store(index, embedder), HashingEmbedder(dim=128), reranker, candidates=50)
    return Harness(AnthropicLLMClient(settings), searcher, settings, entities=LazyGraph(settings), scratch=tmp_path)


@pytest.mark.langsmith(test_suite_name="plg-quality-gate")
@pytest.mark.parametrize(("name", "golden"), GATE, ids=[g.id for _, g in GATE])
def test_quality_gate(name: str, golden: Golden, harness: Harness) -> None:
    t.log_inputs({"dataset": name, **golden.inputs()})
    t.log_reference_outputs(golden.reference)
    evaluators, _ = evaluators_for(name, Judge(harness.llm))

    async def case() -> tuple[dict[str, Any], list[dict[str, Any]]]:
        outcome = await harness.ask(golden.question, golden.user, route_only=name == "route")
        outputs = outcome.model_dump(mode="json")
        scored = [m for evaluate in evaluators for m in await evaluate(golden.inputs(), outputs, golden.reference)]
        return outputs, scored

    outputs, scored = asyncio.run(case())
    t.log_outputs(outputs)
    for m in scored:
        t.log_feedback(key=m["key"], score=m["score"])
    key, threshold = required(name)
    found = next(m for m in scored if m["key"] == key)
    assert found["score"] >= threshold, f"{golden.id}: {key} {found['score']:.0%} < {threshold:.0%} ({found['comment']})"
