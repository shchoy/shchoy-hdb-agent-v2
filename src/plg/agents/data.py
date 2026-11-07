"""The `data` agent: answers numeric questions over PLG Records by planning, writing read-only SQL, running it
through the validator and explaining the result in terms of the business definition in force.

Business terms (vacant, arrears, ...) come from the glossary: the agent asks `get_definition` for the version in
force on the reporting date and its SQL binding, so a historical question uses the definition of its time.
Every query it sends leaves a `SqlTrace`.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from pydantic import BaseModel, ValidationError

from plg.agents.runtime import Tool, run_agent
from plg.data.semantic import SemanticLayer
from plg.data.sqlcheck import SqlRejected
from plg.data.trace import ConceptUsed, ResultSummary, SqlTrace
from plg.data.warehouse import QueryResult, Warehouse
from plg.llm import AgentMessage, LLMClient
from plg.ontology.generated.models import GlossaryTerm
from plg.ontology.glossary import Glossary
from plg.ontology.vocab import VocabIndex

NODE = "data"

SAMPLE_ROWS = 10
"""Rows of a result kept in the trace."""
SHOWN_ROWS = 60
"""Rows of a result shown to the agent."""

SYSTEM = """\
You are the data specialist of the PLG Super-Librarian, answering numeric questions from officers of the \
Properties & Land Group by querying PLG Records (counts, sums, lists of tenancies, units, invoices, inspections, ...).

How to work:
1. Plan first: which business terms does the question use, as of which date, and which tables answer it.
2. For every business term (vacant, arrears, active tenancy, occupancy, ...) call get_definition with the date the \
question is about. It returns the definition version in force then, with its effective dates and, when there is one, \
the SQL binding that implements it. Build your query on that binding (wrap it as a subquery) rather than \
re-deriving the term. Never use a figure's definition from memory.
3. Call run_sql with your plan, the SQL, the versioned glossary term IDs it relies on (e.g. plg:Vacant_v2), and the \
reporting date `as_of` (omit for the data date, {today}). Use $as_of in the SQL for that date. Only one SELECT is accepted, \
over the tables below. If it is rejected, read the reason, fix the query and send it again.
4. Explain the result: say what was counted, name the business definition and its effective date, and quote the \
figures exactly as the query returned them. Mention any data-quality warning the result carries. Don't guess at \
numbers you did not query; if the data cannot answer the question, say so.

When two figures disagree (for example the QBR says 52 vacant and the monthly report 47), look for a definition \
change: call get_definition for each version (use `version`) and run both bindings on the same date, then explain \
the difference in terms of what each definition includes.

PLG Records is a snapshot as at {today}: "today" and "now" mean that date.
Money is Singapore dollars. Dates are ISO text: compare them as strings and use date_diff for day counts. Amounts \
come with GST where the glossary says so. Be concise.

Tables (all columns are in the database; DESCRIBE is not available, so use the schema below):
{tables}

