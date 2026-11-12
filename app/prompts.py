"""Prompts are versioned artifacts: app/prompts/<version>/<name>.txt. The version is recorded on every response (L2)."""
from __future__ import annotations
from pathlib import Path
from string import Template
from .config import get_settings

ROOT = Path(__file__).parent / "prompts"


def available_versions() -> list[str]:
    return sorted(p.name for p in ROOT.iterdir() if p.is_dir())


def render(name: str, version: str | None = None, **vars) -> tuple[str, str, str]:
    """returns (system, user, version)."""
    v = version or get_settings().prompt_version
    raw = (ROOT / v / f"{name}.txt").read_text()
    system, _, user = raw.partition("\n---\n")
    return Template(system).safe_substitute(**vars).strip(), Template(user).safe_substitute(**vars).strip(), v
