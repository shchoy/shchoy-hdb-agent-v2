"""Top tasks and the task digest through plg-api (issue #22): an officer's open tasks from PLG Records ranked by
urgency × impact (a deterministic rules matrix), overdue tasks marked, each with the reasons for its place. The ranking
needs no Claude: `GET /tasks/digest` is tested directly. In a conversation the `tasks` specialist streams the ranking
(`tasks` event) and merge writes the rationale from it. Team leads may view their team's tasks; others only their own.

The records are poc-data's PLG Records, whose snapshot date (the tasks' "today") is 30 Sep 2026.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from plg import cli
from plg.llm import ScriptedLLMClient
from tests.conftest import USER, Api, route

BENJAMIN = {"X-PLG-User": "S12"}
"""Benjamin Ho, Estate Manager (West)."""
MARCUS = {"X-PLG-User": "S04"}
"""Marcus Lim, Estate Manager (East): leads the Estate Management officers (S06, S10)."""
NURUL = {"X-PLG-User": "S03"}
"""Nurul Huda Rahman, Senior Manager, Tenancy Management."""
DIRECTOR = {"X-PLG-User": "S01"}
LUCKY_STAR = "TSK-2026-0452"
"""Daniel Ong's (S06) follow-up of the Lucky Star Hair Studio subletting inspection, due 30 Jun 2026."""


