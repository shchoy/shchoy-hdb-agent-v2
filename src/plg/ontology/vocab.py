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


class TermMatch(BaseModel):
    """A PLG term spotted in free text, and the concepts it names."""

    text: str
    concepts: list[ConceptRef]


MAX_TERM_WORDS = 6


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

    def find_terms(self, text: str) -> list[TermMatch]:
        """PLG terms in free text, longest first: abbreviations written in capitals ("LOD", "NC", "A&A") and
        multi-word labels ("ceiling leak"). Single lower-case words are skipped; too many are everyday words."""
        words = list(re.finditer(r"[A-Za-z0-9]+", text))
        found: list[TermMatch] = []
        i = 0
        while i < len(words):
            for n in range(min(MAX_TERM_WORDS, len(words) - i), 0, -1):
                surface = text[words[i].start() : words[i + n - 1].end()]
                is_abbreviation = surface.upper() == surface and any(c.isalpha() for c in surface)
                concepts = self.resolve(surface) if n > 1 or is_abbreviation else []
                if concepts:
                    found.append(TermMatch(text=surface, concepts=concepts))
                    i += n
                    break
            else:
                i += 1
        return found


@cache
def load_vocab(path: Path = GENERATED / "vocab_index.json") -> VocabIndex:
    data = json.loads(path.read_text())
    labels = {
        label: [ConceptRef.model_validate(r) for r in refs] for label, refs in data["labels"].items()
    }
    return VocabIndex(data["schemes"], labels)
