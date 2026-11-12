"""Clause-aware chunking (L1). Why: the difficult case spans two regulations; every chunk therefore carries
doc id + clause id + title as a contextual header that is embedded WITH the text, so a search for
'nutrition claim conditions' can land on the claims regulation and a clause can be fetched by id.
One clause = one chunk; long clauses are split on sentence boundaries with overlap and keep the same clause id."""
from __future__ import annotations
import hashlib, re
from dataclasses import dataclass, asdict
from pathlib import Path

MAX_CHARS, OVERLAP = 1100, 150


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    doc_title: str
    doc_version: str
    clause_id: str   # "DOC:Clause"
    clause: str
    title: str
    part: int
    text: str
    embed_text: str
    content_hash: str

    def to_dict(self):
        return asdict(self)


def _mk(doc_id, doc_title, ver, clause, title, part, text) -> Chunk:
    head = f"[{doc_id} | {clause} | {title}]"
    cid = hashlib.sha1(f"{doc_id}|{clause}|{part}".encode()).hexdigest()[:12]
    embed_text = f"{head}\n{text}"
    return Chunk(cid, doc_id, doc_title, ver, f"{doc_id}:{clause}", clause, title, part, text, embed_text,
                 hashlib.sha1(embed_text.encode()).hexdigest())


def _split(text: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    sents = re.split(r"(?<=[.;])\s+|\n", text)
    out, cur = [], ""
    for s in sents:
        if cur and len(cur) + len(s) > MAX_CHARS:
            out.append(cur.strip())
            cur = cur[-OVERLAP:] + " " + s
        else:
            cur += (" " if cur else "") + s
    if cur.strip():
        out.append(cur.strip())
    return out


def parse_md(path: Path) -> list[Chunk]:
    text = re.sub(r"<!--.*?-->", "", path.read_text(), flags=re.S)
    m = re.search(r"^# DOC:\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*$", text, re.M)
    if not m:
        raise ValueError(f"{path.name}: missing '# DOC: id | title | version' header")
    doc_id, doc_title, ver = m.groups()
    chunks = []
    for cm in re.finditer(r"^## \[(.+?)\]\s*(.*?)\n(.*?)(?=^## \[|\Z)", text, re.M | re.S):
        clause, title, body = cm.group(1).strip(), cm.group(2).strip(), cm.group(3).strip()
        for i, piece in enumerate(_split(body)):
            chunks.append(_mk(doc_id, doc_title, ver, clause, title, i, piece))
    return chunks


def parse_pdf(path: Path) -> list[Chunk]:
    """Text-layer PDFs only (scanned PDFs need OCR first). Splits on 'N. Heading' regulations and SCHEDULE headings."""
    from pypdf import PdfReader
    raw = "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    if len(raw.strip()) < 200:
        raise ValueError(f"{path.name}: no text layer; run OCR first")
    doc_id = path.stem.split(".")[0]
    pat = re.compile(r"^\s*(?:(?P<reg>\d{1,2})\.\s+(?P<rt>[A-Z][^\n]{2,90})|(?P<sch>SCHEDULE[\s\-–]*[IVX]+)\b[^\n]*)\s*$", re.M)
    marks = list(pat.finditer(raw))
    chunks = []
    for i, mk in enumerate(marks):
        body = raw[mk.end(): marks[i + 1].start() if i + 1 < len(marks) else len(raw)].strip()
        if len(body) < 30:
            continue
        clause = f"Reg {mk.group('reg')}" if mk.group("reg") else re.sub(r"[\s\-–]+", " ", mk.group("sch")).title().replace("Schedule ", "Schedule ")
        title = (mk.group("rt") or "").strip()
        for j, piece in enumerate(_split(re.sub(r"[ \t]+", " ", body))):
            chunks.append(_mk(doc_id, doc_id, "pdf", clause, title, j, piece))
    return chunks


def parse_file(path: Path) -> list[Chunk]:
    return parse_md(path) if path.suffix in (".md", ".txt") else parse_pdf(path)
