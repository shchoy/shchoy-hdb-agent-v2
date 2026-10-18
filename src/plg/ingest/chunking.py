"""Structure-aware chunking: one chunk per section (split only when long), each with a contextual header."""

from __future__ import annotations

from dataclasses import dataclass

from plg.ingest.extract import Block

MAX_CHARS = 1800


@dataclass(frozen=True)
class Section:
    path: list[str]
    """Heading trail, outermost first."""
    text: str
    page: int | None


def sections(blocks: list[Block]) -> list[Section]:
    """Body text grouped under its heading trail. Headings with no body of their own produce nothing."""
    trail: list[tuple[int, str]] = []
    result: list[Section] = []
    body: list[str] = []
    page: int | None = None

    def flush() -> None:
        if body:
            result.append(Section([h for _, h in trail], "\n".join(body), page))
            body.clear()

    for block in blocks:
        if block.level:
            flush()
            trail[:] = [(lvl, h) for lvl, h in trail if lvl < block.level] + [(block.level, block.text)]
            page = block.page
        else:
            if not body:
                page = block.page if block.page is not None else page
            body.append(block.text)
    flush()
    return result


def split(text: str, limit: int = MAX_CHARS) -> list[str]:
    """Pieces of at most `limit` characters, cut at line breaks where possible."""
    pieces: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            cut = line.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if current:
                pieces.append(current)
                current = ""
            pieces.append(line[:cut])
            line = line[cut:].lstrip()
        if current and len(current) + 1 + len(line) > limit:
            pieces.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        pieces.append(current)
    return pieces


def location(section: Section, part: int, parts: int) -> str:
    where = " > ".join(section.path) or "(body)"
    if section.page is not None:
        where = f"{where} (p. {section.page})"
    return f"{where} [part {part + 1}/{parts}]" if parts > 1 else where
