"""StateGraph wiring: START → route → specialists (fan-out; `defect` and `doc_check` run the `defect_flow` and
`doc_check_flow` subgraphs; `tasks` is deterministic) → merge → (approval → execute_action)* → END.

`route` (Haiku) decides which specialists a question needs; none means `merge` answers it directly.
`merge` fuses the specialists' findings into one answer and is the only node that streams tokens.
Proposed actions wait at `approval` (a LangGraph interrupt) for the officer's decision; `execute_action`, the only
node with side effects, is reachable only from there.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt
from pydantic import BaseModel

from plg.actions import letters, tickets
from plg.actions.audit import AuditEntry, AuditLog
from plg.actions.model import ApprovalDecision, LetterPayload, ProposedAction, TicketPayload, pending
from plg.actions.outbox import LocalOutbox, Outbox, OutboxItem
from plg.agents import data, drafting, knowledge
from plg.agents.runtime import CACHE
from plg.config import Settings
from plg.defects.classify import NODE as DEFECT_NODE
from plg.defects.flow import DefectInput, build_defect_flow
from plg.defects.taxonomy import Taxonomy, load_taxonomy
from plg.defects.tickets import LocalTicketSystem, TicketSystem
from plg.doccheck.checklists import Checklists, load_checklists
from plg.doccheck.flow import DocCheckInput, build_doc_check_flow
from plg.doccheck.identify import NODE as DOC_CHECK_NODE
from plg.data.semantic import SemanticLayer, load_semantic_layer
from plg.data.warehouse import Warehouse
from plg.drafting.model import Draft
from plg.drafting.store import DraftStore
from plg.drafting.templates import TemplateLibrary
from plg.entities.policy import PolicyLineage
from plg.entities.store import GraphStore
from plg.graph import summary as history
from plg.identity import UserCtx, load_personas
from plg.tasks import ask as task_ask
from plg.tasks import rules as task_rules
from plg.graph.state import RUN_ID, Finding, Intent, PLGGraph, PLGState
from plg.memory.service import MemoryService
from plg.llm import AgentMessage, Block, LLMClient, Message
from plg.ontology.glossary import Glossary, load_glossary
from plg.ontology.vocab import VocabIndex, load_vocab
from plg.search.rerank import Retriever

ROUTE = "route"
KNOWLEDGE = knowledge.NODE
DATA = data.NODE
DRAFTING = drafting.NODE
DEFECT = DEFECT_NODE
DOC_CHECK = DOC_CHECK_NODE
TASKS = task_ask.NODE
MERGE = "merge"
SUMMARISE = history.NODE
LOAD_MEMORY = "load_memory"
WRITE_MEMORY = "write_memory"
APPROVAL = "approval"
EXECUTE = "execute_action"

ROUTE_SYSTEM = """\
You route questions from officers of the Properties & Land Group (PLG) to specialists.
- knowledge: anything answered from PLG's documents and records, including what is known about a tenant, unit or tenancy: policies, SOPs, circulars, procedures, \
rules, limits, deadlines, what a PLG term means, precedents (past cases and decisions), audit findings, incidents, letters, emails and notes.
- data: numeric questions answered by querying PLG Records and the Excel trackers (vacancy report, arrears ageing, \
rent roll, renewals pipeline, inspection and officer task trackers, trade mix, feedback statistics): counts, totals, \
rates and lists of units, tenancies, arrears, invoices, inspections, feedback, tickets and tasks; and why two \
reported figures differ.
- drafting: the officer asks for a standard letter or notice to be drafted: an arrears reminder, a missing-documents \
notice, or an update reply to someone who gave feedback.
- defect: the officer pastes public or tenant feedback (or names a feedback case) to have it classified and routed, \
e.g. to raise an i-EMS maintenance ticket for it.
- doc_check: the officer asks whether an application (APP-yyyy-nnnn) is complete or has all its documents, or asks \
to check its submitted documents or bundle; the check also drafts the missing-documents notice for it, so a request \
for that notice about a named application goes here, not to drafting.
- tasks: the officer asks what to work on: their own (or a named colleague's) top, most urgent or overdue tasks, work \
queue or task digest, ranked and explained. Counts and statistics of tasks across PLG go to data.
A question can have several parts, each needing a different specialist: name every specialist needed. Choose no \
specialist for greetings, thanks and questions about how to use the assistant.
Give each specialist your confidence (0 to 1) that the question needs it. If you can't tell what the officer is asking \
for (which unit, tenant or document they mean, or what they want to know about it), give low confidence and write \
the one short question you would ask them to clear it up; earlier messages of the conversation may already say."""

ROUTE_TOOL: Block = {
    "name": ROUTE,
    "description": "Send the question to the specialists that can answer it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "intents": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "intent": {"type": "string", "enum": ["knowledge", "data", "drafting", "defect", "doc_check", "tasks"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["intent", "confidence"],
                },
                "description": "The specialists needed, each with your confidence that it is; empty if none.",
            },
            "clarifying_question": {
                "type": "string",
                "description": "The question to ask the officer when the request is too unclear to route.",
            },
        },
        "required": ["intents"],
    },
    "cache_control": CACHE,
}