def digest(api: Api, headers: dict[str, str], **params: Any) -> dict[str, Any]:
    response = api.client.get("/tasks/digest", params=params, headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def ids(found: dict[str, Any]) -> list[str]:
    return [t["task_id"] for t in found["tasks"]]


def test_my_top_5_tasks_are_ranked_by_urgency_times_impact(api: Api) -> None:
    found = digest(api, BENJAMIN)

    assert found["staff_id"] == "S12" and found["name"] == "Benjamin Ho"
    assert found["as_of"] == "2026-09-30"
    assert found["open_count"] == 27 and found["overdue_count"] == 21
    # Three overdue fire-safety follow-ups (overdue × high = 12), longest overdue first; then the oldest overdue task.
    assert ids(found) == ["TSK-2025-0160", "TSK-2026-0470", "TSK-2026-0938", "TSK-2025-0034", "TSK-2025-0066"]
    first = found["tasks"][0]
    assert first["rank"] == 1
    assert (first["urgency"], first["impact"], first["score"]) == ("overdue", "high", 12)
    assert first["overdue"] is True and first["days_overdue"] == 283
    assert "Safety-related" in first["reasons"]
    assert "Overdue by 283 days (due 21 Dec 2025)" in first["reasons"]


def test_impact_outweighs_a_lesser_overdue_task(api: Api) -> None:
    """Rent at risk raises impact: a high-value renewal due this week (3 × 3) outranks an overdue medium one (4 × 2)."""
    found = digest(api, USER, limit=10)

    assert ids(found)[:4] == ["TSK-2026-0183", "TSK-2026-0374", "TSK-2026-0501", "TSK-2026-0541"]
    fifth = found["tasks"][4]
    assert (fifth["urgency"], fifth["impact"], fifth["score"]) == ("this_week", "high", 9)
    assert fifth["overdue"] is False
    assert "TSK-2026-0194" not in ids(found)  # overdue, S$26,400 at risk: medium impact, score 8
    assert any(r.startswith("S$") and "rent at risk" in r for r in found["tasks"][0]["reasons"])


def test_tenants_affected_raise_impact(api: Api) -> None:
    found = digest(api, {"X-PLG-User": "S10"}, limit=1)

    (top,) = found["tasks"]
    assert top["task_id"] == "TSK-2026-0828"
    assert "11 tenants affected" in top["reasons"]


def test_the_lucky_star_subletting_follow_up_is_marked_overdue(api: Api) -> None:
    found = digest(api, MARCUS, staff_id="S06", limit=100)

    lucky = next(t for t in found["tasks"] if t["task_id"] == LUCKY_STAR)
    assert lucky["overdue"] is True and lucky["days_overdue"] == 92
    assert lucky["title"] == "Follow up Unauth Sublet at U-RH455-01-20"


def test_limit_is_capped_and_ranks_are_contiguous(api: Api) -> None:
    found = digest(api, USER, limit=500)

    assert len(found["tasks"]) == 50
    assert [t["rank"] for t in found["tasks"]] == list(range(1, 51))
    scores = [t["score"] for t in found["tasks"]]
    assert scores == sorted(scores, reverse=True)


def test_team_leads_view_their_teams_tasks_and_no_one_elses(api: Api) -> None:
    assert digest(api, NURUL, staff_id="S05")["staff_id"] == "S05"  # same department
    assert digest(api, DIRECTOR, staff_id="S12")["staff_id"] == "S12"  # directors see everyone
    for viewer, target in [(USER, "S12"), (NURUL, "S06"), (MARCUS, "S05"), (MARCUS, "S12"), ({"X-PLG-User": "S08"}, "S05")]:
        response = api.client.get("/tasks/digest", params={"staff_id": target}, headers=viewer)
        assert response.status_code == 403, (viewer, target)
    assert api.client.get("/tasks/digest", params={"staff_id": "S99"}, headers=DIRECTOR).status_code == 404
    assert api.client.get("/tasks/digest").status_code == 401


def test_team_lists_the_officers_whose_tasks_i_may_view(api: Api) -> None:
    def team(headers: dict[str, str]) -> list[str]:
        response = api.client.get("/tasks/team", headers=headers)
        assert response.status_code == 200
        return [p["staff_id"] for p in response.json()]

    assert team(USER) == ["S05"]
    assert team(MARCUS) == ["S04", "S06", "S10"]  # officers, not the other estate manager
    assert team(NURUL) == ["S03", "S05"]
    assert team(DIRECTOR)[0] == "S01" and len(team(DIRECTOR)) == 12


# ---------------------------------------------------------------- in a conversation

QUESTION = "What are my top 5 tasks this week and why?"


def test_asking_for_my_top_tasks_streams_the_ranking_and_merge_explains_it(
    api: Api, llm: ScriptedLLMClient
) -> None:
    route(llm, QUESTION, "tasks")
    llm.script("merge", QUESTION, "Start with the overdue fire-safety follow-ups.")

    stream = api.run(api.create_thread(BENJAMIN), QUESTION, BENJAMIN)

    (ranked,) = stream.of_type("tasks")
    assert ranked["staff_id"] == "S12"
    assert ids(ranked) == ["TSK-2025-0160", "TSK-2026-0470", "TSK-2026-0938", "TSK-2025-0034", "TSK-2025-0066"]
    assert stream.text == "Start with the overdue fire-safety follow-ups."
    system, _ = llm.streamed[-1]
    assert "TSK-2025-0160" in system and "Overdue by 283 days" in system
    assert "TSK-2026-0955" not in system  # only the top 5 reach merge
    assert "one short sentence per task" in system  # merge writes the rationale


def test_a_named_officers_tasks_follow_the_role_check(api: Api, llm: ScriptedLLMClient) -> None:
    question = "What are Daniel Ong's top 3 tasks?"
    route(llm, question, "tasks")
    llm.script("merge", question, "Daniel's top three tasks are ...")

    stream = api.run(api.create_thread(MARCUS), question, MARCUS)

    (ranked,) = stream.of_type("tasks")
    assert ranked["staff_id"] == "S06" and len(ranked["tasks"]) == 3


def test_an_officer_cannot_see_someone_elses_tasks_in_a_conversation(api: Api, llm: ScriptedLLMClient) -> None:
    question = "What are Benjamin Ho's top 5 tasks?"
    route(llm, question, "tasks")
    llm.script("merge", question, "You can only view your own tasks.")

    stream = api.run(api.create_thread(), question)

    assert stream.of_type("tasks") == []
    system, _ = llm.streamed[-1]
    assert "not allowed to view Benjamin Ho's tasks" in system
    assert "TSK-" not in system


# ---------------------------------------------------------------- plg digest (scheduled)


def test_plg_digest_prints_an_officers_top_tasks() -> None:
    result = CliRunner().invoke(cli.app, ["digest", "--user", "S12"])

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0].startswith("Top 5 of Benjamin Ho's (S12, Estate Manager (West)) 27 open tasks as of 30 Sep 2026")
    assert lines[1].startswith("1. OVERDUE TSK-2025-0160 Inspection Follow-up")
    assert "Overdue by 283 days (due 21 Dec 2025)" in lines[1]


def test_plg_digest_writes_every_officers_digest_to_a_file(tmp_path: Path) -> None:
    out = tmp_path / "digest.txt"

    result = CliRunner().invoke(cli.app, ["digest", "--out", str(out), "--limit", "100"])

    assert result.exit_code == 0, result.output
    text = out.read_text()
    assert "Daniel Ong's (S06" in text and f"OVERDUE {LUCKY_STAR}" in text
    assert "Tan Wei Ling" not in text  # no open tasks, no digest
    assert str(out) in result.stdout


def test_plg_digest_rejects_an_unknown_officer() -> None:
    result = CliRunner().invoke(cli.app, ["digest", "--user", "S99"])

    assert result.exit_code != 0


def test_a_first_name_names_a_colleague_only_when_it_is_theirs(api: Api, llm: ScriptedLLMClient) -> None:
    """"grace period" is not Grace Chua; "Daniel's" is Daniel Ong."""
    for question, expected in [("Is there a grace period on my top tasks?", "S04"), ("Show me Daniel's top tasks", "S06")]:
        route(llm, question, "tasks")
        llm.script("merge", question, "Here they are.")

        stream = api.run(api.create_thread(MARCUS), question, MARCUS)

        (ranked,) = stream.of_type("tasks")
        assert ranked["staff_id"] == expected, question
