"""`defect_flow`: the subgraph behind the `defect` specialist. classify (Haiku, with what PLG Records hold about a
feedback case the question names) → propose_ticket (maintenance defects only). Raising the ticket is only proposed:
it waits for the officer at the parent graph's `approval`."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from plg.actions import tickets
from plg.actions.model import ProposedAction
from plg.defects.classify import Classification, classify
from plg.defects.taxonomy import Taxonomy
from plg.entities.ids import find_ids, is_valid_id
from plg.identity import UserCtx
from plg.llm import LLMClient


class FeedbackCase(TypedDict):
    feedback_id: str
    unit_id: str
    description: str


class DefectInput(TypedDict, total=False):
    question: str
    user: UserCtx


class DefectOutput(TypedDict, total=False):
    classification: Classification
    summary: str
    """The specialist's finding, for merge."""
    proposed_actions: list[ProposedAction]


class DefectState(DefectInput, DefectOutput, total=False):
    case: FeedbackCase | None
    feedback: str
    """The feedback as given, without the officer's request."""


DefectFlow = CompiledStateGraph[DefectState, Any, DefectInput, DefectOutput]


def build_defect_flow(llm: LLMClient, taxonomy: Taxonomy, records_db: Path) -> DefectFlow:
    async def classify_feedback(state: DefectState) -> DefectState:
        case = feedback_case(records_db, state["question"])
        context = f"Feedback case {case['feedback_id']} as received (unit {case['unit_id']}): {case['description']}" if case else ""
        found, feedback = await classify(llm, taxonomy, state["question"], context)
        return {"classification": found, "feedback": feedback, "case": case, "summary": summary(found), "proposed_actions": []}

    def propose_ticket(state: DefectState) -> DefectState:
        found, case, user = state["classification"], state.get("case"), state["user"]
        units = [i for i in find_ids(state["question"]) if is_valid_id("Unit", i)]
        action = tickets.propose_ticket(
            found,
            description=case["description"] if case else state["feedback"],
            feedback_id=case["feedback_id"] if case else tickets.new_feedback_id(),
            unit_id=case["unit_id"] if case else next(iter(units), None),
            owner=user.staff_id,
        )
        return {"proposed_actions": [action], "summary": state["summary"] + PROPOSED.format(team=found.team)}

    def ticketed(state: DefectState) -> str:
        return "propose_ticket" if state["classification"].is_defect and state.get("user") else END

    graph = StateGraph(DefectState, input_schema=DefectInput, output_schema=DefectOutput)
    graph.add_node("classify_feedback", classify_feedback)
    graph.add_node("propose_ticket", propose_ticket)
    graph.add_edge(START, "classify_feedback")
    graph.add_conditional_edges("classify_feedback", ticketed, ["propose_ticket", END])
    graph.add_edge("propose_ticket", END)
    return graph.compile()


PROPOSED = "\nAn i-EMS ticket for {team} has been prepared and waits for the officer's approval; nothing is raised until then."


def summary(found: Classification) -> str:
    lines = [
        f"Category: {found.category} ({found.category_code}); severity {found.severity}; team {found.team}"
        + (f"; vendor {found.vendor}" if found.vendor else "") + ".",
        f"Confidence: {found.confidence:.2f}" + (" (low: an officer should check it)" if found.low_confidence else "") + ".",
        f"Rationale: {found.rationale}",
    ]
    if len(found.candidates) > 1:
        others = ", ".join(f"{c.category} ({c.severity})" for c in found.candidates if c.code != found.category_code)
        lines.append(f"Also plausible: {others}. The more severe category was chosen so a safety issue isn't under-classified.")
    if found.is_defect:
        lines.append(f"A maintenance defect: i-EMS SLA {found.sla_days} days for {found.severity} severity.")
    else:
        lines.append(f"Not a maintenance defect: no i-EMS ticket; {found.team} handles it.")
    return "\n".join(lines)


def feedback_case(records_db: Path, question: str) -> FeedbackCase | None:
    """The first feedback case the question names that PLG Records hold."""
    ids = [i for i in find_ids(question) if is_valid_id("FeedbackCase", i)]
    if not ids:
        return None
    with sqlite3.connect(f"file:{records_db}?mode=ro", uri=True) as conn:
        for feedback_id in ids:
            row = conn.execute(
                "SELECT feedback_id, unit_id, description FROM feedback_cases WHERE feedback_id = ?", (feedback_id,)
            ).fetchone()
            if row:
                return {"feedback_id": row[0], "unit_id": row[1], "description": row[2]}
    return None
