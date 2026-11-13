"""What each submitted file is, judged by its content, never its file name (applicants send `scan_0006.pdf`,
`Document (3).pdf`, ...).

A PDF with a text layer is identified by the printed title of the form or certificate. A scan (no text layer), or a
PDF whose text names no known document, is read by Claude through PDF input (Sonnet): it transcribes the page, says
whether it can read it, and names the document type. The transcription then goes through the same identification
and checks as a text PDF.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from pypdf import PdfReader

from plg.llm import Block, LLMClient

NODE = "doc_check"
"""The `doc_check` specialist, and the node its scan readings are made under."""
IDENTIFY_NODE = NODE
IDENTIFY_MAX_TOKENS = 4000

SIGNATURES: list[tuple[str, str]] = [
    ("REN", r"APPLICATION FOR RENEWAL OF TENANCY"),
    ("ASG", r"APPLICATION FOR ASSIGNMENT OF TENANCY"),
    ("COT", r"APPLICATION FOR CHANGE\s*/\s*ADDITION OF TRADE"),
    ("AA", r"APPLICATION FOR ALTERATION\s*&\s*ADDITION WORKS"),
    ("FEE", r"PAYMENT RECEIPT\s*-\s*ASSIGNMENT FEE"),
    ("CON", r"CONTRACTOR REGISTRATION CERTIFICATE"),
    ("PE", r"PROFESSIONAL ENGINEER ENDORSEMENT"),
    ("MS", r"METHOD STATEMENT"),
    ("DWG", r"LAYOUT\s*&\s*ELEVATION DRAWINGS"),
    ("LAYOUT", r"PROPOSED FLOOR LAYOUT"),
    ("PLAN", r"BUSINESS PLAN\b"),
    ("INS", r"CERTIFICATE OF INSURANCE"),
    ("GIRO", r"GIRO AUTHORISATION FORM"),
    ("DEP", r"PAYMENT ADVICE\s*-\s*SECURITY DEPOSIT"),
    ("LOA", r"ACCEPTANCE OF LETTER OF OFFER"),
    ("BIZ", r"BUSINESS\s+PROFILE"),
    ("NRIC", r"IDENTITY CARD"),
    ("LIC", r"-\s*LICEN[CS]E\b"),
]
"""The printed title of each document type (checked in this order, first match wins)."""

IDENTIFY_PROMPT = """\
File {file} of the submission bundle for application {application_id}. Transcribe the page text faithfully, one \
line per printed line, keeping names, IDs, unit numbers, addresses and dates exactly as printed; mark what you \
cannot read as [illegible]. Say whether the document is legible enough to accept: a scan whose key details (names, \
IDs, dates, amounts) can't be read is not. Then name the document type. Record the result with the record_document tool."""


def identify_prompt(application_id: str, file: str) -> str:
    return IDENTIFY_PROMPT.format(file=file, application_id=application_id)


def document_tool(codes: dict[str, str]) -> Block:
    return {
        "name": "record_document",
        "description": "Record what the submitted document is and what it says.",
        "input_schema": {
            "type": "object",
            "properties": {
                "document_type": {
                    "type": "string", "enum": [*codes, "OTHER"],
                    "description": "; ".join(f"{c}: {label}" for c, label in codes.items()) + "; OTHER: none of these.",
                },
                "legible": {"type": "boolean", "description": "False if the key details can't be read."},
                "title": {"type": "string", "description": "The document's title as printed."},
                "text": {"type": "string", "description": "The transcription, one line per printed line."},
            },
            "required": ["document_type", "legible", "title", "text"],
        },
    }


class Reading(BaseModel):
    """What Claude read off a scanned file."""

    document_type: str
    legible: bool
    title: str = ""
    text: str = ""


@dataclass(frozen=True)
class Identified:
    file: str
    text: str
    doc_code: str | None
    read_by: Literal["text", "scan"]
    legible: bool = True


def pdf_text(path: Path) -> str:
    try:
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    except Exception:  # an unreadable file is left to Claude
        return ""


def signature(text: str) -> str | None:
    upper = text.upper()
    return next((code for code, pattern in SIGNATURES if re.search(pattern, upper)), None)


async def identify(llm: LLMClient, application_id: str, path: Path, codes: dict[str, str]) -> Identified:
    """The document `path` is, from its text layer or, failing that, from Claude reading its pages."""
    text = pdf_text(path)
    if len(text.strip()) >= 20 and (code := signature(text)):
        return Identified(path.name, text, code, "text")
    reading = await read(llm, application_id, path, codes)
    content = f"{reading.title}\n{reading.text}"
    code = signature(content) or (reading.document_type if reading.document_type in codes else None)
    return Identified(path.name, content, code, "scan" if len(text.strip()) < 20 else "text", reading.legible)


async def read(llm: LLMClient, application_id: str, path: Path, codes: dict[str, str]) -> Reading:
    pdf = base64.standard_b64encode(path.read_bytes()).decode()
    tool = document_tool(codes)
    reply = await llm.complete(
        node=IDENTIFY_NODE, tier="sonnet",
        system=[{"type": "text", "text": "You identify documents tenants submit with their applications to the Properties & Land Group."}],
        messages=[{"role": "user", "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf}},
            {"type": "text", "text": identify_prompt(application_id, path.name)},
        ]}],
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        max_tokens=IDENTIFY_MAX_TOKENS,
    )
    call = next((b for b in reply.content if b["type"] == "tool_use" and b["name"] == tool["name"]), None)
    if call is None:
        return Reading(document_type="OTHER", legible=False)
    return Reading.model_validate(call["input"])
