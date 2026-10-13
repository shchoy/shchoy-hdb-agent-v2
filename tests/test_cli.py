"""`plg ask`, driven through the CLI with a scripted LLMClient."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from plg import cli
from plg.config import Settings
from plg.llm import LLMClient, ScriptedLLMClient


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> ScriptedLLMClient:
    scripted = ScriptedLLMClient()

    def make_llm(settings: Settings) -> LLMClient:
        return scripted

    monkeypatch.setattr(cli, "make_llm", make_llm)
    return scripted


def test_ask_prints_the_streamed_answer(llm: ScriptedLLMClient) -> None:
    llm.script("merge", "hello", "Hello! How can I help with PLG today?")

    result = CliRunner().invoke(cli.app, ["ask", "hello"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "Hello! How can I help with PLG today?"


def test_ask_reports_a_failure_mid_answer_and_exits_non_zero(llm: ScriptedLLMClient) -> None:
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
