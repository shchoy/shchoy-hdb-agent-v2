"""LangSmith tracing (issue #27): one trace per graph run, tenant PII masked before upload, and the trace's URL.

A run (a question, or the resume of an approval) is a root `plg_run` whose ID is the run ID the answer reports in
`done`, so feedback and "view trace" point at it. Its metadata says whose thread, which intents, which channel and
which code; the graph's nodes and `Send()` branches (LangGraph), Claude calls (`wrap_anthropic`), tool calls and
searches (`@traceable`) nest under it and inherit the thread, user, channel and git SHA.

Everything goes through a `Client` built by `tracing_client`, whose anonymizer masks identity numbers, emails, phone
numbers and tenant contact names in inputs, outputs, errors and metadata before they leave the process.
"""

from __future__ import annotations

import functools
import os
import re
import sqlite3
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

import langsmith
from langsmith import Client
from langsmith.anonymizer import create_anonymizer
from langsmith.run_trees import RunTree

from plg.config import REPO_ROOT, Settings
from plg.drafting.pii import EMAIL, NRIC, PHONE
from plg.identity import UserCtx

Channel = Literal["api", "cli"]
ROOT = "plg_run"


def tenant_contacts(records_db: Path) -> list[str]:
    """Tenants' contact people (named in PLG Records), longest first so a full name masks before a part of it."""
    with sqlite3.connect(f"file:{records_db}?mode=ro", uri=True) as conn:
        rows = conn.execute("SELECT DISTINCT contact_person FROM tenants WHERE contact_person IS NOT NULL").fetchall()
    return sorted({name.strip() for (name,) in rows if name and name.strip()}, key=len, reverse=True)


def pii_masker(records_db: Path) -> Callable[[str], str]:
    """Masks identity numbers, emails, phone numbers and tenant contact names in a string."""
    names = tenant_contacts(records_db)
    contact = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b", re.IGNORECASE) if names else None

    def mask(value: str) -> str:
        value = NRIC.sub("[NRIC]", value)
        value = EMAIL.sub("[email]", value)
        value = PHONE.sub("[phone]", value)
        return contact.sub("[tenant contact]", value) if contact else value

    return mask


def tracing_client(records_db: Path, **client_kwargs: Any) -> Client:
    """A LangSmith client that masks tenant PII in everything it uploads."""
    mask = pii_masker(records_db)
    return Client(anonymizer=create_anonymizer(lambda value, _path: mask(value)), **client_kwargs)


@functools.cache
def git_sha() -> str:
    """The commit the code runs from (PLG_GIT_SHA when there is no checkout, e.g. in a container)."""
    if sha := os.environ.get("PLG_GIT_SHA"):
        return sha
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5)
    except OSError:
        return "unknown"
    return out.stdout.strip() or "unknown"


class Tracer:
    """Traces graph runs to one LangSmith project and finds a run's page there."""

    def __init__(self, client: Client, project: str | None = None) -> None:
        self.client = client
        self.project = project or os.environ.get("LANGSMITH_PROJECT") or "default"
        self._project_url: str | None = None

    @contextmanager
    def run(
        self, run_id: str, *, thread_id: str, user: UserCtx | None, channel: Channel, inputs: dict[str, Any],
        extra: dict[str, Any] | None = None,
    ) -> Iterator[RunTree]:
        """The root run: every node, Claude call and tool call inside the block nests under it."""
        shared: dict[str, Any] = {"thread_id": thread_id, "channel": channel, "git_sha": git_sha()}
        if user is not None:
            shared |= {"user_id": user.staff_id, "user_role": user.role}
        with langsmith.tracing_context(enabled=True, client=self.client, project_name=self.project, metadata=shared):
            with langsmith.trace(
                ROOT, "chain", run_id=run_id, inputs=inputs, metadata={**shared, **(extra or {})},
                tags=[channel], client=self.client, project_name=self.project,
            ) as root:
                yield root

    def url(self, run_id: str) -> str:
        """The run's page in LangSmith (the project, and so the workspace, is looked up once)."""
        if self._project_url is None:
            self._project_url = self.client.read_project(project_name=self.project).url
        return f"{self._project_url}/r/{run_id}?poll=true"


def open_tracer(settings: Settings) -> Tracer | None:
    """Tracing is on when LangSmith is configured: LANGSMITH_API_KEY set and LANGSMITH_TRACING true."""
    if not os.environ.get("LANGSMITH_API_KEY") or not langsmith.utils.tracing_is_enabled():
        return None
    return Tracer(tracing_client(settings.records_db))


def install_tracer(settings: Settings) -> Tracer | None:
    """`open_tracer`, made LangSmith's default client too, so traces outside a graph run (`plg sync`'s scans and
    lineage, background memory extraction) are masked the same way."""
    tracer = open_tracer(settings)
    if tracer is not None:
        langsmith.configure(client=tracer.client, project_name=tracer.project)
    return tracer
