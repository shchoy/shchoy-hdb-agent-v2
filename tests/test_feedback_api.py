"""Answer feedback and curation through plg-api (issue #26).

An officer gives 👍/👎 (and corrections) on an answer: the feedback is recorded and sent to LangSmith against the
run's ID, and a 👎 run joins the review annotation queue. What the feedback would teach the team (a question → SQL
pair, a corrected answer, a team fact) waits in `pending_review` until a curator approves it; approved question →
SQL pairs are shown to the data agent as few-shot examples for similar questions.

LangSmith is the third-party boundary: a recording stand-in for its Client is passed to the app.
"""

from __future__ import annotations

from typing import Any

import pytest

from plg.llm import ScriptedLLMClient, text, tool_call, turn
from tests.conftest import USER, Api, route

ANALYST = {"X-PLG-User": "S08"}
"""Kelvin Goh, Data Analyst: curates question → SQL examples."""
LEAD = {"X-PLG-User": "S03"}
"""Nurul Huda Rahman, Senior Manager: a team lead, curates everything."""
OFFICER = {"X-PLG-User": "S06"}
"""Daniel Ong, Property Officer: not a curator."""

QUESTION = "How many tenancies are active?"
SQL = "SELECT COUNT(*) AS active FROM tenancies WHERE status = 'Active'"


class FakeLangSmith:
    """Records what the app sends to LangSmith, as its Client would receive it."""

    def __init__(self) -> None:
        self.feedback: list[dict[str, Any]] = []
        self.queues: dict[str, str] = {}
        self.queued: list[tuple[str, list[str]]] = []

    def create_feedback(self, run_id: str, key: str, **kwargs: Any) -> None:
        self.feedback.append({"run_id": str(run_id), "key": key, **kwargs})

    def list_annotation_queues(self, *, name: str | None = None, **_: Any) -> list[Any]:
        return [type("Queue", (), {"id": qid, "name": n})() for n, qid in self.queues.items() if n == name]

    def create_annotation_queue(self, *, name: str, **_: Any) -> Any:
        self.queues[name] = f"queue-{len(self.queues) + 1}"
        return type("Queue", (), {"id": self.queues[name], "name": name})()

    def add_runs_to_annotation_queue(self, queue_id: str, *, run_ids: list[str], **_: Any) -> None:
        self.queued.append((str(queue_id), [str(r) for r in run_ids]))


@pytest.fixture
def langsmith() -> FakeLangSmith:
    return FakeLangSmith()


@pytest.fixture
def api(make_api: Any, langsmith: FakeLangSmith) -> Api:
    return make_api(langsmith=langsmith)


def data_answer(api: Api, llm: ScriptedLLMClient, question: str = QUESTION, sql: str = SQL) -> tuple[str, str]:
    """Ask a data question whose query runs; the thread and the run ID of its answer."""
    route(llm, question, "data")
    llm.script_turns(
        "data", question,
        turn(tool_call("run_sql", plan="Count active tenancies.", sql=sql, concepts=[])),
        turn(text("There are 1587 active tenancies.")),
    )
    llm.script("merge", question, "There are 1587 active tenancies.")
    thread = api.create_thread()
    stream = api.run(thread, question)
    return thread, str(stream.of_type("done")[0]["run_id"])


def feedback(api: Api, body: dict[str, Any], headers: dict[str, str] | None = None) -> Any:
    return api.client.post("/feedback", json=body, headers=headers or USER)


def test_thumbs_up_on_a_data_answer_is_sent_to_langsmith_and_proposes_its_sql(
    api: Api, llm: ScriptedLLMClient, langsmith: FakeLangSmith
) -> None:
    thread, run_id = data_answer(api, llm)

    response = feedback(api, {"thread_id": thread, "run_id": run_id, "score": "up"})

    assert response.status_code == 201
    receipt = response.json()
    assert receipt["forwarded"] is True and receipt["queued"] is False
    assert langsmith.feedback == [{"run_id": run_id, "key": "user_score", "score": 1, "comment": None}]
    [proposal] = receipt["proposals"]
    assert proposal["action_type"] == "approve_sql_example"
    assert proposal["status"] == "pending"
    assert proposal["payload"]["question"] == QUESTION
    assert proposal["payload"]["sql"] == SQL
    assert langsmith.queued == []