MERGE_SYSTEM = (
    "You are the PLG Super-Librarian, an assistant for officers of the Properties & Land Group. "
    "Answer clearly and concisely using PLG's own terms."
)

MERGE_FINDINGS = """
Answer the officer's question from the specialists' findings below, and only from them. Keep each citation \
marker such as [1] right after the claim it supports, exactly as written; never add, renumber or drop one. \
Figures from the data specialist carry no marker: keep them exact and keep the business definition and \
effective date it names. Do not add facts the findings don't contain.

{findings}"""

MERGE_SECTIONS = """
The question has several parts. Answer each part in its own section, in the order the officer asked them, each \
headed `## ` and a few words naming the part. Put nothing before the first section."""

MERGE_NO_SOURCES = """
No specialist searched PLG's sources for this message. Don't state PLG policies, rules, figures, dates or \
records from memory; if the officer asks about them, say you couldn't look that up and ask them to rephrase it \
as a question about PLG's documents."""

CLARIFY = "Could you tell me a bit more about what you need, and which unit, tenant or document it is about?"
"""Asked when `route` named no specialist confidently and didn't say what it would ask."""

NOT_COVERED = (
    "The indexed PLG sources don't cover this question, so I can't give you a sourced answer. "
    "Try rephrasing it, or check with the policy owner."
)


class ScoredIntent(BaseModel):
    intent: Intent
    confidence: float


class RouteDecision(BaseModel):
    intents: list[ScoredIntent]
    clarifying_question: str = ""

    def confident(self, threshold: float) -> list[Intent]:
        """The specialists named with at least `threshold` confidence; weaker labels are dropped."""
        return list(dict.fromkeys(i.intent for i in self.intents if i.confidence >= threshold))

    def needs_clarification(self, threshold: float) -> bool:
        """No specialist was named with confidence, though the router named some or had a question to ask."""
        unsure = bool(self.intents) or bool(self.clarifying_question.strip())
        return unsure and not self.confident(threshold)