Example queries:
{examples}"""

class DefinitionInput(BaseModel):
    concept: str
    as_of: date | None = None
    version: int | None = None


class SqlInput(BaseModel):
    plan: str
    sql: str
    concepts: list[str] = []
    as_of: date | None = None


class DataResult(BaseModel):
    text: str
    traces: list[SqlTrace]


def concept_used(term: GlossaryTerm) -> ConceptUsed:
    return ConceptUsed(
        id=term.id, concept=term.concept, version=term.version, label=term.pref_label,
        effective_from=term.effective_from, effective_to=term.effective_to,
    )


def describe_term(term: GlossaryTerm, glossary: Glossary, layer: SemanticLayer) -> str:
    period = f"from {term.effective_from}" if term.effective_from else "since before records began"
    if term.effective_to:
        period += f" to {term.effective_to}"
    lines = [f"{term.id} ({term.pref_label}), {term.status}, in force {period}.", f"Definition: {term.definition}"]
    if term.value:
        lines.append(f"Value: {term.value}")
    others = [f"{t.id} ({t.status})" for t in glossary.versions(term.concept) if t.id != term.id]
    if others:
        lines.append(f"Other versions: {', '.join(others)}.")
    binding = layer.binding(term.id)
    if binding:
        lines.append(f"SQL binding ($as_of = the reporting date; defaults to {layer.as_of_default}):\n{binding.sql.strip()}")
        if binding.note:
            lines.append(f"Note: {' '.join(binding.note.split())}")
        if len(binding.concepts) > 1:
            lines.append(f"The same binding implements {', '.join(c for c in binding.concepts if c != term.id)}.")
    else:
        lines.append("No SQL binding: this term is not computed from PLG Records.")
    return "\n".join(lines)


def definition_tool(glossary: Glossary, layer: SemanticLayer) -> Tool:
    async def run(raw: dict[str, Any]) -> str:
        try:
            args = DefinitionInput.model_validate(raw)
        except ValidationError as e:
            return f"Invalid arguments: {e.errors()[0]['msg']}"
        concept = glossary.find(args.concept)
        if concept is None:
            return f"No glossary term matches {args.concept!r}."
        if args.version is not None:
            term = next((t for t in glossary.versions(concept) if t.version == args.version), None)
            return describe_term(term, glossary, layer) if term else f"{concept} has no version {args.version}."
        on = args.as_of or layer.as_of_default
        term = glossary.in_force(concept, on)
        if term is None:
            versions = ", ".join(f"{t.id} from {t.effective_from or 'before records'}" for t in glossary.versions(concept))
            return f"No approved version of {concept} was in force on {on}. Versions: {versions}."
        return describe_term(term, glossary, layer)

    return Tool(
        name="get_definition",
        description=(
            "The business definition of a PLG term as in force on a date (default: the data date), or a given "
            "version: its versioned ID, definition, effective dates, other versions and, where there is one, "
            "the SQL binding."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "concept": {"type": "string", "description": "A glossary concept ID such as plg:Vacant, a versioned ID, or a label."},
                "as_of": {"type": "string", "format": "date", "description": "The date the question is about (YYYY-MM-DD)."},
                "version": {"type": "integer", "description": "A specific version, instead of the one in force."},
            },
            "required": ["concept"],
        },
        run=run,
    )


def result_text(result: QueryResult, warnings: list[str]) -> str:
    lines = ["\t".join(result.columns), *("\t".join("" if v is None else str(v) for v in r) for r in result.rows[:SHOWN_ROWS])]
    count = f"{len(result.rows)}{'+' if result.truncated else ''}"
    lines.append(f"({count} rows{', first ' + str(SHOWN_ROWS) + ' shown' if len(result.rows) > SHOWN_ROWS else ''})")
    lines += [f"DATA QUALITY WARNING: {w}" for w in warnings]
    return "\n".join(lines)


def sql_tool(warehouse: Warehouse, glossary: Glossary, layer: SemanticLayer, traces: list[SqlTrace]) -> Tool:
    async def run(raw: dict[str, Any]) -> str:
        try:
            args = SqlInput.model_validate(raw)
        except ValidationError as e:
            return f"Invalid arguments: {e.errors()[0]['msg']}"
        as_of = args.as_of or layer.as_of_default
        used: list[ConceptUsed] = []
        trace = SqlTrace(
            plan=args.plan, sql=args.sql.strip(), as_of=as_of, status="rejected", error=None, result=None,
            concepts=[], warnings=[], explanation="",
        )
        try:
            for ref in args.concepts:
                term = next((t for t in glossary.terms if t.id == ref), None)
                if term is None and (concept := glossary.find(ref)):
                    term = glossary.in_force(concept, as_of)
                if term is None:
                    raise SqlRejected(f"{ref!r} is not a glossary term version in force on {as_of}; call get_definition.")
                used.append(concept_used(term))
            trace.concepts = used
            result = await asyncio.to_thread(warehouse.run, args.sql, as_of)
        except SqlRejected as e:
            trace.error = str(e)
            traces.append(trace)
            return f"Rejected: {e}"
        trace.status = "ok"
        trace.warnings = layer.warnings(args.sql, result)
        trace.result = ResultSummary(
            columns=result.columns, row_count=len(result.rows), truncated=result.truncated,
            sample=result.rows[:SAMPLE_ROWS],
        )
        traces.append(trace)
        return result_text(result, trace.warnings)

    return Tool(
        name="run_sql",
        description=(
            "Run one read-only SELECT over PLG Records (DuckDB SQL; $as_of is bound to `as_of`). It is validated, "
            "dry-run and then executed. Returns the rows (tab-separated) and any data-quality warnings, or the "
            "reason it was rejected."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "One or two sentences: what you are computing and from which tables."},
                "sql": {"type": "string", "description": "A single SELECT statement."},
                "concepts": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Versioned glossary term IDs the query relies on, e.g. plg:Vacant_v2.",
                },
                "as_of": {"type": "string", "format": "date", "description": "The reporting date (YYYY-MM-DD); omit for the data date."},
            },
            "required": ["plan", "sql"],
        },
        run=run,
    )


def terms_context(layer: SemanticLayer, glossary: Glossary, vocab: VocabIndex, question: str) -> str:
    """Glossary terms that have SQL bindings, and PLG terms the question uses."""
    bound = dict.fromkeys(
        glossary.find(term) or term for b in layer.bindings for term in b.concepts
    )
    labels = [f"- {c}: {t.pref_label}" for c in bound if c and (t := glossary.current(c) or glossary.versions(c)[-1])]
    found = [
        f'- "{m.text}" means ' + "; ".join(f"{c.pref_label} ({c.id})" for c in m.concepts) for m in vocab.find_terms(question)
    ]
    parts = ["Glossary terms with SQL bindings (pass them to get_definition):\n" + "\n".join(labels)]
    if found:
        parts.append("PLG terms in the question:\n" + "\n".join(found))
    return "\n\n".join(parts)


def with_definitions(text: str, traces: list[SqlTrace]) -> str:
    """`text`, ending with the definitions the queries relied on (version and effective date) unless it already
    names them all, so no explanation leaves out which definition was used."""
    used = {c.id: c for t in traces if t.status == "ok" for c in t.concepts}
    missing = [
        c for c in used.values()
        if not (str(c.effective_from) in text or c.effective_to and str(c.effective_to) in text)
    ]
    if not missing:
        return text
    def line(c: ConceptUsed) -> str:
        start = f"from {c.effective_from}" if c.effective_from else "since before records began"
        return f"{c.label} v{c.version} ({c.id}, in force {start}{f' to {c.effective_to}' if c.effective_to else ''})"
    return f"{text}\n\nDefinitions used: {'; '.join(line(c) for c in missing)}.".strip()


async def answer(
    llm: LLMClient,
    warehouse: Warehouse,
    glossary: Glossary,
    layer: SemanticLayer,
    vocab: VocabIndex,
    messages: list[AgentMessage],
    question: str,
) -> DataResult:
    traces: list[SqlTrace] = []
    tables = "\n".join(f"- {name}: {note}" for name, note in layer.tables.items())
    examples = "\n".join(f"Q: {e.question}\n{e.sql.strip()}" for e in layer.examples)
    result = await run_agent(
        llm,
        node=NODE,
        system=SYSTEM.format(today=layer.as_of_default, tables=tables, examples=examples),
        context=terms_context(layer, glossary, vocab, question),
        tools=[definition_tool(glossary, layer), sql_tool(warehouse, glossary, layer, traces)],
        messages=messages,
    )
    text = result.text
    if traces:
        text = with_definitions(text, traces)
        traces[-1].explanation = text
    return DataResult(text=text, traces=traces)
