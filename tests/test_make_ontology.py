"""`make ontology` (scripts/build_ontology.py) refuses an invalid glossary and writes nothing."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from plg.config import REPO_ROOT


def test_a_broken_supersedes_chain_fails_the_build_and_writes_nothing(tmp_path: Path) -> None:
    source = tmp_path / "ontology"
    shutil.copytree(REPO_ROOT / "ontology", source)
    glossary = source / "glossary.yaml"
    glossary.write_text(glossary.read_text().replace("supersedes: plg:LodTrigger_v1", "supersedes: plg:LodTrigger_v0"))
    out = tmp_path / "generated"

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "build_ontology.py"), "--source", str(source), "--out", str(out)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "plg:LodTrigger_v2: supersedes plg:LodTrigger_v0, which does not exist" in result.stderr
    assert not out.exists()


def test_a_semantic_binding_that_does_not_plan_fails_the_build_and_writes_nothing(tmp_path: Path) -> None:
    source = tmp_path / "ontology"
    shutil.copytree(REPO_ROOT / "ontology", source)
    semantic = source / "semantic.yaml"
    semantic.write_text(semantic.read_text().replace("u.status = 'Vacant' AND", "u.no_such_column = 'Vacant' AND"))
    out = tmp_path / "generated"

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "build_ontology.py"), "--source", str(source), "--out", str(out)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "semantic: binding for plg:Vacant_v2: The query does not plan" in result.stderr
    assert not out.exists()


def test_a_binding_for_an_unknown_glossary_term_fails_the_build(tmp_path: Path) -> None:
    source = tmp_path / "ontology"
    shutil.copytree(REPO_ROOT / "ontology", source)
    semantic = source / "semantic.yaml"
    semantic.write_text(semantic.read_text().replace("concepts: [plg:UnderTender_v1]", "concepts: [plg:UnderTender_v9]"))

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "build_ontology.py"), "--source", str(source), "--out", str(tmp_path / "g")],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "semantic: binding for plg:UnderTender_v9: not a glossary term" in result.stderr
