"""L4: prompt-injection defence, toxicity detection, output filtering.
Free text is checked at the ingestion boundary (before any agent starts) and sanitised again before it can
reach a model. Agents never see raw label text outside <label_text> data delimiters."""
from __future__ import annotations
import re, unicodedata

INJECTION = [re.compile(p, re.I) for p in [
    r"ignore (all |any |the |your )?(previous|prior|above|earlier)\b.{0,30}(instruction|prompt|rule|message)",
    r"disregard\b.{0,40}(instruction|rule|prompt|polic)",
    r"forget (everything|all|your)\b.{0,30}(instruction|rule|prompt)?",
    r"\byou are now\b", r"\bnew instructions?\b", r"\bsystem prompt\b", r"\bdeveloper mode\b",
    r"\bjailbreak\b", r"\bdo anything now\b", r"\bact as (a|an|the|if)\b",
    r"reveal\b.{0,30}(prompt|instruction|key|secret|credential)",
    r"<\s*/?\s*(system|assistant|tool|instructions?)\s*>", r"\[\s*(system|inst)\s*\]",
    r"(approve|clear|pass|certify)\b.{0,20}\b(this|the) (label|pack|packaging|request)",
    r"mark (this|it|the label) as (approved|compliant|clear|passed)",
    r"(call|use|invoke|run)\b.{0,15}\b(tool|function|search_corpus|lookup_clause)",
    r"\boverride\b.{0,20}(rule|check|polic|route|verification)",
    r"set (the )?route to", r"clear-for-print\b.{0,40}(always|regardless)",
]]
TOXIC = re.compile(r"\b(idiot|stupid|moron|scum|dumbass|shut up|hate you|kill yourself|crap|damn you|bastard|asshole)\b", re.I)
_ZW = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)


def _norm(t: str) -> str:
    return unicodedata.normalize("NFKC", t).translate(_ZW)


def detect_injection(text: str) -> str | None:
    t = _norm(text)
    for p in INJECTION:
        if p.search(t):
            return p.pattern[:60]
    return None


def detect_toxicity(text: str) -> bool:
    return bool(TOXIC.search(_norm(text)))


def sanitize_for_prompt(text: str, limit: int = 600) -> str:
    t = _norm(str(text))
    t = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", t)
    t = t.replace("<", "\u2039").replace(">", "\u203a").replace("```", "'''")
    return re.sub(r"\s+", " ", t).strip()[:limit]


def wrap_untrusted(text: str) -> str:
    return f"<label_text>{sanitize_for_prompt(text)}</label_text>"


# ---- output filter: the system never approves a label for print or certifies compliance.
FORBIDDEN_OUT = re.compile(
    r"\b(approved?|approves|approval granted|certif(?:y|ied|ies)|guarantee[sd]?|legally compliant|"
    r"fully compliant|is compliant|safe to print|cleared? to print|authori[sz]ed for print)\b", re.I)
ALLOWED_ROUTES = {"clear-for-print", "revise-and-recheck", "regulatory-review"}


def filter_output(text: str) -> tuple[str, bool]:
    """Redact determinations the system is not authorised to make. Returns (text, was_modified)."""
    out = FORBIDDEN_OUT.sub("[determination reserved for regulatory affairs]", text or "")
    return out, out != text


def check_free_text(fields: dict[str, str]) -> list[dict]:
    errs = []
    for name, val in fields.items():
        if not val:
            continue
        if (pat := detect_injection(val)):
            errs.append({"field": name, "code": "prompt_injection_suspected",
                         "message": "Field contains instruction-like text addressed to an AI system."})
        if detect_toxicity(val):
            errs.append({"field": name, "code": "toxic_content", "message": "Field contains abusive language."})
    return errs
