"""Data questions through plg-api: the router sends numeric questions to the data agent, which plans, queries PLG
Records through the SQL validator and explains the result; every query reaches the client as an `sql_trace` event.

Claude is scripted; the SQL it "writes" runs for real against poc-data/plg_records.db. Expected figures come from
the ground truth in poc-data/_master and the business glossary.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest
import yaml

from plg.config import REPO_ROOT, Settings
from plg.llm import ScriptedLLMClient, text, tool_call, turn
from tests.conftest import Api, route

MASTER = REPO_ROOT / "poc-data" / "_master"
RECORDS = Settings().records_db

VACANT_QUESTION = "Why does the QBR say 52 vacant and the monthly report 47 at 31 Aug 2026?"
ARREARS_QUESTION = "Which tenancies have arrears above 3 months' rent?"
GOLDEN_LEAF_QUESTION = "How much does Golden Leaf Minimart owe in arrears?"

BINDINGS = yaml.safe_load((REPO_ROOT / "ontology" / "semantic.yaml").read_text())["bindings"]


def binding(term: str) -> str:
    return str(next(b["sql"] for b in BINDINGS if term in b["concepts"]))


def count_of(term: str) -> str:
    """SELECT COUNT(*) over a glossary binding, as the agent builds it after get_definition."""
    return f"SELECT COUNT(*) AS vacant_units FROM ({binding(term)})"


def arrears_over(months: float) -> str:
    sql = binding("plg:Arrears_v1")
    return f"SELECT tenancy_id, tenant_name, arrears, days_overdue, months_of_rent FROM ({sql}) WHERE months_of_rent > {months}"


def tool_results(llm: ScriptedLLMClient) -> list[str]:
    """Every tool result the data agent was shown, in order."""
    last = max((m for m in llm.sent if any(isinstance(x["content"], list) for x in m)), key=len)
    return [
        str(b["content"]) for m in last if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"] if b["type"] == "tool_result"
    ]


def ask(api: Api, llm: ScriptedLLMClient, question: str, *turns: Any, answer: str = "Done.") -> Any:
    route(llm, question, "data")
    llm.script_turns("data", question, *turns)
    llm.script("merge", question, answer)
    return api.run(api.create_thread(), question)


def sql_turn(plan: str, sql: str, concepts: list[str] | None = None, as_of: str | None = None) -> Any:
    args: dict[str, Any] = {"plan": plan, "sql": sql, "concepts": concepts or []}
    if as_of:
        args["as_of"] = as_of
    return turn(tool_call("run_sql", **args))


def test_vacancy_47_vs_52_is_explained_by_the_definition_change(api: Api, llm: ScriptedLLMClient) -> None:
    explanation = (
        "On 2026-08-31, 47 units were vacant under Vacant v2 (effective 2026-04-15, excluding units under tender). "
        "The QBR's 52 follows Vacant v1, which counts the 5 units under tender as vacant."
    )
    stream = ask(
        api, llm, VACANT_QUESTION,
        turn(tool_call("get_definition", concept="plg:Vacant", as_of="2026-08-31"),
             tool_call("get_definition", concept="plg:Vacant", version=1)),
        sql_turn("Count vacant units under the definition in force", count_of("plg:Vacant_v2"), ["plg:Vacant_v2"], "2026-08-31"),
        sql_turn("Count them under the superseded definition", count_of("plg:Vacant_v1"), ["plg:Vacant_v1"], "2026-08-31"),
        turn(text(explanation)),
        answer="47 vacant under Vacant v2; the QBR's 52 follows the earlier definition.",
    )

    traces = stream.of_type("sql_trace")
    assert [t["status"] for t in traces] == ["ok", "ok"]
    assert [t["result"]["sample"] for t in traces] == [[[47]], [[52]]]  # type: ignore[index]
    v2, v1 = (t["concepts"][0] for t in traces)  # type: ignore[index]
    assert (v2["id"], v2["version"], v2["effective_from"]) == ("plg:Vacant_v2", 2, "2026-04-15")
    assert (v1["id"], v1["version"], v1["effective_to"]) == ("plg:Vacant_v1", 1, "2026-04-14")
    assert all(t["as_of"] == "2026-08-31" and t["plan"] and t["sql"] for t in traces)
    assert traces[-1]["explanation"] == explanation
    assert [e["node"] for e in stream.of_type("node") if e["status"] == "started"] == ["route", "data", "merge"]
    assert stream.of_type("done") and not stream.of_type("error")
    # The definition in force on that date, and the superseded one, were put in front of the agent.
    shown = "\n".join(tool_results(llm))
    assert "plg:Vacant_v2 (Vacant unit), current" in shown
    assert "including units under tender" in shown


def test_get_definition_picks_the_version_in_force_on_the_date(api: Api, llm: ScriptedLLMClient) -> None:
    question = "How many vacant units were there on 1 March 2026?"
    ask(
        api, llm, question,
        turn(tool_call("get_definition", concept="vacant", as_of="2026-03-01")),
        turn(text("Under Vacant v1 ...")),
    )
    assert "plg:Vacant_v1 (Vacant unit), superseded, in force since before records began to 2026-04-14" in tool_results(llm)[0]


def test_arrears_above_three_months_match_ground_truth(api: Api, llm: ScriptedLLMClient) -> None:
    truth = {a["tenancy_id"]: a for a in json.loads((MASTER / "arrears.json").read_text()) if a["months_of_rent"] > 3}

    stream = ask(
        api, llm, ARREARS_QUESTION,
        sql_turn("Arrears per tenancy, over 3 months of rent", arrears_over(3), ["plg:Arrears_v1", "plg:MonthsOfArrears_v1"]),
        turn(text("Tenancies above 3 months")),
    )

    (trace,) = stream.of_type("sql_trace")
    assert trace["status"] == "ok"
    assert trace["result"]["row_count"] == len(truth)  # type: ignore[index]
    assert {c["id"] for c in trace["concepts"]} == {"plg:Arrears_v1", "plg:MonthsOfArrears_v1"}  # type: ignore[attr-defined]
    shown = tool_results(llm)[0]
    for tenancy_id in truth:
        assert tenancy_id in shown


def test_golden_leaf_arrears_match_ground_truth(api: Api, llm: ScriptedLLMClient) -> None:
    truth = next(a for a in json.loads((MASTER / "arrears.json").read_text()) if a["tenancy_id"] == "TA-2024-00542")
    sql = arrears_over(0).replace("WHERE months_of_rent > 0", "WHERE tenant_name LIKE 'Golden Leaf Minimart%'")

    stream = ask(api, llm, GOLDEN_LEAF_QUESTION, sql_turn("Arrears of Golden Leaf Minimart", sql, ["plg:Arrears_v1"]), turn(text("x")))

    (trace,) = stream.of_type("sql_trace")
    row = dict(zip(trace["result"]["columns"], trace["result"]["sample"][0], strict=True))  # type: ignore[index]
    assert (row["tenancy_id"], row["arrears"], row["days_overdue"], row["months_of_rent"]) == (
        truth["tenancy_id"], truth["amount"], truth["days_overdue"], truth["months_of_rent"],
    )
    assert (truth["amount"], truth["days_overdue"], truth["months_of_rent"]) == (22672.0, 121, 4.0)


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("DELETE FROM tenancies", "Only read-only SELECT"),
        ("UPDATE units SET status = 'Vacant'", "Only read-only SELECT"),
        ("DROP TABLE units", "Only read-only SELECT"),
        ("INSERT INTO towns VALUES ('XX', 'x', 'East', 'x', 'S01')", "Only read-only SELECT"),
        ("ATTACH 'other.db' AS other", "Only read-only SELECT"),
        ("COPY units TO '/tmp/units.csv'", "Only read-only SELECT"),
        ("SELECT 1; DELETE FROM units", "Only read-only SELECT"),
        ("SELECT 1; SELECT 2", "exactly one SELECT"),
        ("SELECT * FROM staff", "Table staff is not available"),
        ("SELECT * FROM sqlite_master", "not available"),
        ("SELECT * FROM duckdb_settings()", "Table functions are not allowed"),
        ("SELECT * FROM read_csv('/etc/hosts')", "Table functions are not allowed"),
        ("SELECT * FROM other.main.units", "not available"),
        ("SELECT no_such_column FROM units", "does not plan"),
    ],
)
def test_the_validator_rejects_unsafe_sql_and_the_data_is_untouched(
    api: Api, llm: ScriptedLLMClient, sql: str, reason: str
) -> None:
    question = f"Run this: {sql}"
    before = _fingerprint()

    stream = ask(api, llm, question, sql_turn("Try it", sql), turn(text("That was rejected.")))

    (trace,) = stream.of_type("sql_trace")
    assert trace["status"] == "rejected"
    assert reason in str(trace["error"])
    assert trace["result"] is None
    assert tool_results(llm)[0].startswith("Rejected: ")
    assert _fingerprint() == before


def test_a_rejected_query_can_be_corrected_in_the_same_run(api: Api, llm: ScriptedLLMClient) -> None:
    stream = ask(
        api, llm, "Clear the vacant units",
        sql_turn("Remove them", "DELETE FROM units WHERE status = 'Vacant'"),
        sql_turn("Count them instead", "SELECT COUNT(*) AS n FROM units WHERE status = 'Vacant'"),
        turn(text("There are 47.")),
    )

    assert [t["status"] for t in stream.of_type("sql_trace")] == ["rejected", "ok"]
    assert stream.of_type("sql_trace")[1]["result"]["sample"] == [[47]]  # type: ignore[index]
    assert [e["seq"] for e in stream.events] == sorted(e["seq"] for e in stream.events)  # type: ignore[type-var]


def test_an_unknown_glossary_term_is_rejected(api: Api, llm: ScriptedLLMClient) -> None:
    stream = ask(
        api, llm, "How many gizmos?", sql_turn("Count", "SELECT COUNT(*) FROM units", ["plg:Gizmo_v1"]), turn(text("x"))
    )
    (trace,) = stream.of_type("sql_trace")
    assert trace["status"] == "rejected"
    assert "not a glossary term" in str(trace["error"])


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT tenant_id, name FROM tenants WHERE brn = '201754388R'", "T-10514"),
        ("SELECT tenant_id FROM tenants WHERE tenant_id = 'T-19807'", "share business registration number"),
        ("SELECT AVG(monthly_rent) AS avg_rent FROM tenancies", "TA-2022-00400"),
        ("SELECT tenancy_id, monthly_rent FROM tenancies ORDER BY monthly_rent DESC LIMIT 1", "S$63,100"),
        ("SELECT MAX(inspection_date) AS latest FROM inspections", "INSP-2025-0125"),
        ("SELECT inspection_id FROM inspections WHERE inspection_date > '2026-12-31'", "2099-10-18"),
        ("SELECT * FROM payments WHERE payment_id = 'PAY-00001235'", "PAY-00001235"),
        ("SELECT SUM(amount) AS received FROM payments", "PAY-00001235"),
    ],
)
def test_known_data_quality_issues_are_warned_about(api: Api, llm: ScriptedLLMClient, sql: str, expected: str) -> None:
    stream = ask(api, llm, f"Check: {sql}", sql_turn("Look", sql), turn(text("See the warning.")))

    (trace,) = stream.of_type("sql_trace")
    assert trace["status"] == "ok"
    assert any(expected in w for w in trace["warnings"]), trace["warnings"]  # type: ignore[attr-defined]
    assert "DATA QUALITY WARNING" in tool_results(llm)[0]


def test_a_query_that_hits_no_known_issue_has_no_warnings(api: Api, llm: ScriptedLLMClient) -> None:
    stream = ask(api, llm, "Count towns", sql_turn("Count", "SELECT COUNT(*) FROM towns"), turn(text("6")))
    assert stream.of_type("sql_trace")[0]["warnings"] == []


def test_a_data_answer_without_a_successful_query_is_not_a_sourced_answer(api: Api, llm: ScriptedLLMClient) -> None:
    question = "Total rent of everyone?"
    route(llm, question, "data")
    llm.script_turns("data", question, sql_turn("Try", "DROP TABLE tenancies"), turn(text("I could not query that.")))

    stream = api.run(api.create_thread(), question)

    assert stream.of_type("sql_trace")[0]["status"] == "rejected"
    assert "don't cover this question" in stream.text  # fixed answer; merge made no Claude call


def _fingerprint() -> list[int]:
    con = sqlite3.connect(f"file:{RECORDS}?mode=ro", uri=True)
    try:
        return [con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("units", "tenancies", "towns", "tenants")]
    finally:
        con.close()
