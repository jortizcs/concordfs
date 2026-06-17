"""
Filesystem commit utilities for Concord.

These helpers implement the "write + fsync + atomic rename (+ directory fsync)"
protocol that ConcordFS relies on for durable, crash-consistent commit points.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Union, Optional


def _fsync_dir(dir_path: Path) -> None:
    """
    Best-effort directory fsync to durably persist directory entries.

    On some platforms/filesystems this may be a no-op or may require elevated
    privileges; we treat failures conservatively by surfacing exceptions.
    """
    fd = os.open(str(dir_path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes, *, fsync_dir: bool = True) -> None:
    """
    Atomically write bytes to `path` using a temp file + rename.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".tmp-{path.name}.{os.getpid()}.{uuid.uuid4().hex}"

    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp, path)
    if fsync_dir:
        _fsync_dir(path.parent)


def atomic_write_text(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    fsync_dir: bool = True,
) -> None:
    atomic_write_bytes(path, text.encode(encoding), fsync_dir=fsync_dir)


def atomic_write_json(
    path: Path,
    obj: Any,
    *,
    indent: Optional[int] = 2,
    sort_keys: bool = False,
    encoding: str = "utf-8",
    fsync_dir: bool = True,
) -> None:
    atomic_write_text(
        path,
        json.dumps(obj, indent=indent, sort_keys=sort_keys),
        encoding=encoding,
        fsync_dir=fsync_dir,
    )
