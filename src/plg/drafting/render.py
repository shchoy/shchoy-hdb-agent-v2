"""Fill a template's slots; render the result as an HTML preview and a DOCX file."""

from __future__ import annotations

import html
import io
import re

import docx
from docx.enum.text import WD_COLOR_INDEX
from docx.document import Document as DocxDocument

from plg.drafting.templates import SLOT, Template, letter_paragraphs

OPEN = "«{}»"
"""How a slot with no value shows in the letter, so it can't be mistaken for finished wording."""


def fill(template: Template, values: dict[str, str]) -> list[str]:
    """The letter's paragraphs with each slot replaced by its value, or marked open if it has none."""
    clean = {slot: value.replace("«", "").replace("»", "") for slot, value in values.items()}
    return [SLOT.sub(lambda m: clean.get(m.group(1)) or OPEN.format(m.group(1)), p) for p in template.body]


def to_html(paragraphs: list[str]) -> str:
    """An HTML fragment. All text is escaped, so a slot value can't inject markup."""
    def render(p: str) -> str:
        escaped = html.escape(p).replace("\n", "<br>")
        marked = "".join(
            f"<mark>{part}</mark>" if part.startswith("«") else part for part in _split_open(escaped)
        )
        return f"<p>{marked}</p>" if p.strip() else ""
    return "\n".join(r for r in map(render, paragraphs) if r)


def _split_open(text: str) -> list[str]:
    return [part for part in re.split(r"(«\w+»)", text) if part]


def to_docx(template: Template, paragraphs: list[str]) -> bytes:
    """The template file with its control block removed and the letter's paragraphs filled in."""
    document: DocxDocument = docx.Document(str(template.path))
    body = document.element.body
    letter = letter_paragraphs(document)
    keep = {p._p for p in letter}
    for element in list(body):
        if element.tag.endswith("}sectPr"):
            continue
        if element not in keep:
            body.remove(element)
    for p, text in zip(letter, paragraphs, strict=False):
        for run in list(p.runs):
            run._r.getparent().remove(run._r)
        for part in _split_open(text):
            run = p.add_run(part)
            if part.startswith("«"):
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()
