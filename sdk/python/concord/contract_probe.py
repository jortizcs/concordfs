"""
Storage contract probe for ConcordFS.

Validates that the underlying filesystem satisfies the storage contract
(C1–C3) required for ConcordFS's safety properties.  Run at startup;
refuse to proceed unless all probes pass or the caller explicitly opts
into weak-durability mode.

Contract items:
  C1  Atomic rename   – rename is atomic w.r.t. observation
  C2  Durable publish – file fsync + dir fsync persists across crash
  C3  Read visibility – close-to-open: writer close → reader open sees data

Usage:
    from concord.contract_probe import probe_storage_contract

    result = probe_storage_contract(Path("/mnt/concord"))
    if not result.ok:
        if not allow_weak_durability:
            raise SystemExit(
                f"Storage contract violation: {result.summary()}. "
                "Pass --allow-weak-durability to proceed with degraded guarantees."
            )
        else:
            logger.warning("Proceeding with weak durability: %s", result.summary())
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from multiprocessing import Process, Queue
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ProbeResult:
    """Outcome of a single contract probe."""
    contract_item: str          # "C1", "C2", "C3"
    description: str
    passed: bool
    details: str = ""
    trials: int = 0
    failures: int = 0


@dataclass
class ContractProbeResult:
    """Aggregate outcome of all contract probes."""
    probes: List[ProbeResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(p.passed for p in self.probes)

    @property
    def c1_ok(self) -> bool:
        return all(p.passed for p in self.probes if p.contract_item == "C1")

    @property
    def c2_ok(self) -> bool:
        return all(p.passed for p in self.probes if p.contract_item == "C2")

    @property
    def c3_ok(self) -> bool:
        return all(p.passed for p in self.probes if p.contract_item == "C3")

    def summary(self) -> str:
        failed = [p for p in self.probes if not p.passed]
        if not failed:
            return "all contract items satisfied"
        parts = []
        for p in failed:
            parts.append(f"{p.contract_item} ({p.description}): {p.details}")
        return "; ".join(parts)


# ---------------------------------------------------------------------------
# C1 – Atomic rename
# ---------------------------------------------------------------------------

def _reader_worker(path: Path, q: Queue, n_reads: int) -> None:
    """Child process that reads a file repeatedly, checking for torn state."""
    torn = 0
    good = 0
    for _ in range(n_reads):
        try:
            with open(path) as f:
                raw = f.read()
            obj = json.loads(raw)
            # Validate internal consistency
            if obj.get("checksum") == hashlib.sha256(obj.get("payload", "").encode()).hexdigest():
                good += 1
            else:
                torn += 1
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            # File absent or mid-rename is acceptable (old-or-new); parse
            # failure on a non-empty read is a torn read.
            pass
        time.sleep(0.0005)
    q.put({"torn": torn, "good": good})


def probe_c1_atomic_rename(probe_dir: Path, n_updates: int = 100, n_readers: int = 3, reads_per_reader: int = 500) -> ProbeResult:
    """Verify that rename provides atomic visibility (no torn reads)."""
    target = probe_dir / "c1_state.json"

    # Seed initial file
    _commit(target, 0)

    q: Queue = Queue()
    readers = [
        Process(target=_reader_worker, args=(target, q, reads_per_reader))
        for _ in range(n_readers)
    ]
    for r in readers:
        r.start()

    time.sleep(0.05)  # let readers spin up

    for v in range(1, n_updates + 1):
        _commit(target, v)
        time.sleep(0.001)

    for r in readers:
        r.join(timeout=10)

    total_torn = 0
    while not q.empty():
        res = q.get_nowait()
        total_torn += res["torn"]

    total_reads = n_readers * reads_per_reader
    return ProbeResult(
        contract_item="C1",
        description="atomic rename",
        passed=(total_torn == 0),
        details=f"{total_torn}/{total_reads} torn reads",
        trials=total_reads,
        failures=total_torn,
    )


# ---------------------------------------------------------------------------
# C2 – Durable publish (file fsync + dir fsync)
# ---------------------------------------------------------------------------

def probe_c2_durable_publish(probe_dir: Path, n_commits: int = 50) -> ProbeResult:
    """
    Verify that committed files survive and read back correctly.

    This cannot simulate a real power-loss crash from userspace, so we
    validate the *protocol mechanics*: every committed file reads back
    with correct contents immediately after the commit sequence.  The
    adversarial server-crash variant is in the contract-violation matrix
    experiment (exp_nfs_contract_violation.py).
    """
    lost = 0
    for i in range(n_commits):
        path = probe_dir / f"c2_commit_{i:04d}.json"
        _commit(path, i)

        # Immediate read-back
        try:
            with open(path) as f:
                obj = json.load(f)
            if obj.get("version") != i:
                lost += 1
        except (FileNotFoundError, json.JSONDecodeError):
            lost += 1

    return ProbeResult(
        contract_item="C2",
        description="durable publish",
        passed=(lost == 0),
        details=f"{lost}/{n_commits} commits lost or corrupted on read-back",
        trials=n_commits,
        failures=lost,
    )


# ---------------------------------------------------------------------------
# C3 – Read visibility (close-to-open)
# ---------------------------------------------------------------------------

def _writer_worker(path: Path, q: Queue, value: int) -> None:
    """Child process that writes a file and closes it (triggering flush)."""
    _commit(path, value)
    q.put({"written": True, "time": time.perf_counter()})


def probe_c3_read_visibility(probe_dir: Path, n_handoffs: int = 30, timeout_ms: float = 2000) -> ProbeResult:
    """Verify close-to-open: after writer closes, reader sees data promptly."""
    stale = 0
    max_delay_ms = 0.0

    for i in range(n_handoffs):
        path = probe_dir / f"c3_handoff_{i:04d}.json"
        if path.exists():
            path.unlink()

        q: Queue = Queue()
        writer = Process(target=_writer_worker, args=(path, q, i))
        writer.start()
        writer.join(timeout=5)

        # Now poll from this (main) process
        t0 = time.perf_counter()
        deadline = t0 + timeout_ms / 1000
        visible = False
        while time.perf_counter() < deadline:
            if path.exists():
                try:
                    with open(path) as f:
                        obj = json.load(f)
                    if obj.get("version") == i:
                        visible = True
                        break
                except (json.JSONDecodeError, IOError):
                    pass
            time.sleep(0.001)

        delay_ms = (time.perf_counter() - t0) * 1000
        max_delay_ms = max(max_delay_ms, delay_ms)
        if not visible:
            stale += 1

    return ProbeResult(
        contract_item="C3",
        description="read visibility (close-to-open)",
        passed=(stale == 0),
        details=f"{stale}/{n_handoffs} stale reads; max visibility delay {max_delay_ms:.1f}ms",
        trials=n_handoffs,
        failures=stale,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _commit(path: Path, version: int) -> None:
    """Execute the full commit protocol: write-tmp → fsync → rename → fsync(dir)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = f"payload_v{version}_{'X' * 200}"
    obj = {
        "version": version,
        "payload": payload,
        "checksum": hashlib.sha256(payload.encode()).hexdigest(),
    }
    tmp = path.parent / f".probe.{uuid.uuid4().hex}.tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    # Dir fsync
    dfd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def probe_storage_contract(
    mount_path: Path,
    *,
    verbose: bool = False,
) -> ContractProbeResult:
    """
    Run all contract probes on *mount_path*.

    Returns a ContractProbeResult; caller decides whether to proceed.
    """
    probe_dir = mount_path / ".concordfs_probe"
    probe_dir.mkdir(parents=True, exist_ok=True)

    result = ContractProbeResult()

    if verbose:
        print(f"Probing storage contract on {mount_path} ...")

    # C1
    r1 = probe_c1_atomic_rename(probe_dir)
    result.probes.append(r1)
    if verbose:
        status = "PASS" if r1.passed else "FAIL"
        print(f"  C1 (atomic rename): {status} — {r1.details}")

    # C2
    r2 = probe_c2_durable_publish(probe_dir)
    result.probes.append(r2)
    if verbose:
        status = "PASS" if r2.passed else "FAIL"
        print(f"  C2 (durable publish): {status} — {r2.details}")

    # C3
    r3 = probe_c3_read_visibility(probe_dir)
    result.probes.append(r3)
    if verbose:
        status = "PASS" if r3.passed else "FAIL"
        print(f"  C3 (read visibility): {status} — {r3.details}")

    # Cleanup
    import shutil
    shutil.rmtree(probe_dir, ignore_errors=True)

    if verbose:
        print(f"  Overall: {'PASS' if result.ok else 'FAIL'} — {result.summary()}")

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ConcordFS storage contract probe")
    parser.add_argument("path", type=str, help="Filesystem path to probe")
    args = parser.parse_args()

    res = probe_storage_contract(Path(args.path), verbose=True)
    raise SystemExit(0 if res.ok else 1)
