"""Text extraction: each text-bearing format -> a flat list of headings and body blocks, plus control fields."""

from __future__ import annotations

import email
import email.policy
import re
from collections import Counter
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path

TEXT_SUFFIXES = {".docx", ".pdf", ".pptx", ".eml", ".md", ".txt"}

# Document-control keys whose value we read for metadata. In DOCX they sit in two-column tables;
# in PDFs and plain text the key and value are consecutive lines.
CONTROL_KEYS = {"Document ID", "Version", "Effective date", "Effective", "Status", "Date"}

# Numbered ("4.", "4.5 ") or ID-style ("PC-2023-041 - ", "IA-06 ") headings in text without styles.
_HEADING = re.compile(r"^(?:(?P<num>\d+\.(?:\d+\.?)*)|[A-Z]{2,5}-\d{2,4}(?:-\d{2,4})?(?:\s+-)?)\s+[A-Z(]")
_PAGE_NO = re.compile(r"^Page \d+ of \d+$")


@dataclass
class Block:
    text: str
    level: int = 0
    """0 for body text, else the heading level (1 = top)."""
    page: int | None = None
    """1-based page (PDF) or slide (PPTX)."""


@dataclass
class ParsedDoc:
    blocks: list[Block]
    fields: dict[str, str] = field(default_factory=dict)
    title: str | None = None


def extract(path: Path) -> ParsedDoc:
    match path.suffix.lower():
        case ".docx":
            return _docx(path)
        case ".pdf":
            return _pdf(path)
        case ".pptx":
            return _pptx(path)
        case ".eml":
            return _eml(path)
        case ".md":
            return _markdown(path.read_text(encoding="utf-8"))
        case ".txt":
            return _plain(path.read_text(encoding="utf-8").splitlines())
    raise ValueError(f"not a text-bearing document: {path}")


def _heading_level(line: str) -> int:
    """The heading level of a line in unstyled text, or 0 for body text."""
    m = _HEADING.match(line)
    if not m or len(line) > 80 or line.rstrip().endswith((".", ",", ";")):
        return 0
    return m["num"].rstrip(".").count(".") + 1 if m["num"] else 1


def _control_fields(lines: list[str], limit: int = 80) -> dict[str, str]:
    fields: dict[str, str] = {}
    head = [ln.strip() for ln in lines[:limit]]
    for key, value in zip(head, head[1:], strict=False):
        if key in CONTROL_KEYS and value and value not in CONTROL_KEYS:
            fields.setdefault(key, value)
    for line in head:  # "Effective: 1 April 2026"
        key, sep, value = line.partition(":")
        if sep and key in CONTROL_KEYS and value.strip():
            fields.setdefault(key, value.strip())
    return fields


def _plain(lines: list[str], page: int | None = None) -> ParsedDoc:
    blocks: list[Block] = []
    for line in (ln.strip() for ln in lines):
        if not line:
            continue
        level = _heading_level(line)
        blocks.append(Block(line, level, page))
    return ParsedDoc(blocks, _control_fields(lines))


def _markdown(text: str) -> ParsedDoc:
    blocks: list[Block] = []
    title: str | None = None
    for line in (ln.strip() for ln in text.splitlines()):
        if not line:
            continue
        if m := re.match(r"^(#{1,6})\s+(.*)$", line):
            level, heading = len(m[1]), m[2].strip()
            if level == 1 and title is None:
                title = heading
            blocks.append(Block(heading, level))
        else:
            blocks.append(Block(line))
    return ParsedDoc(blocks, _control_fields(text.splitlines()), title)


def _docx(path: Path) -> ParsedDoc:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(str(path))
    blocks: list[Block] = []
    fields: dict[str, str] = {}
    title: str | None = None
    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            text = item.text.strip()
            style = item.style.name if item.style is not None else ""
            if not text:
                continue
            if style == "Title":  # already in every chunk's contextual header
                title = title or text
            elif m := re.match(r"Heading (\d)", style):
                blocks.append(Block(text, int(m[1])))
            else:
                blocks.append(Block(f"- {text}" if style.startswith("List") else text))
        elif isinstance(item, Table):
            for row in item.rows:
                cells = list(dict.fromkeys(c.text.strip() for c in row.cells))  # merged cells repeat
                if len(cells) == 2 and cells[0] in CONTROL_KEYS:
                    fields.setdefault(cells[0], cells[1])
                if any(cells):
                    blocks.append(Block(" | ".join(cells)))
    return ParsedDoc(blocks, fields, title)


def _pdf(path: Path) -> ParsedDoc:
    from pypdf import PdfReader

    pages = [(p.extract_text() or "").splitlines() for p in PdfReader(path).pages]
    # Letterheads and running headers repeat on every page; keep them only where they first appear.
    repeated = Counter(ln.strip() for lines in pages for ln in set(lines[:6]))
    boilerplate = {ln for ln, n in repeated.items() if len(pages) > 1 and n >= len(pages) / 2}
    boilerplate |= {"HOUSING & ESTATES BOARD", "RESTRICTED - FICTIONAL POC DATA"}
    blocks: list[Block] = []
    for number, lines in enumerate(pages, start=1):
        kept = [
            ln for ln in lines
            if ln.strip() not in boilerplate
            and not _PAGE_NO.match(ln.strip())
            and not ln.startswith("Properties & Land Group  |")
        ]
        blocks.extend(_plain(kept, page=number).blocks)
    blocks = [b for b in blocks if b.text not in {"Item", "Detail"}]  # key/value table header rows
    all_lines = [ln for lines in pages for ln in lines]
    return ParsedDoc(blocks, _control_fields(all_lines))


def _pptx(path: Path) -> ParsedDoc:
    from pptx import Presentation

    blocks: list[Block] = []
    deck = Presentation(str(path))
    for number, slide in enumerate(deck.slides, start=1):
        title_shape = slide.shapes.title
        title = title_shape.text_frame.text.strip() if title_shape is not None else ""
        blocks.append(Block(f"Slide {number}: {title}".rstrip(": "), 1, number))
        for shape in slide.shapes:
            if shape is title_shape:
                continue
            if shape.has_text_frame and shape.text_frame.text.strip():
                blocks.extend(
                    Block(ln.strip(), 0, number) for ln in shape.text_frame.text.splitlines() if ln.strip()
                )
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    blocks.append(Block(" | ".join(c.text.strip() for c in row.cells), 0, number))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame
            if notes is not None and notes.text.strip():
                blocks.append(Block(f"Speaker notes: {notes.text.strip()}", 0, number))
    title = blocks[0].text.removeprefix("Slide 1: ") if blocks else None
    return ParsedDoc(blocks, {}, title)


def _eml(path: Path) -> ParsedDoc:
    message = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    assert isinstance(message, EmailMessage)
    part = message.get_body(preferencelist=("plain", "html"))
    body = part.get_content() if part is not None else ""
    body = re.split(r"\n--\s*\n", body, maxsplit=1)[0]  # drop the signature disclaimer
    attachments = [a.get_filename() for a in message.iter_attachments() if a.get_filename()]
    header = [f"{name}: {message[name]}" for name in ("From", "To", "Cc", "Date", "Subject") if message[name]]
    if attachments:
        header.append(f"Attachments: {', '.join(str(a) for a in attachments)}")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    blocks = [Block("\n".join(header)), *(Block(p) for p in paragraphs)]
    return ParsedDoc(blocks, {"Date": str(message["Date"] or "")}, str(message["Subject"] or "") or None)
