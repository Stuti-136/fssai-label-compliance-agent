
"""Clause-aware chunking for official FSSAI regulatory documents."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, asdict
from pathlib import Path

MAX_CHARS, OVERLAP = 1100, 150


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    doc_title: str
    doc_version: str
    clause_id: str
    clause: str
    title: str
    part: int
    text: str
    embed_text: str
    content_hash: str

    def to_dict(self):
        return asdict(self)



def _mk(doc_id, doc_title, ver, clause, title, part, text):
    head = f"[{doc_id} | {clause} | {title}]"
    embed_text = f"{head}\n{text}"
    content_hash = hashlib.sha1(embed_text.encode()).hexdigest()

    # Include content in the ID so amended versions remain distinct.
    cid = hashlib.sha1(
        f"{doc_id}|{clause}|{part}|{content_hash}".encode()
    ).hexdigest()[:12]

    return Chunk(
        cid, doc_id, doc_title, ver, f"{doc_id}:{clause}",
        clause, title, part, text, embed_text, content_hash
    )



def _split(text):
    if len(text) <= MAX_CHARS:
        return [text]
    sentences = re.split(r"(?<=[.;])\s+|\n", text)
    output, current = [], ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > MAX_CHARS:
            output.append(current.strip())
            current = current[-OVERLAP:] + " " + sentence
        else:
            current += (" " if current else "") + sentence
    if current.strip():
        output.append(current.strip())
    return output


def parse_md(path):
    text = re.sub(r"<!--.*?-->", "", path.read_text(), flags=re.S)
    match = re.search(
        r"^# DOC:\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*$",
        text, re.M
    )
    if not match:
        raise ValueError(f"{path.name}: missing DOC header")

    doc_id, doc_title, version = match.groups()
    chunks = []

    for match in re.finditer(
        r"^## \[(.+?)\]\s*(.*?)\n(.*?)(?=^## \[|\Z)",
        text, re.M | re.S
    ):
        clause, title, body = (
            match.group(1).strip(),
            match.group(2).strip(),
            match.group(3).strip()
        )
        for i, piece in enumerate(_split(body)):
            chunks.append(
                _mk(doc_id, doc_title, version, clause, title, i, piece)
            )
    return chunks


def _pdf_edition_from_text(doc_id, header_text):
    if not header_text:
        return None

    date = r"(\d{2}[./_-]\d{2}[./_-]\d{4})"
    if doc_id == "LDR-2020":
        match = re.search(
            r"^\s*(?:\d+\s*\|\s*)?Version[\s-]+(VII|VIII)\s*\(\s*"
            + date + r"\s*\)\s*$",
            header_text,
            re.I | re.M,
        )
        if match:
            return f"Version {match.group(1).upper()} ({match.group(2).replace('/', '.')})"
    else:
        match = re.search(
            r"^\s*(?:\d+\s*\|\s*)?Version[^\r\n]{0,24}?\(\s*"
            + date + r"\s*\)\s*$",
            header_text,
            re.I | re.M,
        )
        if match:
            return f"Compendium ({match.group(1).replace('/', '.')})"
    return None


def _pdf_identity(path):
    name = path.name.lower()

    if "gazette" in name and "advertising" in name:
        return (
            "ACR-2018",
            "Food Safety and Standards (Advertising and Claims) Regulations, 2018",
            "Gazette Notification (27.11.2018)"
        )

    if path.stem.lower() == "ldr-2020":
        return (
            "LDR-2020",
            "Food Safety and Standards (Labelling and Display) Regulations, 2020",
            "Source PDF (version not encoded in PDF)"
        )

    if "labelling" in name:
        return (
            "LDR-2020",
            "Food Safety and Standards (Labelling and Display) Regulations, 2020",
            "Source PDF (version not encoded in PDF)"
        )

    if path.stem.lower() == "acr-2018":
        return (
            "ACR-2018",
            "Food Safety and Standards (Advertising and Claims) Regulations, 2018",
            "Source PDF (version not encoded in PDF)"
        )

    if "advertising" in name:
        return (
            "ACR-2018",
            "Food Safety and Standards (Advertising and Claims) Regulations, 2018",
            "Source PDF (version not encoded in PDF)"
        )

    raise ValueError(f"No canonical document mapping for {path.name}")



def _heading_pattern(doc_id):
    if doc_id == "LDR-2020":
        titles = {
            1: "Short Title and Commencement",
            2: "Definitions",
            3: "The FSSAI may establish",
            4: "General Requirements",
            5: "Labelling Requirements",
            6: "Principal display panel",
            7: "Mandatory Declarations",
            8: "Exemptions from certain labelling requirements",
            9: "Display of information in food service establishments",
            10: "Labelling Requirements of non-retail container",
            11: "Labelling of packaged Food Additives for Retail Sale",
            12: "Labelling of Pre-packaged Food Additives Sold other than by Retail",
            13: "The provision of these regulations shall supersede",
        }
    else:
        titles = {
            1: "Short title and commencement",
            2: "Definitions",
            3: "Food business operator and marketers",
            4: "General principles",
            5: "Nutrition claims",
            6: "Non-addition claims",
            7: "Health claims",
            8: "Claims related to dietary guidelines",
            9: "Conditional Claims",
            10: "Prohibited claims",
            11: "Approval of claims",
            12: "Procedure for approval of claims",
            13: "Redressal of non-compliance",
            14: "Procedure for redressal of non-compliance",
            15: "Corrective advertisement",
        }

    alternatives = "|".join(
        rf"(?P<r{number}>{re.escape(title)})"
        for number, title in titles.items()
    )

    return re.compile(
        rf"^\s*(?P<num>\d{{1,2}})\.\s+(?P<title>{alternatives})(?=[\s.:\-–—]|$)",
        re.I | re.M
    )


def _schedule_name(line):
    match = re.match(
        r"^\s*SCHEDULE\s*[-–—]?\s*([IVX]+A?)\s*$",
        line.strip(), re.I
    )
    return (
        "Schedule " + match.group(1).upper()
        if match else None
    )


def _make_chunks(doc_id, doc_title, version, clause, title, body):
    return [
        _mk(doc_id, doc_title, version, clause, title, i, piece)
        for i, piece in enumerate(_split(body))
        if piece.strip()
    ]


def _split_ldr_reg5(body):
    expected = {
        1: "Name of Food",
        2: "List of Ingredients",
        3: "Nutritional information",
        4: "Declaration regarding Veg or Non veg",
        5: "Declaration regarding Food Additives",
        6: "Declaration of name and complete address",
        7: "FSSAI logo and license number",
        8: "Net quantity",
        9: "Lot/Code/Batch identification",
        10: "Date Marking",
        11: "Labelling of Imported Foods",
        12: "Country of Origin",
        13: "Instructions for use",
        14: "Declaration regarding Food allergen",
        15: "Every package of food material",
    }

    lines = body.splitlines()
    marks = []

    for i, line in enumerate(lines):
        match = re.match(r"^\s*\((\d{1,2})\)\s*(.*?)\s*$", line)
        if not match:
            continue

        number = int(match.group(1))
        heading = match.group(2).lower()

        if number in expected and expected[number].lower() in heading:
            marks.append((i, number, match.group(2).strip()))

    if not marks:
        return [("Reg 5", "Labelling Requirements", body)]

    output = []

    if marks[0][0] > 0:
        prefix = "\n".join(lines[:marks[0][0]]).strip()
        if prefix:
            output.append(("Reg 5", "Labelling Requirements", prefix))

    for i, (start, number, heading) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(lines)
        section = "\n".join(lines[start:end]).strip()
        output.append((f"Reg 5({number})", heading, section))

    return output


def _schedule_chunks(doc_id, doc_title, version, schedule, body):
    if schedule != "Schedule I":
        return _make_chunks(
            doc_id, doc_title, version, schedule, "", body
        )

    pattern = re.compile(
        r"^\s*\d{1,2}\.\s*(?P<label>Fat|Sugars|Protein|Sodium|Dietary\s+fibre)\b.*$",
        re.I | re.M
    )
    marks = list(pattern.finditer(body))

    chunks = _make_chunks(
        doc_id, doc_title, version, schedule, "", body
    )

    for i, match in enumerate(marks):
        label = re.sub(
            r"\s+", " ", match.group("label")
        ).strip().lower()

        if label == "dietary fibre":
            label = "fibre"

        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        section = body[match.start():end].strip()
        clause = f"{schedule}/{label.title()}"

        chunks.extend(_make_chunks(
            doc_id, doc_title, version, clause, label.title(), section
        ))

    return chunks


def parse_pdf(path):
    from pypdf import PdfReader

    pages = [page.extract_text() or "" for page in PdfReader(str(path)).pages]
    raw = "\n".join(pages)
    doc_id, doc_title, version = _pdf_identity(path)
    if pages:
        version = _pdf_edition_from_text(doc_id, pages[0]) or version

    if len(raw.strip()) < 200:
        raise ValueError(f"{path.name}: no usable text layer")

    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    marks = []

    for match in _heading_pattern(doc_id).finditer(raw):
        marks.append((
            match.start(), match.end(), "reg",
            int(match.group("num")), match.group("title").strip()
        ))

    for match in re.finditer(r"^.*$", raw, re.M):
        schedule = _schedule_name(match.group())
        if schedule:
            marks.append((
                match.start(), match.end(), "schedule", schedule, ""
            ))

    marks.sort(key=lambda item: item[0])
    chunks = []

    for i, mark in enumerate(marks):
        start, end, kind, identifier, title = mark
        body_end = (
            marks[i + 1][0] if i + 1 < len(marks) else len(raw)
        )
        body = raw[end:body_end].strip()

        if len(body) < 20:
            continue

        if kind == "reg":
            if doc_id == "LDR-2020" and identifier == 5:
                sections = _split_ldr_reg5(body)
                for clause, sub_title, sub_body in sections:
                    chunks.extend(_make_chunks(
                        doc_id, doc_title, version,
                        clause, sub_title, sub_body
                    ))
            else:
                chunks.extend(_make_chunks(
                    doc_id, doc_title, version,
                    f"Reg {identifier}", title, body
                ))
        else:
            chunks.extend(_schedule_chunks(
                doc_id, doc_title, version, identifier, body
            ))

       # Collapse exact duplicate extraction results, preserving distinct amendments.
    unique = {}
    for chunk in chunks:
        unique.setdefault(chunk.chunk_id, chunk)

    return list(unique.values())


def parse_file(path):
    return (
        parse_md(path)
        if path.suffix.lower() in (".md", ".txt")
        else parse_pdf(path)
    )
