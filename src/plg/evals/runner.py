"""Seed the golden datasets into LangSmith and run experiments against them.

`seed` mirrors each golden dataset into LangSmith dataset `plg-<name>` (example IDs derived from the golden IDs, so a
re-seed updates in place and drops examples the ground truth no longer has). `run` asks every example through the
harness, scores it and compares the target metric with the POC threshold; uploaded, it is a LangSmith experiment
(`aevaluate`) whose metadata names the model per tier, the git SHA and a label, so tiers and prompts can be compared.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from langsmith import Client, aevaluate
from langsmith.schemas import Example
from pydantic import BaseModel

from plg.config import Settings
from plg.evals.evaluators import TARGETS, Judge, Metric, metric, RowEvaluator, SummaryEvaluator, Target, evaluators_for
from plg.evals.golden import CORPUS, Golden, dataset
from plg.evals.harness import Harness
from plg.search.store import SearchStore

EXAMPLE_IDS = uuid.UUID("5d0c1f7e-31a0-4b8e-9c55-7a0f31e7d031")
"""Namespace of the LangSmith example IDs (uuid5 of the golden ID)."""


def dataset_name(name: str) -> str:
    return f"plg-{name}"


def example_id(golden: Golden) -> uuid.UUID:
    return uuid.uuid5(EXAMPLE_IDS, golden.id)


def selected(name: str, *, gate: bool = False, limit: int | None = None, corpus: Path = CORPUS) -> list[Golden]:
    examples = [g for g in dataset(name, corpus) if g.gate or not gate]
    return examples if limit is None else examples[:limit]


class SeedResult(BaseModel):
    dataset: str
    created: int
    updated: int
    removed: int


def seed(client: Client, names: Sequence[str], corpus: Path = CORPUS) -> list[SeedResult]:
    results = []
    for name in names:
        golden = dataset(name, corpus)
        ds_name = dataset_name(name)
        if client.has_dataset(dataset_name=ds_name):
            ds = client.read_dataset(dataset_name=ds_name)
        else:
            ds = client.create_dataset(ds_name, description=f"PLG golden dataset: {name} (seeded from poc-data ground truth)")
        existing = {e.id for e in client.list_examples(dataset_id=ds.id)}
        rows = [{"id": example_id(g), "inputs": g.inputs(), "outputs": g.reference,
                 "metadata": {"golden_id": g.id, "source": g.source, "gate": g.gate}} for g in golden]
        new = [r for r in rows if r["id"] not in existing]
        old = [r for r in rows if r["id"] in existing]
        stale = existing - {r["id"] for r in rows}
        if new:
            client.create_examples(dataset_id=ds.id, examples=new)
        if old:
            client.update_examples(dataset_id=ds.id, updates=old)
        if stale:
            client.delete_examples(list(stale))
        results.append(SeedResult(dataset=ds_name, created=len(new), updated=len(old), removed=len(stale)))
    return results


class Row(BaseModel):
    id: str
    metrics: list[Metric]


class EvalReport(BaseModel):
    dataset: str
    experiment: str | None
    """The LangSmith experiment name (None when run offline)."""
    rows: list[Row]
    scores: dict[str, float]
    """The mean of every metric over the experiment (summary metrics as computed)."""
    target: Target
    passed: bool

    @property
    def score(self) -> float | None:
        return self.scores.get(self.target.metric)


def experiment_metadata(settings: Settings, label: str | None) -> dict[str, Any]:
    from plg.tracing import git_sha

    return {"model_haiku": settings.model_haiku, "model_sonnet": settings.model_sonnet, "model_opus": settings.model_opus,
            "rerank_backend": settings.rerank_backend, "git_sha": git_sha(), "label": label or ""}


async def run(
    name: str, harness: Harness, judge: Judge, *, store: SearchStore | None = None, gate: bool = False,
    limit: int | None = None, client: Client | None = None, label: str | None = None, concurrency: int = 4,
    corpus: Path = CORPUS,
) -> EvalReport:
    """Run dataset `name` through the harness. With a `client`, as a LangSmith experiment over the seeded dataset."""
    golden = selected(name, gate=gate, limit=limit, corpus=corpus)
    row_evaluators, summary_evaluators = evaluators_for(name, judge)
    audit_outputs: dict[str, Any] | None = None
    audit_lock = asyncio.Lock()

    async def target(inputs: dict[str, Any]) -> dict[str, Any]:
        nonlocal audit_outputs
        if name == "audit":
            if store is None:
                raise ValueError("The audit dataset needs the search index")
            async with audit_lock:  # one audit per experiment, however many examples ask
                audit_outputs = audit_outputs or await harness.audit(store)
            return audit_outputs
        asked = await harness.ask(inputs["question"], inputs.get("user", "S05"), route_only=name == "route")
        return asked.model_dump(mode="json")

    if client is None:
        outputs = await _run_offline(golden, target, concurrency)
        experiment = None
        rows = [Row(id=g.id, metrics=await _score(row_evaluators, g, o)) for g, o in zip(golden, outputs)]
    else:
        outputs, rows, experiment = await _run_langsmith(
            name, golden, target, row_evaluators, summary_evaluators, client,
            experiment_metadata(harness.settings, label), label, concurrency,
        )
    scores = _means(rows)
    for summary in summary_evaluators:
        for m in summary(outputs, [g.reference for g in golden]):
            scores[m["key"]] = m["score"]
    goal = TARGETS[name]
    return EvalReport(dataset=name, experiment=experiment, rows=rows, scores=scores, target=goal,
                      passed=scores.get(goal.metric, 0.0) >= goal.threshold)


async def _run_offline(golden: list[Golden], target: Any, concurrency: int) -> list[dict[str, Any]]:
    gate = asyncio.Semaphore(concurrency)

    async def one(g: Golden) -> dict[str, Any]:
        async with gate:
            return await target(g.inputs())  # type: ignore[no-any-return]
    return list(await asyncio.gather(*(one(g) for g in golden)))


async def _score(evaluators: list[RowEvaluator], g: Golden, outputs: dict[str, Any]) -> list[Metric]:
    found: list[Metric] = []
    for evaluate in evaluators:
        found += await evaluate(g.inputs(), outputs, g.reference)
    return found


def _means(rows: list[Row]) -> dict[str, float]:
    totals: dict[str, list[float]] = {}
    for row in rows:
        for m in row.metrics:
            totals.setdefault(m["key"], []).append(m["score"])
    return {k: sum(v) / len(v) for k, v in totals.items()}


async def _run_langsmith(
    name: str, golden: list[Golden], target: Any, row_evaluators: list[RowEvaluator],
    summary_evaluators: list[SummaryEvaluator], client: Client, metadata: dict[str, Any], label: str | None,
    concurrency: int,
) -> tuple[list[dict[str, Any]], list[Row], str]:
    """A LangSmith experiment over the seeded examples of `golden`: the run outputs and their scores, in `golden`'s
    order."""
    ids = {example_id(g): g for g in golden}
    examples: list[Example] = list(client.list_examples(dataset_name=dataset_name(name), example_ids=list(ids)))
    if len(examples) != len(ids):
        raise RuntimeError(f"{dataset_name(name)} is not seeded with the current golden examples: run `plg eval seed {name}`")

    def wrap(evaluate: RowEvaluator) -> Any:
        async def scored(inputs: dict[str, Any], outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
            return {"results": await evaluate(inputs, outputs, reference_outputs)}
        scored.__name__ = getattr(evaluate, "__name__", "evaluate")
        return scored

    def wrap_summary(evaluate: SummaryEvaluator) -> Any:
        def scored(outputs: list[dict[str, Any]], reference_outputs: list[dict[str, Any]]) -> dict[str, Any]:
            return {"results": evaluate(outputs, reference_outputs)}
        scored.__name__ = evaluate.__name__
        return scored

    results = await aevaluate(
        target, data=examples, evaluators=[wrap(e) for e in row_evaluators],
        summary_evaluators=[wrap_summary(e) for e in summary_evaluators], client=client, metadata=metadata,
        experiment_prefix=f"{name}-{label}" if label else name, max_concurrency=concurrency,
    )
    by_example: dict[uuid.UUID, tuple[dict[str, Any], list[Metric]]] = {}
    async for row in results:
        scored = [metric(r.key, r.score if isinstance(r.score, (int, float)) else 0.0, r.comment or "")
                  for r in row["evaluation_results"]["results"]]
        by_example[row["example"].id] = (dict(row["run"].outputs or {}), scored)
    found = [by_example.get(example_id(g), ({}, [])) for g in golden]
    return [o for o, _ in found], [Row(id=g.id, metrics=m) for g, (_, m) in zip(golden, found)], results.experiment_name
