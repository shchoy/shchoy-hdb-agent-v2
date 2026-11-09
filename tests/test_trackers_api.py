"""Data questions over the hand-maintained Excel trackers, through plg-api.

`plg sync` loads the poc-data trackers (sheets/*.xlsx) into DuckDB; the data agent queries them as `trackers.<table>`
next to PLG Records. Claude is scripted; the SQL it "writes" runs for real. Expected figures come from
poc-data/_report.md.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from plg.llm import ScriptedLLMClient, text, turn
from tests.conftest import Api
from tests.test_data_api import ask, sql_turn


@pytest.fixture
def trackers_api(make_api: Callable[..., Api], trackers_db: Path) -> Api:
    return make_api(trackers_db=trackers_db)


def rows(trace: Any) -> list[dict[str, Any]]:
    result = trace["result"]
    return [dict(zip(result["columns"], row, strict=True)) for row in result["sample"]]


def test_vacant_units_by_town_come_from_the_vacancy_report(trackers_api: Api, llm: ScriptedLLMClient) -> None:
    # _report.md question 9: 47 vacant units at 31 Aug 2026, excluding the 5 under tender. The report's merged
    # two-row header (Units › Total, Non-tenanted › Vacant / Under Tender) becomes one column name per column.
    question = "How many vacant units were there at 31 Aug 2026, by town, according to the vacancy report?"
    stream = ask(
        trackers_api, llm, question,
        sql_turn(
            "Vacant and under-tender units per town from the Aug 2026 vacancy report",
            "SELECT town, units_total, non_tenanted_vacant, non_tenanted_under_tender "
            "FROM trackers.vacancy_report_aug2026_summary ORDER BY town",
        ),
        sql_turn(
            "Totals",
            "SELECT SUM(non_tenanted_vacant) AS vacant, SUM(non_tenanted_under_tender) AS under_tender "
            "FROM trackers.vacancy_report_aug2026_summary",
        ),
        turn(text("47 vacant.")),
    )

    by_town, totals = stream.of_type("sql_trace")
    assert by_town["status"] == "ok", by_town["error"]
    assert len(rows(by_town)) == 6  # one row per town: the TOTAL row was all formulas and is not loaded
    assert rows(totals) == [{"vacant": 47, "under_tender": 5}]


def data_system(llm: ScriptedLLMClient) -> str:
    """The data agent's system prompt."""
    system, _ = next(r for r in llm.requests if any(t["name"] == "run_sql" for t in r[1]))
    return " ".join(b["text"] for b in system)


def test_formula_columns_are_not_trusted_but_computed_from_their_formula(
    trackers_api: Api, llm: ScriptedLLMClient
) -> None:
    # _report.md question 11: Golden Leaf Minimart owes S$22,672.00, 121 days, 4.0 months of rent. The tracker's
    # "Months of rent" is a formula with no saved value, so it is not loaded; the agent is shown the formula.
    question = "What does the arrears ageing tracker say Golden Leaf Minimart owes?"
    stream = ask(
        trackers_api, llm, question,
        sql_turn("Read the tracker's months of rent", (
            "SELECT months_of_rent FROM trackers.arrears_ageing_sep2026_data WHERE tenancy_id = 'TA-2024-00542'"
        )),
        sql_turn("Compute months of rent from the formula", (
            "SELECT tenancy_id, arrears_incl_gst, days_overdue, "
            "ROUND(arrears_incl_gst / (monthly_rent * 1.09), 1) AS months_of_rent "
            "FROM trackers.arrears_ageing_sep2026_data WHERE tenant_name LIKE 'Golden Leaf Minimart%'"
        )),
        turn(text("S$22,672.00, 121 days, 4.0 months.")),
    )

    unsaved, computed = stream.of_type("sql_trace")
    assert unsaved["status"] == "rejected" and "months_of_rent" in unsaved["error"]
    assert rows(computed) == [
        {"tenancy_id": "TA-2024-00542", "arrears_incl_gst": 22672.0, "days_overdue": 121, "months_of_rent": 4.0}
    ]
    system = data_system(llm)
    assert "months_of_rent (Months of rent) = arrears_incl_gst/(monthly_rent*1.09)" in system
    # Static check rows are kept as the preparer's notes, and summary sheets of formulas are not loaded.
    assert "Static check: 135 tenancies in arrears, total S$962,688.00." in system
    assert "Sheet Summary not loaded" in system