def test_thumbs_down_joins_the_review_queue_and_proposes_the_correction_and_team_fact(
    api: Api, llm: ScriptedLLMClient, langsmith: FakeLangSmith
) -> None:
    thread, run_id = data_answer(api, llm)

    receipt = feedback(api, {
        "thread_id": thread, "run_id": run_id, "score": "down", "comment": "Wrong scope.",
        "correction": "Count only tenancies with an unexpired term: 1,587.",
        "team_fact": "Tenancy Management counts Pending Commencement tenancies as active. Call 9123 4567.",
    }).json()

    assert receipt["queued"] is True
    assert langsmith.queued == [("queue-1", [run_id])]
    assert list(langsmith.queues) == ["PLG thumbs-down review"]
    [sent] = langsmith.feedback
    assert (sent["score"], sent["comment"]) == (0, "Wrong scope.")
    assert sent["correction"] == {"answer": "Count only tenancies with an unexpired term: 1,587."}
    by_type = {p["action_type"]: p for p in receipt["proposals"]}
    assert set(by_type) == {"approve_example", "approve_team_fact"}  # a 👎 proposes no SQL example
    example = by_type["approve_example"]["payload"]
    assert example["answer"] == "Count only tenancies with an unexpired term: 1,587."
    assert example["original"] == "There are 1587 active tenancies."
    fact = by_type["approve_team_fact"]
    assert fact["payload"]["fact"] == "Tenancy Management counts Pending Commencement tenancies as active. Call [phone]."
    assert "S05" not in fact["approvers"] and {"S01", "S03", "S04"} <= set(fact["approvers"])
    assert "S08" not in fact["approvers"]  # analysts curate SQL examples only


def test_feedback_on_someone_elses_answer_or_an_unknown_run_is_404(api: Api, llm: ScriptedLLMClient) -> None:
    thread, run_id = data_answer(api, llm)

    assert feedback(api, {"thread_id": thread, "run_id": run_id, "score": "up"}, OFFICER).status_code == 404
    assert feedback(api, {"thread_id": thread, "run_id": "not-a-run", "score": "up"}).status_code == 404


def test_without_langsmith_feedback_is_still_recorded(make_api: Any, llm: ScriptedLLMClient, monkeypatch: Any) -> None:
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    api = make_api()
    thread, run_id = data_answer(api, llm)

    receipt = feedback(api, {"thread_id": thread, "run_id": run_id, "score": "down"}).json()

    assert (receipt["forwarded"], receipt["queued"], receipt["proposals"]) == (False, False, [])


