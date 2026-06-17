"""
ConcordFS checkpoint saver for LangGraph.

Implements LangGraph's BaseCheckpointSaver using ConcordFS's atomic
filesystem commit protocol (write-fsync-rename-dir_fsync).  Drop-in
replacement for SqliteSaver or InMemorySaver:

    with ConcordFSCheckpointSaver("/mnt/concord/checkpoints") as saver:
        graph = workflow.compile(checkpointer=saver)

All coordination state is stored as individual JSON files in a structured
directory tree, providing the inspectability and durability guarantees
described in the ConcordFS storage contract (C1-C3).
"""

from __future__ import annotations

import json
import os
import shutil
from contextlib import AbstractContextManager, AbstractAsyncContextManager
from pathlib import Path
from types import TracebackType
from typing import Any, Iterator, Optional, Sequence

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
    WRITES_IDX_MAP,
)
from langgraph.checkpoint.serde.base import SerializerProtocol

from .fsops import atomic_write_bytes, _fsync_dir


class ConcordFSCheckpointSaver(
    BaseCheckpointSaver[int],
    AbstractContextManager,
    AbstractAsyncContextManager,
):
    """Filesystem-backed checkpoint saver using ConcordFS commit protocol.

    Directory layout::

        <base_dir>/<thread_id>/<checkpoint_ns>/
            checkpoints/<checkpoint_id>.json
            blobs/<channel>_<version>.bin
            writes/<checkpoint_id>/<task_id>_<idx>.json
    """

    base_dir: Path

    def __init__(
        self,
        base_dir: str | Path,
        *,
        serde: Optional[SerializerProtocol] = None,
    ) -> None:
        super().__init__(serde=serde)
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # -- context manager --------------------------------------------------

    def __enter__(self) -> ConcordFSCheckpointSaver:
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    async def __aenter__(self) -> ConcordFSCheckpointSaver:
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass

    # -- helpers -----------------------------------------------------------

    def _thread_dir(self, thread_id: str, checkpoint_ns: str = "") -> Path:
        ns = checkpoint_ns or "__default__"
        return self.base_dir / thread_id / ns

    def _ckpt_path(self, thread_id: str, checkpoint_ns: str, checkpoint_id: str) -> Path:
        d = self._thread_dir(thread_id, checkpoint_ns) / "checkpoints"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{checkpoint_id}.json"

    def _blob_path(self, thread_id: str, checkpoint_ns: str, channel: str, version: Any) -> Path:
        d = self._thread_dir(thread_id, checkpoint_ns) / "blobs"
        d.mkdir(parents=True, exist_ok=True)
        safe_channel = channel.replace("/", "_").replace("\\", "_")
        return d / f"{safe_channel}_{version}.bin"

    def _writes_dir(self, thread_id: str, checkpoint_ns: str, checkpoint_id: str) -> Path:
        d = self._thread_dir(thread_id, checkpoint_ns) / "writes" / checkpoint_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _atomic_write(self, path: Path, type_tag: str, data: bytes) -> None:
        """Store a typed blob: 2-line file (type_tag\\nbase64_data)."""
        import base64
        payload = f"{type_tag}\n".encode() + base64.b64encode(data)
        atomic_write_bytes(path, payload)

    def _atomic_read(self, path: Path) -> tuple[str, bytes]:
        """Read a typed blob written by _atomic_write."""
        import base64
        raw = path.read_bytes()
        newline = raw.index(b"\n")
        type_tag = raw[:newline].decode()
        data = base64.b64decode(raw[newline + 1:])
        return type_tag, data

    # -- BaseCheckpointSaver interface ------------------------------------

    def get_tuple(self, config: "RunnableConfig") -> Optional[CheckpointTuple]:
        thread_id: str = config["configurable"]["thread_id"]
        checkpoint_ns: str = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)

        if not checkpoint_id:
            # Get latest checkpoint
            ckpt_dir = self._thread_dir(thread_id, checkpoint_ns) / "checkpoints"
            if not ckpt_dir.exists():
                return None
            files = sorted(ckpt_dir.glob("*.json"), key=lambda p: p.stem, reverse=True)
            if not files:
                return None
            checkpoint_id = files[0].stem

        path = self._ckpt_path(thread_id, checkpoint_ns, checkpoint_id)
        if not path.exists():
            return None

        with open(path) as f:
            saved = json.load(f)

        checkpoint_data: tuple[str, bytes] = (saved["checkpoint_type"], bytes.fromhex(saved["checkpoint_data"]))
        metadata_data: tuple[str, bytes] = (saved["metadata_type"], bytes.fromhex(saved["metadata_data"]))
        parent_checkpoint_id: Optional[str] = saved.get("parent_checkpoint_id")

        checkpoint_: Checkpoint = self.serde.loads_typed(checkpoint_data)

        # Load channel blobs
        channel_values: dict[str, Any] = {}
        for k, v in checkpoint_.get("channel_versions", {}).items():
            blob_path = self._blob_path(thread_id, checkpoint_ns, k, v)
            if blob_path.exists():
                typed = self._atomic_read(blob_path)
                if typed[0] != "empty":
                    channel_values[k] = self.serde.loads_typed(typed)

        # Load pending writes
        writes_dir = self._writes_dir(thread_id, checkpoint_ns, checkpoint_id)
        pending_writes = []
        if writes_dir.exists():
            for wf in sorted(writes_dir.glob("*.json")):
                with open(wf) as f:
                    w = json.load(f)
                pending_writes.append((
                    w["task_id"],
                    w["channel"],
                    self.serde.loads_typed((w["value_type"], bytes.fromhex(w["value_data"]))),
                ))

        parent_config = None
        if parent_checkpoint_id:
            parent_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": parent_checkpoint_id,
                }
            }

        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                }
            },
            checkpoint={**checkpoint_, "channel_values": channel_values},
            metadata=self.serde.loads_typed(metadata_data),
            pending_writes=pending_writes,
            parent_config=parent_config,
        )

    def put(
        self,
        config: "RunnableConfig",
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> "RunnableConfig":
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")

        c = checkpoint.copy()
        values: dict[str, Any] = c.pop("channel_values", {})

        # Store channel blobs atomically
        for k, v in new_versions.items():
            blob_path = self._blob_path(thread_id, checkpoint_ns, k, v)
            if k in values:
                typed = self.serde.dumps_typed(values[k])
                self._atomic_write(blob_path, typed[0], typed[1])
            else:
                self._atomic_write(blob_path, "empty", b"")

        # Serialize checkpoint and metadata
        ckpt_typed = self.serde.dumps_typed(c)
        meta_typed = self.serde.dumps_typed(
            get_checkpoint_metadata(config, metadata)
        )

        # Store checkpoint atomically
        saved = {
            "checkpoint_type": ckpt_typed[0],
            "checkpoint_data": ckpt_typed[1].hex(),
            "metadata_type": meta_typed[0],
            "metadata_data": meta_typed[1].hex(),
            "parent_checkpoint_id": parent_checkpoint_id,
        }

        path = self._ckpt_path(thread_id, checkpoint_ns, checkpoint["id"])
        atomic_write_bytes(path, json.dumps(saved).encode())

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(
        self,
        config: "RunnableConfig",
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]

        writes_dir = self._writes_dir(thread_id, checkpoint_ns, checkpoint_id)

        for idx, (channel, value) in enumerate(writes):
            write_idx = WRITES_IDX_MAP.get(channel, idx)

            # Skip if already exists (idempotent)
            write_path = writes_dir / f"{task_id}_{write_idx}.json"
            if write_idx >= 0 and write_path.exists():
                continue

            typed = self.serde.dumps_typed(value)
            w = {
                "task_id": task_id,
                "channel": channel,
                "value_type": typed[0],
                "value_data": typed[1].hex(),
                "task_path": task_path,
            }
            atomic_write_bytes(write_path, json.dumps(w).encode())

    def list(
        self,
        config: "RunnableConfig | None",
        *,
        filter: "dict[str, Any] | None" = None,
        before: "RunnableConfig | None" = None,
        limit: "int | None" = None,
    ) -> Iterator[CheckpointTuple]:
        if config is None:
            thread_ids = [
                d.name for d in self.base_dir.iterdir() if d.is_dir()
            ]
        else:
            thread_ids = [config["configurable"]["thread_id"]]

        config_checkpoint_ns = (
            config["configurable"].get("checkpoint_ns") if config else None
        )

        count = 0
        for thread_id in thread_ids:
            thread_dir = self.base_dir / thread_id
            if not thread_dir.exists():
                continue

            for ns_dir in sorted(thread_dir.iterdir()):
                if not ns_dir.is_dir():
                    continue
                checkpoint_ns = ns_dir.name
                if checkpoint_ns == "__default__":
                    checkpoint_ns = ""

                if config_checkpoint_ns is not None and checkpoint_ns != config_checkpoint_ns:
                    continue

                ckpt_dir = ns_dir / "checkpoints"
                if not ckpt_dir.exists():
                    continue

                for ckpt_file in sorted(ckpt_dir.glob("*.json"), key=lambda p: p.stem, reverse=True):
                    checkpoint_id = ckpt_file.stem

                    if before:
                        before_id = get_checkpoint_id(before)
                        if before_id and checkpoint_id >= before_id:
                            continue

                    item_config = {
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": checkpoint_id,
                        }
                    }
                    tup = self.get_tuple(item_config)
                    if tup is None:
                        continue

                    if filter:
                        meta = tup.metadata or {}
                        if not all(meta.get(k) == v for k, v in filter.items()):
                            continue

                    yield tup
                    count += 1
                    if limit and count >= limit:
                        return

    def delete_thread(self, thread_id: str) -> None:
        thread_dir = self.base_dir / thread_id
        if thread_dir.exists():
            shutil.rmtree(thread_dir)

    def get_next_version(self, current: Optional[int], channel: "ChannelProtocol") -> int:
        if current is None:
            return 1
        return current + 1
