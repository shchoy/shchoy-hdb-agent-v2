"""`plg ask`, driven through the CLI with a scripted LLMClient."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from plg import cli
from plg.config import Settings
from plg.llm import LLMClient, ScriptedLLMClient
from tests.conftest import route


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> ScriptedLLMClient:
    scripted = ScriptedLLMClient()

    def make_llm(settings: Settings) -> LLMClient:
        return scripted

    monkeypatch.setattr(cli, "make_llm", make_llm)
    return scripted


def test_ask_prints_the_streamed_answer(llm: ScriptedLLMClient) -> None:
    route(llm, "hello")
    llm.script("merge", "hello", "Hello! How can I help with PLG today?")

    result = CliRunner().invoke(cli.app, ["ask", "hello"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "Hello! How can I help with PLG today?"


def test_ask_reports_a_failure_mid_answer_and_exits_non_zero(llm: ScriptedLLMClient) -> None:
    route(llm, "hello")
    llm.script("merge", "hello", "The letter of", error=ConnectionError("Claude unavailable"))

    result = CliRunner().invoke(cli.app, ["ask", "hello"])

    assert result.exit_code == 1
    assert "The letter of" in result.stdout
    assert "failed" in result.stderr


def test_openapi_prints_the_api_contract_without_an_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = CliRunner().invoke(cli.app, ["openapi"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["openapi"].startswith("3.1")
    assert "RunEvent" in doc["components"]["schemas"]


def test_memory_cli_lists_edits_and_forgets_an_officers_notes(tmp_path: Path) -> None:
    from plg.search.embed import HashingEmbedder

    env = {"PLG_SEARCH_DB": str(tmp_path / "index"), "PLG_EMBED_DIM": "1024"}
    store = None
    with pytest.MonkeyPatch.context() as mp:
        from plg import cli

        embedder = HashingEmbedder(dim=1024)
        from plg.memory.store import MemoryStore
        from plg.search.lance import LanceSearchStore

        store = MemoryStore(LanceSearchStore(tmp_path / "index", dim=1024), embedder)
        mp.setattr(cli, "make_memory", lambda settings: store)
        runner = CliRunner()
        listed = runner.invoke(cli.app, ["memory", "list", "--user", "S05"], env=env)
        assert listed.exit_code == 0 and "Leasing Officer" in listed.output and "Staff records" in listed.output
        note = store.remember("S05", "preference", "Prefers tables", provenance="test")
        assert runner.invoke(cli.app, ["memory", "edit", note.id, "Prefers lists", "-u", "S05"], env=env).exit_code == 0
        assert "Prefers lists" in runner.invoke(cli.app, ["memory", "show", note.id, "-u", "S05"], env=env).output
        assert runner.invoke(cli.app, ["memory", "forget", note.id, "-u", "S01"], env=env).exit_code == 1
        assert runner.invoke(cli.app, ["memory", "forget", note.id, "-u", "S05"], env=env).exit_code == 0
        assert store.find("S05", note.id) is None
