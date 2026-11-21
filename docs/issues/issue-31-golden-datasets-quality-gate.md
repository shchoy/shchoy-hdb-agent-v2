# Issue #31: Golden datasets and quality regression gate

## What was built

- **Golden datasets.** There are 11 datasets: one per node plus one end to end, 175 examples in total. They are built from the corpus ground truth:
  - the 28 sample questions in `_report.md` §5
  - `planned_conflicts` (C1–C6)
  - `submission_bundles_ground_truth` (20 bundles)
  - `data_quality_issues`
  - `key_entities`
  - the labelled cases in `feedback.json`
  - the generated glossary

  Every example has a stable ID, the staff member who asks it, a reference, its ground-truth source and a flag saying whether it is in the regression gate.
- **Seeding into LangSmith.** `plg eval seed` mirrors each dataset into the LangSmith dataset `plg-<name>`. It uploads through the PII-masking `tracing_client`. Example IDs are derived from the golden IDs, so a re-seed updates examples in place and removes ones the ground truth no longer has.
- **Evaluators for the POC targets.** Each dataset has a target:

  | Dataset | Metric | Target |
  |---|---|---|
  | route | intent accuracy | 90% |
  | knowledge | faithfulness, judged by Opus against the cited passages; an uncited answer scores 0 | 85% |
  | data | execution accuracy against known result values, column totals and row counts | 80% |
  | drafting | slot accuracy | 90% |
  | defect | macro-F1 | 85% |
  | doc_check | recall | 90% |
  | audit | recall of C1–C6 (duplicate and rule recall are reported alongside) | 80% |
  | glossary | correctness, judged by Opus | 90% |
  | guardrails | guarded | 100% |
  | tasks | correct digest | 90% (chosen here, not in the spec) |
  | e2e | correctness, judged by Opus | 80% (chosen here, not in the spec) |

- **`plg eval run`.**
  - Each example goes through a harness that builds the same graph `plg ask` uses, in a scratch directory. It has no memory and never approves an action.
  - The run is scored and compared with the target. It exits 1 when a target is missed.
  - By default each run is a LangSmith experiment (`aevaluate`). Its metadata records the model per tier, the rerank backend, the git SHA and a `--label`.
  - `--model tier=id` swaps a tier's model, so tiers and prompt changes can be compared.
  - `--offline` scores locally and uploads nothing.
  - For the route dataset, the run stops once the fan-out is known, so routing evals don't pay for answers.
- **Pytest regression gate.** `tests/evals/test_quality_gate.py` runs 31 gate cases with real Claude through the LangSmith pytest integration (`@pytest.mark.langsmith`, suite `plg-quality-gate`, masking client). It is opt-in (`PLG_EVALS=1`). A new CI job, `evals`, runs it after the `api` job.

## How it fits

This is spec #1's testing item 4 ("Model quality: LangSmith evaluations"), at the Observability & evaluation stage (user stories 111–112). Existing tests check behaviour with a scripted Claude. These evals measure how good the real models and prompts are. They sit on the same seams: `LLMClient` (the Opus judge goes through it), `stream_run` events (the harness reads the same events the SSE stream carries) and `run_audit`.

Ontology validity and memory isolation are still covered by the existing deterministic suites (`test_ontology_artefacts`, `test_make_ontology`, `test_memory_api`). They have no eval dataset of their own.

## Modules

| Path | New/modified | Role |
|---|---|---|
| `src/plg/evals/golden.py` | new | Golden datasets built from the ground truth; the `DATASETS` registry |
| `src/plg/evals/harness.py` | new | Eval target: one graph run → `Outcome`; the corpus audit → path pairs |
| `src/plg/evals/evaluators.py` | new | `TARGETS`, row and summary evaluators, the Opus `Judge` |
| `src/plg/evals/runner.py` | new | `seed` into LangSmith; `run` offline or as an `aevaluate` experiment → `EvalReport` |
| `src/plg/cli.py` | modified | `plg eval list / seed / run` |
| `tests/test_evals.py` | new | Offline tests at the CLI seam (scripted Claude, stand-in LangSmith) |
| `tests/evals/test_quality_gate.py` | new | Regression gate with real Claude through the LangSmith pytest plugin |
| `.github/workflows/ci.yml` | modified | `evals` job |
| `CLAUDE.md`, `START.md` | modified | Map and how-to |

## Workflow

```
poc-data/_report.md §5 + _master/*.json + glossary
        │ golden.py (DATASETS)
        ▼
plg eval seed ──tracing_client (PII masked)──▶ LangSmith datasets plg-<name>
plg eval run ─▶ runner.run ─▶ Harness.ask ─▶ build_graph + stream_run (real Claude via LLMClient)
                   │                 └─ events → Outcome (intents, answer, citations, sql, draft, …)
                   │          Harness.audit ─▶ run_audit (graph copy) → conflict / duplicate pairs
                   ├─ evaluators (deterministic + Judge: Opus via LLMClient)
                   ├─ aevaluate experiment (metadata: models, git SHA, label) ─▶ LangSmith
                   └─ EvalReport vs TARGETS → PASS / FAIL (exit 1)
pytest tests/evals (PLG_EVALS=1) ─▶ same harness + evaluators, gate subset ─▶ LangSmith test suite plg-quality-gate
```

## Status and next steps

- **No real-Claude scores yet.** The Anthropic account had no credit, so nothing has been measured. The LangSmith seeding and experiment path was smoke-tested: dataset `plg-route` was seeded, and experiment `route-smoke-…` ran but failed on credit. Once credit is added:
  1. Run `plg eval seed`.
  2. Run `plg eval run`.
  3. Tune any references that turn out to be brittle.
- **Add CI secrets.** Add `ANTHROPIC_API_KEY` and `LANGSMITH_API_KEY` as repository secrets to turn the gate on. Without them its cases are skipped.
- **Gate index.** The gate asks over the offline hashing-embedder index, so its retrieval is weaker than in the full experiments.
- **Doc-check references.** For 3 bundles the reference adds `INS:expired` to the ground truth, following `KNOWN_GT_DEVIATIONS`.
