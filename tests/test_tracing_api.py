"""Tracing and the "view trace" link (issue #27).

Every run (a question, or the resume of an approval) is one LangSmith trace whose root run carries the run ID the
answer reports in `done`, with thread, user, intents, channel and git SHA as metadata; the graph's nodes, `Send()`
branches and tool calls are its children. Tenant PII is masked before anything is uploaded. Developers (the
`developers` setting) get the trace's URL for their own answers; nobody else does.

LangSmith is the third-party boundary: a real `langsmith.Client` built by plg (so with its masking) posts to a
recording HTTP session standing in for the LangSmith API.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from typing import Any

import pytest

from plg.config import REPO_ROOT
from plg.llm import ScriptedLLMClient, text, tool_call, turn
from tests.conftest import PROJECT_ID, TENANT_ID, USER, Api, LangSmithApi, SseStream, route

DEVELOPER = {"X-PLG-User": "S08"}
"""Kelvin Goh, Data Analyst: the POC's developer persona."""


QUESTION = "How many tenancies are active?"
SQL = "SELECT COUNT(*) AS active FROM tenancies WHERE status = 'Active'"


@pytest.fixture
def langsmith() -> LangSmithApi:
    return LangSmithApi()


@pytest.fixture
def api(make_api: Any, langsmith: LangSmithApi) -> Api:
    return make_api(tracer=langsmith.tracer(), developers="S08")


def data_answer(api: Api, llm: ScriptedLLMClient, headers: dict[str, str] = USER) -> tuple[str, SseStream]:
    route(llm, QUESTION, "data")
    llm.script_turns(
        "data", QUESTION,
        turn(tool_call("run_sql", plan="Count active tenancies.", sql=SQL, concepts=[])),
        turn(text("There are 1587 active tenancies.")),
    )
    llm.script("merge", QUESTION, "There are 1587 active tenancies.")
    thread = api.create_thread(headers)
    return thread, api.run(thread, QUESTION, headers)


def run_id(stream: SseStream) -> str:
    return str(stream.of_type("done")[0]["run_id"])


def metadata(run: dict[str, Any]) -> dict[str, Any]:
    return dict(run["extra"].get("metadata", {}))


def test_a_run_is_one_trace_with_thread_user_intents_channel_and_git_sha(
    api: Api, llm: ScriptedLLMClient, langsmith: LangSmithApi
) -> None:
    thread, stream = data_answer(api, llm)

    root = langsmith.root(run_id(stream))
    assert root.get("parent_run_id") is None
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
    meta = metadata(root)
    assert (meta["thread_id"], meta["user_id"], meta["channel"], meta["kind"]) == (thread, "S05", "api", "question")
    assert meta["user_role"] == "officer"
    assert meta["intents"] == ["data"]
    assert meta["git_sha"] == sha


def test_nodes_branches_and_tool_calls_are_children_of_the_run(
    api: Api, llm: ScriptedLLMClient, langsmith: LangSmithApi
) -> None:
    thread, stream = data_answer(api, llm)

    trace = run_id(stream)
    children = [r for r in langsmith.runs().values() if r.get("trace_id") == trace and str(r["id"]) != trace]
    names = {r["name"] for r in children}
    assert {"route", "data", "merge"} <= names  # graph nodes, `data` as a Send() branch
    (sql,) = [r for r in children if r["name"] == "run_sql"]
    assert sql["run_type"] == "tool"
    assert "tenancies" in json.dumps(sql["inputs"])
    assert all(metadata(r).get("thread_id") == thread for r in children)


def test_tenant_pii_is_masked_before_upload(api: Api, llm: ScriptedLLMClient, langsmith: LangSmithApi) -> None:
    question = "Devi Nair (S1234567D, +65 9391 3713, devi@nanyangmart.example.com) asked about her renewal."
    route(llm, question)
    llm.script("merge", question, "Devi Nair can renew; reach her on 9391 3713.")
    thread = api.create_thread()

    assert api.run(thread, question).text.startswith("Devi Nair")  # the officer still sees it

    uploaded = "\n".join(langsmith.raw)
    assert uploaded
    for pii in ("Devi Nair", "S1234567D", "9391 3713", "devi@nanyangmart.example.com"):
        assert pii not in uploaded
    assert "[tenant contact]" in uploaded and "[NRIC]" in uploaded


