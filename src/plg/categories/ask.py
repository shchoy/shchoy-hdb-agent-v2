"""The `category_summary` specialist: answers "summarise the rental arrears category" from the saved categorisation.

Deterministic (no Claude): the question's words are matched against the categories' names (weighted) and
descriptions. A match gives that category's summary and documents; none gives the list of categories there are.
"""

from __future__ import annotations

from plg.categories.model import Categorisation, Category
from plg.entities.ids import search_name

NODE = "category_summary"

NOT_CATEGORISED = (
    "The Library's documents have not been grouped into categories yet (an administrator runs `plg categorise` "
    "after `plg sync`). Say so; offer to answer the question from the documents instead."
)
GUIDANCE = (
    "This is the Library's categorisation, an overview made when the documents were grouped: summarise the category "
    "from it and list its documents. For what a policy actually requires, the officer should ask about it directly."
)
_IGNORED = set(
    "a an and about all are category categories doc docs document documents for give group groups in is library "
    "me of on overview please summarise summarize summary tell the there under what which with".split()
)


def _words(text: str) -> set[str]:
    return {w for w in search_name(text).split() if w not in _IGNORED and len(w) > 1}


def match(question: str, categorisation: Categorisation) -> Category | None:
    """The category the question names: at least one word of its name, best scored; None if no category fits."""
    asked = _words(question)
    scored = []
    for category in categorisation.categories:
        in_name = len(asked & _words(category.name))
        if in_name:
            scored.append((2 * in_name + len(asked & _words(category.description)), category))
    return max(scored, key=lambda s: s[0])[1] if scored else None


def answer(question: str, categorisation: Categorisation) -> str:
    """The finding for merge."""
    if categorisation.categorised_at is None:
        return NOT_CATEGORISED
    when = categorisation.categorised_at.date().isoformat()
    category = match(question, categorisation)
    if category is None:
        lines = [f"No Library category matches the question. The Library's categories (grouped on {when}):"]
        lines += [f"- {c.name} ({len(c.documents)} documents): {c.description}" for c in categorisation.categories]
        lines.append("Name them and ask which one the officer means.")
        return "\n".join(lines)
    lines = [
        f'Library category "{category.name}" ({len(category.documents)} documents, grouped on {when}).',
        f"About: {category.description}",
        f"Summary: {category.summary}",
        "Documents:",
        *(f"- {d.title} ({d.doc_type}, {d.status})" for d in category.documents),
        GUIDANCE,
    ]
    return "\n".join(lines)
