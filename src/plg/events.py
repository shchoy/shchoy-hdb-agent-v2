"""Run events streamed to clients as SSE. Pydantic models, so they can be published in OpenAPI (#3)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from plg.actions.model import Decision, ProposedAction
from plg.defects.classify import Classification
from plg.doccheck.model import DocCheck
from plg.agents.runtime import Citation
from plg.identity import Role
from plg.data.trace import SqlTrace
from plg.drafting.model import Draft
from plg.entities.policy import PolicyLineage


class NodeEvent(BaseModel):
    """A graph node started or finished, for the trajectory view."""

    type: Literal["node"] = "node"
    seq: int
    node: str
    status: Literal["started", "finished"]


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    seq: int
    node: str
    text: str


class CitationEvent(Citation):
    """A source the answer cites. `index` is the number of its `[n]` marker in the answer text."""

    type: Literal["citation"] = "citation"
    seq: int
    index: int


class SqlTraceEvent(SqlTrace):
    """One query the data agent sent: its plan, SQL, result summary and the glossary terms it relied on."""

    type: Literal["sql_trace"] = "sql_trace"
    seq: int


class DraftEvent(Draft):
    """A letter drafted from an approved template: HTML preview, open slots and personal-data flags. Not sent."""

    type: Literal["draft"] = "draft"
    seq: int


class PolicyStanceEvent(PolicyLineage):
    """PLG's position on one policy: the version in force, the versions it superseded and the circulars overriding it."""

    type: Literal["policy_stance"] = "policy_stance"
    seq: int


class ClassificationEvent(Classification):
    """Feedback classified into the defect taxonomy: category, severity, routing team and vendor, confidence, rationale."""

    type: Literal["classification"] = "classification"
    seq: int


class DocCheckEvent(DocCheck):
    """An application's submission bundle checked against its checklist: each file identified, each required
    document ticked or crossed, expired, wrong-unit and illegible documents flagged."""

    type: Literal["doc_check"] = "doc_check"
    seq: int


class ProposedActionEvent(ProposedAction):
    """Something the assistant proposes to do outside the system. It waits for the officer's decision."""

    type: Literal["proposed_action"] = "proposed_action"
    seq: int


class InterruptEvent(BaseModel):
    """The run paused for the officer's decision on this exact version: resume with POST /threads/{id}/resume."""

    type: Literal["interrupt"] = "interrupt"
    seq: int
    action_id: str
    version: int
    approver_roles: list[Role]


class ActionResultEvent(BaseModel):
    """A decision was carried out: the outbox item sent or i-EMS ticket raised (approve, edit), or nothing (reject)."""

    type: Literal["action_result"] = "action_result"
    seq: int
    action_id: str
    version: int
    """The version sent: one above the approved version after an edit."""
    decision: Decision
    outbox_id: str | None
    ticket_id: str | None


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    seq: int
    run_id: str


class ErrorEvent(BaseModel):
    """The run failed. Any answer streamed so far is partial and must not be trusted."""

    type: Literal["error"] = "error"
    seq: int
    run_id: str
    message: str


RunEvent = Annotated[
    NodeEvent | TokenEvent | CitationEvent | SqlTraceEvent | DraftEvent | PolicyStanceEvent | ClassificationEvent
    | DocCheckEvent | ProposedActionEvent
    | InterruptEvent | ActionResultEvent | DoneEvent | ErrorEvent, Field(discriminator="type")
]
