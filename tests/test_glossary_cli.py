"""`plg glossary list` and `plg glossary show`, driven through the CLI."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from plg import cli
from plg.ontology.changes import GlossaryChange, GlossaryChanges, GlossaryVersion, superseded
from plg.ontology.glossary import load_glossary


@pytest.fixture(autouse=True)
def changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Where the CLI reads approved changes: never the developer's .plg/."""
    path = tmp_path / "glossary_changes.jsonl"
    monkeypatch.setenv("PLG_GLOSSARY_CHANGES", str(path))
    return path


def run(*args: str) -> tuple[int, str, str]:
    result = CliRunner().invoke(cli.app, ["glossary", *args])
    return result.exit_code, result.stdout, result.stderr


def test_an_approved_change_shows_as_current_and_the_old_version_is_kept(changes: Path) -> None:
    base = load_glossary()
    previous = GlossaryVersion.of(base.current("plg:Vacant"))  # type: ignore[arg-type]
    new = previous.model_copy(update={
        "id": "plg:Vacant_v3", "version": 3, "definition": "Counted at month end.", "effective_from": date(2026, 10, 1),
        "supersedes": previous.id, "status": "current",
    })
    GlossaryChanges(changes).approve(GlossaryChange(
        term=new, previous=superseded(previous, date(2026, 10, 1)), sql=None, action_id="a1", approved_by="S08",
        at="2026-11-14T00:00:00+00:00",
    ), base)

    code, out, _ = run("show", "vacant")

    assert code == 0
    current, history = out.split("History:")
    assert "plg:Vacant_v3" in current and "Counted at month end." in current
    assert "plg:Vacant_v2  v2  superseded  2026-04-15 -> 2026-09-30" in history
    assert "plg:Vacant_v1" in history


def test_list_shows_each_term_once_at_its_current_version() -> None:
    code, out, _ = run("list")

    assert code == 0
    vacant = [line for line in out.splitlines() if line.startswith("plg:Vacant ")]
    assert len(vacant) == 1
    assert "v2" in vacant[0] and "2026-04-15" in vacant[0] and "1 earlier" in vacant[0]
    assert "plg:ArrearsAgeingBucket" in out


def test_list_all_includes_superseded_versions() -> None:
    code, out, _ = run("list", "--all")

    assert code == 0
    assert "plg:LodTrigger_v1" in out and "superseded" in out
    assert "plg:LodTrigger_v2" in out


def test_show_gives_the_current_definition_then_its_history() -> None:
    code, out, _ = run("show", "LOD trigger")

    assert code == 0
    current, history = out.split("History", 1)
    assert "plg:LodTrigger_v2" in current and "60 days overdue" in current
    assert "2026-04-01" in current and "DOC-002" in current and "PLG-POL-003 v2.0 cl. 4.5" in current
    assert "Priya Menon" in current
    assert "plg:LodTrigger_v1" in history and "45 days overdue" in history and "2026-03-31" in history


def test_show_resolves_an_abbreviation() -> None:
    code, out, _ = run("show", "LOD")

    assert code == 0
    assert out.startswith("Letter of Demand trigger (plg:LodTrigger)")


def test_show_accepts_a_concept_id_or_a_synonym() -> None:
    by_id = run("show", "plg:Vacant")
    by_synonym = run("show", "vacancy")

    assert by_id == by_synonym
    assert by_id[0] == 0 and "excludes units under tender" in by_id[1]


def test_show_an_unknown_term_fails() -> None:
    code, _, err = run("show", "durian")

    assert code == 1
    assert "No glossary term matches 'durian'" in err