def test_officer_tabs_are_one_table_with_text_dates_read_day_first(trackers_api: Api, llm: ScriptedLLMClient) -> None:
    # One tab per officer, same header: one table, `sheet` naming the tab. Some due dates were typed as text
    # ('30/09/26'); they are dates like the rest, so date comparisons see every task.
    question = "Which of Nurul's and Daniel's tracker tasks are due by 30 Sep 2026?"
    stream = ask(
        trackers_api, llm, question,
        sql_turn("Two tasks, one with a typed date", (
            "SELECT task_id, sheet, due, due < DATE '2026-10-01' AS due_by_end_sept FROM trackers.officer_task_tracker "
            "WHERE task_id IN ('TSK-2026-0916', 'TSK-2026-0452') ORDER BY task_id"
        )),
        turn(text("Both.")),
    )

    (trace,) = stream.of_type("sql_trace")
    assert rows(trace) == [
        # _report.md question 24: the Lucky Star subletting follow-up, due 30 Jun 2026.
        {"task_id": "TSK-2026-0452", "sheet": "Daniel", "due": "2026-06-30", "due_by_end_sept": True},
        {"task_id": "TSK-2026-0916", "sheet": "Nurul", "due": "2026-09-30", "due_by_end_sept": True},
    ]
    assert "due: 65 date(s) typed as text (e.g. '30/09/26') read as day/month/year" in data_system(llm)


def test_tracker_rows_join_plg_records(trackers_api: Api, llm: ScriptedLLMClient) -> None:
    # _report.md question 13: NC-PI-1 has 2 bubble tea outlets. The trade-mix matrix is all formulas; its
    # Active Tenancies sheet is loaded and joins PLG Records on the tenancy ID.
    question = "How many bubble tea outlets are in NC-PI-1 per the trade mix analysis?"
    stream = ask(
        trackers_api, llm, question,
        sql_turn("Count bubble tea tenancies in NC-PI-1, checked against PLG Records", (
            "SELECT COUNT(*) AS outlets, COUNT(t.tenancy_id) AS in_records "
            "FROM trackers.trade_mix_analysis_by_nc_active_tenancies a "
            "LEFT JOIN tenancies t ON t.tenancy_id = a.tenancy_id WHERE a.nc = 'NC-PI-1' AND a.trade = 'Bubble Tea'"
        )),
        turn(text("2.")),
    )

    (trace,) = stream.of_type("sql_trace")
    assert rows(trace) == [{"outlets": 2, "in_records": 2}]


@pytest.mark.parametrize("sql", [
    "SELECT * FROM trackers._workbooks",
    "SELECT * FROM trackers.main.staff",
    "SELECT * FROM rec.trackers.vacancy_report_aug2026_summary",
])
def test_only_tracker_tables_are_readable(trackers_api: Api, llm: ScriptedLLMClient, sql: str) -> None:
    stream = ask(trackers_api, llm, f"Run {sql}", sql_turn("Try it", sql), turn(text("No.")))

    (trace,) = stream.of_type("sql_trace")
    assert trace["status"] == "rejected"
    assert "is not available" in trace["error"]


def test_without_trackers_the_data_agent_is_told_of_none(api: Api, llm: ScriptedLLMClient) -> None:
    question = "How many vacant units per the vacancy report?"
    stream = ask(api, llm, question, sql_turn("Try the tracker", (
        "SELECT SUM(non_tenanted_vacant) FROM trackers.vacancy_report_aug2026_summary"
    )), turn(text("No tracker.")))

    (trace,) = stream.of_type("sql_trace")
    assert trace["status"] == "rejected"
    assert "Excel trackers" not in data_system(llm)


def test_arrears_above_three_months_from_the_tracker_match_ground_truth(trackers_api: Api, llm: ScriptedLLMClient) -> None:
    # _report.md question 10: 22 tenancies owe more than 3 x rent x 1.09. Four owe exactly 3 months; the agent is
    # told to round the computed ratio before comparing, which keeps them out.
    question = "Per the arrears ageing tracker, which tenancies owe more than 3 months' rent?"
    stream = ask(
        trackers_api, llm, question,
        sql_turn("Months of rent from the tracker formula, over 3", (
            "SELECT COUNT(*) AS tenancies FROM trackers.arrears_ageing_sep2026_data "
            "WHERE ROUND(arrears_incl_gst / (monthly_rent * 1.09), 2) > 3"
        )),
        turn(text("22.")),
    )

    (trace,) = stream.of_type("sql_trace")
    assert rows(trace) == [{"tenancies": 22}]
    assert "round a computed ratio to 2 decimals before comparing" in data_system(llm)
