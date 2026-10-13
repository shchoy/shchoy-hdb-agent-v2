"""Vocabulary index: SKOS-style concepts by scheme, and synonym/abbreviation resolution."""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from plg.ontology import GENERATED
from plg.ontology.generated.models import Concept


class ConceptRef(BaseModel):
    id: str
    scheme: str
    pref_label: str
    notation: str | None = None


def normalise(text: str) -> str:
    """Case-, punctuation- and spacing-insensitive form of a label: "Letter-of-Demand" -> "letter of demand"."""
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


class VocabIndex:
    def __init__(self, schemes: dict[str, list[dict[str, Any]]], labels: dict[str, list[ConceptRef]]) -> None:
        self._schemes = schemes
        self._labels = labels

    def scheme(self, scheme: str) -> list[ConceptRef]:
        return [ConceptRef.model_validate({**c, "scheme": scheme}) for c in self._schemes[scheme]]

    def concepts[C: Concept](self, scheme: str, cls: type[C]) -> list[C]:
        """The full concepts of a scheme, as the generated ontology class."""
        return [cls.model_validate(c) for c in self._schemes[scheme]]

    def resolve(self, text: str) -> list[ConceptRef]:
        """Concepts whose preferred or alternative label is `text`."""
        return list(self._labels.get(normalise(text), []))


@cache
def load_vocab(path: Path = GENERATED / "vocab_index.json") -> VocabIndex:
    data = json.loads(path.read_text())
    labels = {
        label: [ConceptRef.model_validate(r) for r in refs] for label, refs in data["labels"].items()
    }
    return VocabIndex(data["schemes"], labels)