def queue(api: Api, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = api.client.get("/curation", headers=headers)
    assert response.status_code == 200
    return list(response.json())


def decide(api: Api, proposal: dict[str, Any], headers: dict[str, str], decision: str = "approve", **body: Any) -> Any:
    return api.client.post(
        "/curation/decide", headers=headers,
        json={"action_id": proposal["action_id"], "version": proposal["version"], "decision": decision, **body},
    )


def sql_proposal(api: Api, llm: ScriptedLLMClient, question: str = QUESTION, sql: str = SQL) -> dict[str, Any]:
    thread, run_id = data_answer(api, llm, question, sql)
    [proposal] = feedback(api, {"thread_id": thread, "run_id": run_id, "score": "up"}).json()["proposals"]
    return dict(proposal)


def test_curators_see_pending_proposals_and_other_officers_dont(api: Api, llm: ScriptedLLMClient) -> None:
    proposal = sql_proposal(api, llm)

    assert [p["action_id"] for p in queue(api, ANALYST)] == [proposal["action_id"]]
    assert [p["action_id"] for p in queue(api, LEAD)] == [proposal["action_id"]]
    assert queue(api, OFFICER) == []
    assert [p["action_id"] for p in queue(api, USER)] == [proposal["action_id"]]  # the proposer, to withdraw it
    assert decide(api, proposal, OFFICER).status_code == 404


def test_only_a_curator_approves_and_the_decision_is_audited(api: Api, llm: ScriptedLLMClient) -> None:
    proposal = sql_proposal(api, llm)

    assert decide(api, proposal, USER).status_code == 403  # the proposer can't approve their own
    approved = decide(api, proposal, ANALYST)

    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert queue(api, ANALYST) == []
    assert decide(api, proposal, LEAD).status_code == 409  # no longer pending
    [entry] = api.client.get("/audit", headers=ANALYST).json()
    assert (entry["action_type"], entry["decision"], entry["approver"]) == ("approve_sql_example", "approve", "S08")
    assert entry["run_id"] == proposal["payload"]["run_id"]


def test_a_curator_can_edit_before_approving_and_the_proposer_can_withdraw(api: Api, llm: ScriptedLLMClient) -> None:
    proposal = sql_proposal(api, llm)
    better = "SELECT COUNT(*) AS active FROM tenancies WHERE status IN ('Active', 'Renewed')"

    assert decide(api, proposal, LEAD, "edit", edits={"plan": "x"}).status_code == 422
    assert decide(api, proposal, LEAD, "edit", edits={"sql": "DELETE FROM tenancies"}).status_code == 422
    edited = decide(api, proposal, LEAD, "edit", edits={"sql": better}).json()
    assert (edited["version"], edited["payload"]["sql"]) == (2, better)

    other = sql_proposal(api, llm, "How many tenancies have expired?", "SELECT COUNT(*) FROM tenancies WHERE status = 'Expired'")
    assert decide(api, other, USER, "reject").status_code == 422  # a rejection needs a reason
    withdrawn = decide(api, other, USER, "reject", reason="Asked the wrong thing.").json()
    assert withdrawn["status"] == "rejected"
    assert queue(api, LEAD) == []


def data_system_prompts(llm: ScriptedLLMClient) -> str:
    """Everything the data agent's system prompts said in the requests recorded."""
    return "\n".join(
        str(b.get("text", "")) for system, tools in llm.requests if any(t.get("name") == "run_sql" for t in tools)
        for b in system
    )


def test_an_approved_question_to_sql_pair_is_a_few_shot_example_for_similar_questions(
    api: Api, llm: ScriptedLLMClient
) -> None:
    verified = "SELECT COUNT(*) AS active FROM tenancies WHERE status = 'Active' AND tenancy_id LIKE 'TEN-%'"
    proposal = sql_proposal(api, llm, sql=verified)
    llm.requests.clear()
    data_answer(api, llm, "How many active tenancies are there?")
    assert verified not in data_system_prompts(llm)  # pending: not used yet

    decide(api, proposal, ANALYST)
    llm.requests.clear()
    data_answer(api, llm, "How many active tenancies are there?")

    prompt = data_system_prompts(llm)
    assert verified in prompt
    assert QUESTION in prompt


def test_approved_team_facts_and_corrections_reach_every_officer_as_guidance(api: Api, llm: ScriptedLLMClient) -> None:
    thread, run_id = data_answer(api, llm)
    proposals = feedback(api, {
        "thread_id": thread, "run_id": run_id, "score": "down",
        "correction": "Active means status Active only; Renewed tenancies are counted under their new term.",
        "team_fact": "Tenancy Management reports active tenancies as at month end.",
    }).json()["proposals"]
    later = "What does active tenancy mean?"

    def ask() -> None:
        route(llm, later)
        llm.script("merge", later, "It means a tenancy in force.")
        api.run(api.create_thread(OFFICER), later, OFFICER)

    ask()
    assert "month end" not in llm.streamed[-1].system  # still pending review

    for proposal in proposals:
        assert decide(api, proposal, LEAD).status_code == 200
    ask()

    system = llm.streamed[-1].system
    assert "Tenancy Management reports active tenancies as at month end." in system
    assert "Renewed tenancies are counted under their new term." in system


def test_a_thread_lists_its_answered_turns_by_run_id(api: Api, llm: ScriptedLLMClient) -> None:
    thread, run_id = data_answer(api, llm)

    [answered] = api.client.get(f"/threads/{thread}", headers=USER).json()["turns"]

    assert (answered["run_id"], answered["message_index"], answered["sql"]) == (run_id, 1, SQL)


def test_a_curator_never_approves_their_own_proposal_even_with_no_other_curator(
    api: Api, llm: ScriptedLLMClient
) -> None:
    state = api.client.app.state  # type: ignore[attr-defined]
    state.personas = {k: v for k, v in state.personas.items() if k == "S03"}  # the only curator left is the proposer
    route(llm, QUESTION, "data")
    llm.script_turns("data", QUESTION, turn(tool_call("run_sql", plan="Count.", sql=SQL, concepts=[])), turn(text("1587.")))
    llm.script("merge", QUESTION, "1587.")
    thread = api.create_thread(LEAD)
    run_id = api.run(thread, QUESTION, LEAD).of_type("done")[0]["run_id"]
    [proposal] = feedback(api, {"thread_id": thread, "run_id": run_id, "score": "up"}, LEAD).json()["proposals"]
    assert proposal["approvers"] == []

    assert decide(api, proposal, LEAD).status_code == 403


def test_a_rejected_sql_pair_can_be_proposed_again(api: Api, llm: ScriptedLLMClient) -> None:
    proposal = sql_proposal(api, llm)
    decide(api, proposal, ANALYST, "reject", reason="Wrong table.")

    again = sql_proposal(api, llm)

    assert again["status"] == "pending" and again["action_id"] != proposal["action_id"]
    assert [p["action_id"] for p in queue(api, ANALYST)] == [again["action_id"]]
    thread, run_id = data_answer(api, llm)
    assert feedback(api, {"thread_id": thread, "run_id": run_id, "score": "up"}).json()["proposals"] == []  # still pending
