"""Resolve and atomically publish immutable corpus index generations."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

ACTIVE_INDEX_FILE = "active_index.json"


def read_index_bytes(path: Path) -> bytes:
    """Retry transient Windows sharing violations while a marker is published."""
    for attempt in range(5):
        try:
            return path.read_bytes()
        except PermissionError:
            if (
                os.name != "nt"
                or attempt == 4
            ):
                raise
            time.sleep(0.01 * (2 ** attempt))


def resolve_index_dir(index_root: Path) -> Path:
    """Resolve the active generation, or the legacy root-level index."""
    manifest_path = index_root / ACTIVE_INDEX_FILE
    if not manifest_path.exists():
        return index_root

    manifest = json.loads(read_index_bytes(manifest_path).decode("utf-8"))
    generation = manifest.get("generation")
    if not isinstance(generation, str):
        raise ValueError(f"{manifest_path}: missing generation path")

    relative = Path(generation)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{manifest_path}: generation path must be relative")

    resolved = index_root / relative
    if not resolved.is_dir():
        raise FileNotFoundError(f"{manifest_path}: index generation not found: {resolved}")
    return resolved


def index_marker(index_root: Path) -> Path:
    """Return the file whose contents identify the currently published index."""
    active = index_root / ACTIVE_INDEX_FILE
    return active if active.is_file() else index_root / "index_meta.json"


def publish_index(index_root: Path, generation_dir: Path) -> None:
    """Atomically switch readers to a fully written index generation."""
    relative = generation_dir.resolve().relative_to(index_root.resolve())
    manifest = {"generation": relative.as_posix()}
    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=index_root,
            prefix=".active-index-",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(manifest, temp_file)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        for attempt in range(5):
            try:
                os.replace(temp_path, index_root / ACTIVE_INDEX_FILE)
                break
            except PermissionError as exc:
                if (
                    os.name != "nt"
                    or getattr(exc, "winerror", None) not in {5, 32, 33}
                    or attempt == 4
                ):
                    raise
                time.sleep(0.01 * (2 ** attempt))
    except OSError:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
