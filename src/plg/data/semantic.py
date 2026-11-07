"""The semantic layer: SQL bindings for glossary concepts, table notes, examples and known data-quality issues.

Source is `ontology/semantic.yaml`; `make ontology` validates it and writes `generated/semantic_layer.json`,
which is what runs.
"""

from __future__ import annotations

import json
import re
from datetime import date
from functools import cache
from pathlib import Path

from pydantic import BaseModel

from plg.data.sqlcheck import SqlRejected
from plg.data.warehouse import QueryResult, Warehouse
from plg.ontology import GENERATED


class Binding(BaseModel):
    """SQL returning the rows behind a figure, for one or more versioned glossary terms."""

    concepts: list[str]
    sql: str
    note: str = ""


class Example(BaseModel):
    question: str
    sql: str


class QualityIssue(BaseModel):
    id: str
    table: str
    values: list[str] = []
    sql_pattern: str | None = None
    message: str


class SemanticLayer(BaseModel):
    as_of_default: date
    bindings: list[Binding]
    tables: dict[str, str]
    examples: list[Example]
    quality_issues: list[QualityIssue]

    def binding(self, term_id: str) -> Binding | None:
        return next((b for b in self.bindings if term_id in b.concepts), None)

    def warnings(self, sql: str, result: QueryResult) -> list[str]:
        """The known data-quality issues this query hits: it reads the issue's table and names an affected
        record in its SQL or result, or matches the issue's pattern."""
        shown = {str(v) for row in result.rows for v in row if v is not None}
        warnings = []
        for issue in self.quality_issues:
            if issue.table not in result.tables:
                continue
            named = any(v in sql or v in shown for v in issue.values)
            pattern = issue.sql_pattern is not None and re.search(issue.sql_pattern, sql, re.IGNORECASE)
            if named or pattern:
                warnings.append(issue.message.strip())
        return warnings


def parse_semantic_layer(raw: dict[str, object]) -> SemanticLayer:
    return SemanticLayer.model_validate(raw)


@cache
def load_semantic_layer(path: Path = GENERATED / "semantic_layer.json") -> SemanticLayer:
    return SemanticLayer.model_validate(json.loads(path.read_text()))


def semantic_errors(layer: SemanticLayer, glossary_ids: set[str], warehouse: Warehouse) -> list[str]:
    """Problems that make a layer unfit to run: unknown glossary terms, bindings that don't plan, unknown tables."""
    errors = []
    for binding in layer.bindings:
        for term in binding.concepts:
            if term not in glossary_ids:
                errors.append(f"semantic: binding for {term}: not a glossary term")
        try:
            warehouse.dry_run(binding.sql, layer.as_of_default)
        except SqlRejected as e:
            errors.append(f"semantic: binding for {', '.join(binding.concepts)}: {e}")
    for table in [*layer.tables, *(i.table for i in layer.quality_issues)]:
        if table not in warehouse.tables:
            errors.append(f"semantic: table {table} is not in PLG Records")
    for issue in layer.quality_issues:
        if issue.sql_pattern:
            try:
                re.compile(issue.sql_pattern)
            except re.error as e:
                errors.append(f"semantic: quality issue {issue.id}: bad sql_pattern: {e}")
    return errors