def test_a_resume_is_traced_as_its_own_run_on_the_thread(
    api: Api, llm: ScriptedLLMClient, langsmith: LangSmithApi
) -> None:
    officer = {"X-PLG-User": "S11"}
    question = "Classify feedback case FB-2025-00003 and route it."
    route(llm, question, "defect")
    llm.script_turns("defect", question, turn(tool_call(
        "classify_feedback", categories=[{"code": "PST", "confidence": 0.9}], rationale="Rats.", feedback="Rats.",
    )))
    llm.script("merge", question, "Here is the classification.")
    thread = api.create_thread(officer)
    asked = api.run(thread, question, officer)
    (action,) = asked.of_type("proposed_action")
    paused = langsmith.root(run_id(asked))
    assert metadata(paused)["interrupted"] is True
    assert paused["outputs"]["awaiting_approval"] == [f"{action['action_id']} v{action['version']}"]

    resumed = api.resume(thread, {"action_id": action["action_id"], "version": action["version"], "decision": "approve"}, officer)

    assert isinstance(resumed, SseStream)
    meta = metadata(langsmith.root(run_id(resumed)))
    assert (meta["thread_id"], meta["user_id"], meta["kind"]) == (thread, "S11", "resume")
    assert (meta["action_id"], meta["decision"]) == (action["action_id"], "approve")


def test_a_developer_gets_the_trace_url_of_their_answer(api: Api, llm: ScriptedLLMClient) -> None:
    thread, stream = data_answer(api, llm, DEVELOPER)
    run = run_id(stream)

    response = api.client.get(f"/threads/{thread}/runs/{run}/trace", headers=DEVELOPER)

    assert response.status_code == 200
    assert response.json()["url"].endswith(f"/o/{TENANT_ID}/projects/p/{PROJECT_ID}/r/{run}?poll=true")


def test_only_developers_see_trace_urls_and_only_for_their_own_answers(api: Api, llm: ScriptedLLMClient) -> None:
    thread, stream = data_answer(api, llm)
    run = run_id(stream)

    assert api.client.get(f"/threads/{thread}/runs/{run}/trace", headers=USER).status_code == 403
    assert api.client.get(f"/threads/{thread}/runs/{run}/trace", headers=DEVELOPER).status_code == 404
    mine = api.create_thread(DEVELOPER)
    assert api.client.get(f"/threads/{mine}/runs/{uuid.uuid4()}/trace", headers=DEVELOPER).status_code == 404


def test_personas_say_who_is_a_developer(api: Api) -> None:
    assert api.client.get("/me", headers=DEVELOPER).json()["developer"] is True
    assert api.client.get("/me", headers=USER).json()["developer"] is False
    developers = [p["staff_id"] for p in api.client.get("/personas").json() if p["developer"]]
    assert developers == ["S08"]


def test_without_tracing_there_is_no_trace_url(make_api: Any, llm: ScriptedLLMClient) -> None:
    api = make_api(developers="S08")
    thread, stream = data_answer(api, llm, DEVELOPER)

    response = api.client.get(f"/threads/{thread}/runs/{run_id(stream)}/trace", headers=DEVELOPER)

    assert response.status_code == 503


def test_the_cli_traces_its_runs_on_the_cli_channel(
    langsmith: LangSmithApi, llm: ScriptedLLMClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from plg import cli

    tracer = langsmith.tracer()
    monkeypatch.setattr(cli, "make_llm", lambda _settings: llm)
    monkeypatch.setattr(cli, "make_tracer", lambda _settings: tracer)
    route(llm, "hello")
    llm.script("merge", "hello", "Hello, officer.")

    result = CliRunner().invoke(cli.app, ["ask", "hello"])

    assert result.exit_code == 0, result.output
    roots = [r for r in langsmith.runs().values() if r.get("name") == "plg_run"]
    assert [metadata(r)["channel"] for r in roots] == ["cli"]