def build_graph(
    llm: LLMClient,
    retriever: Retriever,
    vocab: VocabIndex | None = None,
    entities: GraphStore | None = None,
    *,
    warehouse: Warehouse,
    glossary: Glossary | None = None,
    layer: SemanticLayer | None = None,
    templates: TemplateLibrary | None = None,
    drafts: DraftStore | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    settings: Settings | None = None,
    memory: MemoryService | None = None,
    outbox: Outbox | None = None,
    audit: AuditLog | None = None,
    ticket_system: TicketSystem | None = None,
    taxonomy: Taxonomy | None = None,
    checklists: Checklists | None = None,
) -> PLGGraph:
    vocab = vocab or load_vocab()
    glossary = glossary or load_glossary()
    layer = layer or load_semantic_layer()
    settings = settings or Settings.from_env()
    templates = templates or TemplateLibrary(settings.corpus_dir)
    drafts = drafts or DraftStore()
    outbox = outbox or LocalOutbox(settings.outbox_dir)
    audit = audit or AuditLog(settings.audit_log)
    ticket_system = ticket_system or LocalTicketSystem(settings.iems_dir)
    taxonomy = taxonomy or load_taxonomy(vocab)
    defect_flow = build_defect_flow(llm, taxonomy, warehouse.records_db)
    doc_check_flow = build_doc_check_flow(
        llm, checklists or load_checklists(vocab), warehouse.records_db, settings.submissions_dir, templates
    )
    staff = list(load_personas(warehouse.records_db).values())
    first = LOAD_MEMORY if memory else ROUTE  # memory is recalled before routing when the graph has one

    def unsummarised(state: PLGState) -> list[Message]:
        return state.get("messages", [])[state.get("summarised", 0):]

    def conversation(state: PLGState) -> list[Message]:
        recent = unsummarised(state)
        earlier: list[Message] = (
            [{"role": "user", "content": history.SUMMARY_LEAD + state["summary"]}] if state.get("summary") else []
        )
        return [*earlier, *recent, {"role": "user", "content": state["question"]}]

    def start(state: PLGState) -> str:
        recent = unsummarised(state)
        too_long = history.estimate_tokens(recent, state.get("summary", "")) > settings.history_token_threshold
        return SUMMARISE if too_long and len(recent) > settings.history_keep_messages else first

    async def summarise_history(state: PLGState) -> PLGState:
        recent = unsummarised(state)
        cut = len(recent) - settings.history_keep_messages
        folded = await history.fold(llm, recent[:cut], state.get("summary", ""))
        return {"summary": folded, "summarised": state.get("summarised", 0) + cut}

    def agent_conversation(state: PLGState) -> list[AgentMessage]:
        return [{"role": m["role"], "content": m["content"]} for m in conversation(state)]

    async def load_memory(state: PLGState) -> PLGState:
        """The officer's private notes for this turn, as one labelled block (never a source)."""
        user = state.get("user")
        notes = await asyncio.to_thread(memory.context, user, state["question"]) if memory and user else ""
        return {"memory": notes}

    async def route(state: PLGState) -> PLGState:
        reply = await llm.complete(
            node=ROUTE,
            tier="haiku",
            system=[{"type": "text", "text": ROUTE_SYSTEM, "cache_control": CACHE}],
            messages=agent_conversation(state),
            tools=[ROUTE_TOOL],
            tool_choice={"type": "tool", "name": ROUTE},
        )
        call = next(b for b in reply.content if b["type"] == "tool_use")
        decision = RouteDecision.model_validate(call["input"])
        threshold = settings.route_min_confidence
        if decision.needs_clarification(threshold):
            return {"intents": [], "clarification": decision.clarifying_question.strip() or CLARIFY, "findings": []}
        return {"intents": decision.confident(threshold), "clarification": "", "findings": []}

    def fan_out(state: PLGState) -> Sequence[Send | str]:
        """One task per specialist, run in parallel; none (or a clarifying question) goes straight to merge."""
        return [Send(intent, state) for intent in state.get("intents", [])] or [MERGE]

    def propose_sending(state: PLGState, draft: Draft, user: UserCtx) -> ProposedAction:
        """Stream the draft, and propose sending it: it waits for the officer at `approval`."""
        get_stream_writer()({"draft": draft.model_dump()})
        return letters.propose_letter(draft, user.staff_id, state.get("proposed_actions", []))

    async def knowledge_node(state: PLGState) -> PLGState:
        stances: dict[str, PolicyLineage] = {}

        def remember(found: PolicyLineage) -> None:
            stances.setdefault(found.policy_id, found)

        result = await knowledge.answer(
            llm, retriever, vocab, agent_conversation(state), state["question"], entities,
            on_lineage=remember,
        )
        write = get_stream_writer()
        for stance in stances.values():
            write({"policy_stance": stance.model_dump(mode="json")})
        for n, citation in enumerate(result.citations, start=1):
            write({"citation": citation.model_dump(), "index": n})
        return {"findings": [Finding(specialist=KNOWLEDGE, text=result.text, citations=result.citations)]}

    async def data_node(state: PLGState) -> PLGState:
        result = await data.answer(
            llm, warehouse, glossary, layer, vocab, agent_conversation(state), state["question"]
        )
        write = get_stream_writer()
        for trace in result.traces:
            write({"sql_trace": trace.model_dump(mode="json")})
        ran = any(t.status == "ok" for t in result.traces)
        return {"findings": [Finding(specialist=DATA, text=result.text, citations=[], traced=ran)]}

    async def drafting_node(state: PLGState) -> PLGState:
        result = await drafting.answer(
            llm, warehouse, layer, templates, drafts, agent_conversation(state), state.get("user")
        )
        finding = Finding(specialist=DRAFTING, text=result.text, citations=[], traced=result.draft is not None)
        user = state.get("user")
        if not result.draft or user is None:
            return {"findings": [finding]}
        return {"findings": [finding], "proposed_actions": [propose_sending(state, result.draft, user)]}

    async def defect_node(state: PLGState) -> PLGState:
        """Run `defect_flow`; its classification is streamed, its ticket (if any) waits for the officer at `approval`."""
        inputs: DefectInput = {"question": state["question"]}
        if user := state.get("user"):
            inputs["user"] = user
        out = await defect_flow.ainvoke(inputs)
        get_stream_writer()({"classification": out["classification"].model_dump(mode="json")})
        finding = Finding(specialist=DEFECT, text=out["summary"], citations=[], traced=True)
        return {"findings": [finding], "proposed_actions": out.get("proposed_actions", [])}

    async def doc_check_node(state: PLGState) -> PLGState:
        """Run `doc_check_flow`; its checklist is streamed, its missing-documents notice (if any) is drafted and waits
        for the officer at `approval`."""
        inputs: DocCheckInput = {"question": state["question"]}
        user = state.get("user")
        if user:
            inputs["user"] = user
        out = await doc_check_flow.ainvoke(inputs)
        write = get_stream_writer()
        if found := out.get("result"):
            write({"doc_check": found.model_dump(mode="json")})
        finding = Finding(specialist=DOC_CHECK, text=out["summary"], citations=[], traced=True)
        draft = out.get("notice")
        if draft is None or user is None:
            return {"findings": [finding]}
        drafts.add(user.staff_id, draft, out["notice_docx"])
        return {"findings": [finding], "proposed_actions": [propose_sending(state, draft, user)]}

    async def tasks_node(state: PLGState) -> PLGState:
        """Rank the officer's (or a named colleague's, if their role allows) open tasks by the rules matrix; stream the
        ranking. Deterministic: merge words the rationale from the reasons given. Its findings count as traced (a
        records read or the role check that refused it), so merge relays a refusal rather than "not covered"."""
        user = state.get("user")
        if user is None:
            return {"findings": [Finding(specialist=TASKS, text=task_ask.NO_USER, citations=[], traced=True)]}
        officer = task_ask.whose(state["question"], user, staff)
        if not task_rules.can_view(user, officer):
            refusal = task_ask.NOT_ALLOWED.format(viewer=user.name, title=user.title, target=officer.name)
            return {"findings": [Finding(specialist=TASKS, text=refusal, citations=[], traced=True)]}
        found = await asyncio.to_thread(
            task_rules.digest, warehouse.records_db, officer, settings.tasks_today, task_ask.how_many(state["question"])
        )
        get_stream_writer()({"tasks": found.model_dump(mode="json")})
        return {"findings": [Finding(specialist=TASKS, text=task_rules.render(found) + "\n" + task_ask.RATIONALE, citations=[], traced=True)]}

    async def merge(state: PLGState) -> PLGState:
        write = get_stream_writer()
        findings = state.get("findings", [])
        parts: list[str] = []
        clarification = state.get("clarification", "")
        tokens = _words(clarification) if clarification else _fuse(llm, conversation(state), findings, state.get("memory", ""))
        async for text in tokens:
            parts.append(text)
            write({"node": MERGE, "token": text})
        answer = "".join(parts)
        question: Message = {"role": "user", "content": state["question"]}
        return {"answer": answer, "messages": [question, {"role": "assistant", "content": answer}]}

    async def write_memory(state: PLGState, config: RunnableConfig) -> PLGState:
        """Learn from the answered turn in the background: only the officer's own words and verified findings."""
        user = state.get("user")
        if memory and user:
            verified = "\n".join(f.text for f in state.get("findings", []) if f.citations or f.traced)
            thread_id = str(config.get("configurable", {}).get("thread_id", ""))
            memory.learn_in_background(user, thread_id, state["question"], verified)
        return {}

    def after_answer(state: PLGState) -> str:
        return APPROVAL if pending(state.get("proposed_actions", [])) else END

    def approval(state: PLGState) -> PLGState:
        """Pause until the officer decides on one of the pending actions (the interrupt carries them all). The
        decision is checked again here, so nothing but a decision on an exact pending version, by its owner
        holding an approver role, gets through."""
        waiting = pending(state.get("proposed_actions", []))
        decision = ApprovalDecision.model_validate(interrupt([a.model_dump(mode="json") for a in waiting]))
        action = next((a for a in waiting if a.action_id == decision.action_id), None)
        refusal = decision.refusal(action) if action else "That action is not pending."
        if refusal:
            raise PermissionError(refusal)
        return {"decision": decision}

    async def execute_action(state: PLGState, config: RunnableConfig) -> PLGState:
        """Carry out the decision: send the (edited) letter to the outbox or raise the (edited) ticket in i-EMS, or
        nothing for a rejection; audit it."""
        decision = state.get("decision")
        assert decision is not None, "execute_action runs only after approval"
        action = next(a for a in state.get("proposed_actions", []) if a.action_id == decision.action_id)
        if decision.refusal(action):  # never act on a stale decision
            raise PermissionError("The decision no longer matches a pending action.")
        sent: ProposedAction | None = None
        if decision.decision == "edit" and action.action_type == "raise_ticket":
            sent = tickets.edited(action, decision.edits, taxonomy)
        elif decision.decision == "edit":
            sent = await asyncio.to_thread(letters.edited, action, decision.edits, templates, warehouse.records_db)
        elif decision.decision == "approve":
            sent = action
        outbox_id = ticket_id = None
        if sent is not None and isinstance(sent.payload, TicketPayload):
            ticket = tickets.to_ticket(sent, raised_by=decision.approver)
            await asyncio.to_thread(ticket_system.raise_ticket, ticket)
            ticket_id = ticket.ticket_id
        elif sent is not None and isinstance(sent.payload, LetterPayload):
            outbox_id = f"{sent.action_id}-v{sent.version}"
            item = OutboxItem(
                item_id=outbox_id, action_id=sent.action_id, version=sent.version,
                template_id=sent.payload.template_id, recipient=sent.payload.recipient, title=sent.title,
                slots=sent.payload.slots, html=sent.preview, approver=decision.approver, sent_at=letters.now(),
            )
            await asyncio.to_thread(outbox.send, item)
        entry = AuditEntry(
            action_id=action.action_id, version=action.version, action_type=action.action_type, title=action.title,
            thread_id=str(config.get("configurable", {}).get("thread_id", "")), decision=decision.decision, edits=decision.edits, reason=decision.reason, approver=decision.approver,
            approver_role=decision.approver_role, at=letters.now(),
            run_id=str(config.get("configurable", {}).get(RUN_ID, "")), outbox_id=outbox_id, ticket_id=ticket_id,
        )
        await asyncio.to_thread(audit.record, entry)
        get_stream_writer()({"action_result": {
            "action_id": action.action_id, "version": sent.version if sent else action.version,
            "decision": decision.decision, "outbox_id": outbox_id, "ticket_id": ticket_id,
        }})
        done = (sent or action).model_copy(update={"status": "rejected" if sent is None else "approved"})
        return {"proposed_actions": [done], "decision": None}

    graph = StateGraph(PLGState)
    graph.add_node(ROUTE, route)
    graph.add_node(KNOWLEDGE, knowledge_node)
    graph.add_node(DATA, data_node)
    graph.add_node(DRAFTING, drafting_node)
    graph.add_node(DEFECT, defect_node)
    graph.add_node(DOC_CHECK, doc_check_node)
    graph.add_node(TASKS, tasks_node)
    graph.add_node(MERGE, merge)
    graph.add_node(SUMMARISE, summarise_history)
    graph.add_node(APPROVAL, approval)
    graph.add_node(EXECUTE, execute_action)
    graph.add_edge(APPROVAL, EXECUTE)
    graph.add_conditional_edges(EXECUTE, after_answer, [APPROVAL, END])
    graph.add_conditional_edges(START, start, [SUMMARISE, first])
    graph.add_edge(SUMMARISE, first)
    if memory:
        graph.add_node(LOAD_MEMORY, load_memory)
        graph.add_node(WRITE_MEMORY, write_memory)
        graph.add_edge(LOAD_MEMORY, ROUTE)
    graph.add_conditional_edges(ROUTE, fan_out, [KNOWLEDGE, DATA, DRAFTING, DEFECT, DOC_CHECK, TASKS, MERGE])
    graph.add_edge(KNOWLEDGE, MERGE)
    graph.add_edge(DATA, MERGE)
    graph.add_edge(DRAFTING, MERGE)
    graph.add_edge(DEFECT, MERGE)
    graph.add_edge(DOC_CHECK, MERGE)
    graph.add_edge(TASKS, MERGE)
    answered = WRITE_MEMORY if memory else MERGE
    if memory:
        graph.add_edge(MERGE, WRITE_MEMORY)
    graph.add_conditional_edges(answered, after_answer, [APPROVAL, END])
    return graph.compile(checkpointer=checkpointer or InMemorySaver())


async def _fuse(
    llm: LLMClient, messages: list[Message], findings: list[Finding], memory: str = ""
) -> AsyncIterator[str]:
    """The answer's tokens. Findings without a single citation are not an answer: say the sources don't
    cover the question rather than let Claude fill the gap."""
    supported = [f for f in findings if f.citations or f.traced]
    if findings and not supported:
        async for token in _words(NOT_COVERED):
            yield token
        return
    if findings:
        blocks = "\n\n".join(f"<{f.specialist}>\n{f.text}\n</{f.specialist}>" for f in findings)
        system = MERGE_SYSTEM + MERGE_FINDINGS.format(findings=blocks)
        if len(supported) > 1:  # one section per part that has a sourced answer
            system += MERGE_SECTIONS
    else:
        system = MERGE_SYSTEM + MERGE_NO_SOURCES
    if memory:
        system += "\n\n" + memory
    async for text in llm.stream_text(node=MERGE, tier="sonnet", system=system, messages=messages):
        yield text


async def _words(text: str) -> AsyncIterator[str]:
    """A fixed reply, streamed word by word like Claude's."""
    for token in re.findall(r"\s*\S+", text):
        yield token
