"""Authenticated, replay-verifiable witness events for ConcordFS.

The witness ledger records what a trusted wrapper observed at execution
boundaries. It authenticates event order and artifact references. It does not
decide whether a scientific claim is correct.
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


SCHEMA_VERSION = "concord.witness/v1"
GENESIS_HASH = "0" * 64
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EVENT_TYPES = frozenset(
    {
        "feedback_published",
        "feedback_read",
        "prompt_assembled",
        "model_request_sent",
        "model_response_received",
        "receipt_submitted",
        "gate_decision",
        "artifact_committed",
        "scorer_completed",
    }
)
ROOT_EVENT_TYPES = frozenset(
    {"feedback_published", "prompt_assembled", "artifact_committed"}
)
ALLOWED_CAUSES = {
    "feedback_read": frozenset({"feedback_published"}),
    "prompt_assembled": frozenset({"feedback_read", "model_response_received"}),
    "model_request_sent": frozenset({"prompt_assembled"}),
    "model_response_received": frozenset({"model_request_sent"}),
    "receipt_submitted": frozenset({"model_response_received"}),
    "gate_decision": frozenset({"receipt_submitted"}),
    "artifact_committed": frozenset(
        {"model_response_received", "receipt_submitted"}
    ),
    "scorer_completed": frozenset({"gate_decision"}),
}
REQUIRED_ARTIFACTS = {
    "feedback_published": frozenset({"feedback"}),
    "feedback_read": frozenset({"feedback"}),
    "prompt_assembled": frozenset({"prompt"}),
    "model_request_sent": frozenset({"request"}),
    "model_response_received": frozenset({"response"}),
    "receipt_submitted": frozenset({"receipt"}),
    "gate_decision": frozenset({"decision"}),
    "artifact_committed": frozenset(),
    "scorer_completed": frozenset({"score_report"}),
}


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class WitnessEvent:
    schema_version: str
    event_id: str
    run_id: str
    attempt: int
    sequence: int
    event_type: str
    actor: str
    process_id: str
    correlation_id: str
    causation_id: str | None
    artifact_hashes: dict[str, str]
    metadata: dict[str, Any]
    previous_event_hash: str
    timestamp_ns: int
    key_id: str
    event_hash: str
    signature: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WitnessEvent":
        return cls(
            schema_version=str(value["schema_version"]),
            event_id=str(value["event_id"]),
            run_id=str(value["run_id"]),
            attempt=int(value["attempt"]),
            sequence=int(value["sequence"]),
            event_type=str(value["event_type"]),
            actor=str(value["actor"]),
            process_id=str(value["process_id"]),
            correlation_id=str(value["correlation_id"]),
            causation_id=(
                str(value["causation_id"])
                if value.get("causation_id") is not None
                else None
            ),
            artifact_hashes={
                str(name): str(digest).lower()
                for name, digest in dict(value["artifact_hashes"]).items()
            },
            metadata=dict(value.get("metadata", {})),
            previous_event_hash=str(value["previous_event_hash"]).lower(),
            timestamp_ns=int(value["timestamp_ns"]),
            key_id=str(value["key_id"]),
            event_hash=str(value["event_hash"]).lower(),
            signature=str(value["signature"]),
        )

    def signing_body(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("event_hash")
        value.pop("signature")
        return value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationReport:
    valid: bool
    events: tuple[WitnessEvent, ...]
    errors: tuple[str, ...]

    def require_valid(self) -> tuple[WitnessEvent, ...]:
        if not self.valid:
            raise WitnessIntegrityError("; ".join(self.errors))
        return self.events


class WitnessIntegrityError(RuntimeError):
    """Raised when the ledger cannot support authenticated replay."""


class WitnessSigner:
    """Ed25519 signer held by the isolated witness process."""

    def __init__(self, private_key: Ed25519PrivateKey):
        self._private_key = private_key

    @classmethod
    def generate(cls) -> "WitnessSigner":
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_private_bytes(cls, private_key: bytes) -> "WitnessSigner":
        return cls(Ed25519PrivateKey.from_private_bytes(private_key))

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self._private_key.public_key()

    @property
    def key_id(self) -> str:
        return _hash_bytes(self.public_bytes())[:16]

    def private_bytes(self) -> bytes:
        return self._private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def public_bytes(self) -> bytes:
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def save_private_key(self, path: Path) -> None:
        """Create a mode-0600 raw private-key file without overwriting one."""
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            key = self.private_bytes()
            view = memoryview(key)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_dir(path.parent)

    @classmethod
    def load_private_key(cls, path: Path) -> "WitnessSigner":
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            raise PermissionError("witness private key must not be group/world accessible")
        return cls.from_private_bytes(path.read_bytes())

    def sign(self, event_hash: str) -> str:
        signature = self._private_key.sign(bytes.fromhex(event_hash))
        return base64.b64encode(signature).decode("ascii")


class WitnessVerifier:
    """Verify signatures, ordering, causation, and referenced CAS artifacts."""

    def __init__(self, public_key: Ed25519PublicKey | bytes):
        if isinstance(public_key, bytes):
            public_key = Ed25519PublicKey.from_public_bytes(public_key)
        self.public_key = public_key
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.key_id = _hash_bytes(public_bytes)[:16]

    def verify(
        self, ledger_path: Path, *, artifact_root: Path | None = None
    ) -> VerificationReport:
        errors: list[str] = []
        events: list[WitnessEvent] = []
        if not ledger_path.exists():
            return VerificationReport(True, (), ())
        raw = ledger_path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            errors.append("ledger is truncated or lacks a durable line terminator")
        for line_number, raw_line in enumerate(raw.splitlines(), start=1):
            try:
                decoded = json.loads(raw_line)
                events.append(WitnessEvent.from_dict(decoded))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"line {line_number} is not a valid witness event: {exc}")
        errors.extend(self._verify_events(events, artifact_root=artifact_root))
        return VerificationReport(not errors, tuple(events), tuple(errors))

    def _verify_events(
        self,
        events: Iterable[WitnessEvent],
        *,
        artifact_root: Path | None,
    ) -> list[str]:
        errors: list[str] = []
        by_id: dict[str, WitnessEvent] = {}
        seen_hashes: set[str] = set()
        previous_hash = GENESIS_HASH
        for expected_sequence, event in enumerate(events, start=1):
            prefix = f"event {event.event_id}"
            if event.schema_version != SCHEMA_VERSION:
                errors.append(f"{prefix} has unsupported schema")
            if event.sequence != expected_sequence:
                errors.append(
                    f"{prefix} has sequence {event.sequence}, expected "
                    f"{expected_sequence}"
                )
            if event.previous_event_hash != previous_hash:
                errors.append(f"{prefix} breaks the previous-event hash chain")
            if event.event_id in by_id:
                errors.append(f"{prefix} replays an existing event id")
            if event.event_hash in seen_hashes:
                errors.append(f"{prefix} replays an existing event hash")
            if event.key_id != self.key_id:
                errors.append(f"{prefix} was signed by an unexpected key")
            calculated_hash = _hash_bytes(_canonical_json(event.signing_body()))
            if calculated_hash != event.event_hash:
                errors.append(f"{prefix} has an invalid event hash")
            else:
                try:
                    self.public_key.verify(
                        base64.b64decode(event.signature, validate=True),
                        bytes.fromhex(event.event_hash),
                    )
                except (InvalidSignature, ValueError):
                    errors.append(f"{prefix} has an invalid signature")
            errors.extend(self._verify_schema(event, by_id))
            if artifact_root is not None:
                errors.extend(self._verify_artifacts(event, artifact_root))
            by_id[event.event_id] = event
            seen_hashes.add(event.event_hash)
            previous_hash = event.event_hash
        return errors

    @staticmethod
    def _verify_schema(
        event: WitnessEvent, by_id: Mapping[str, WitnessEvent]
    ) -> list[str]:
        errors: list[str] = []
        prefix = f"event {event.event_id}"
        if event.event_type not in EVENT_TYPES:
            errors.append(f"{prefix} has an unknown event type")
            return errors
        if event.attempt < 1 or event.sequence < 1:
            errors.append(f"{prefix} has a non-positive attempt or sequence")
        for field_name, field_value in (
            ("event_id", event.event_id),
            ("run_id", event.run_id),
            ("actor", event.actor),
            ("process_id", event.process_id),
            ("correlation_id", event.correlation_id),
        ):
            if not field_value:
                errors.append(f"{prefix} has an empty {field_name}")
        if not SHA256_RE.fullmatch(event.previous_event_hash):
            errors.append(f"{prefix} has an invalid previous-event hash")
        if not SHA256_RE.fullmatch(event.event_hash):
            errors.append(f"{prefix} has an invalid event hash encoding")
        for name, digest in event.artifact_hashes.items():
            if not name or not SHA256_RE.fullmatch(digest):
                errors.append(f"{prefix} has an invalid artifact reference")
        missing = REQUIRED_ARTIFACTS[event.event_type] - event.artifact_hashes.keys()
        if missing:
            errors.append(
                f"{prefix} lacks required artifact roles {sorted(missing)}"
            )
        if event.event_type == "artifact_committed" and not event.artifact_hashes:
            errors.append(f"{prefix} commits no artifacts")
        if event.event_type == "model_response_received" and not str(
            event.metadata.get("generation_id", "")
        ):
            errors.append(f"{prefix} lacks a provider generation id")
        included = event.metadata.get("included_feedback_hashes")
        if event.event_type == "prompt_assembled" and included is not None:
            if not isinstance(included, list) or any(
                not isinstance(item, str) or not SHA256_RE.fullmatch(item)
                for item in included
            ):
                errors.append(f"{prefix} has invalid included feedback hashes")

        if event.causation_id is None:
            if event.event_type not in ROOT_EVENT_TYPES:
                errors.append(f"{prefix} lacks a required causal parent")
            return errors
        parent = by_id.get(event.causation_id)
        if parent is None:
            errors.append(f"{prefix} refers to a missing or future causal parent")
            return errors
        allowed = ALLOWED_CAUSES.get(event.event_type, frozenset())
        if parent.event_type not in allowed:
            errors.append(
                f"{prefix} has disallowed parent type {parent.event_type}"
            )
        if (
            parent.run_id != event.run_id
            or parent.attempt != event.attempt
            or parent.correlation_id != event.correlation_id
        ):
            errors.append(f"{prefix} crosses run, attempt, or correlation boundaries")
        errors.extend(WitnessVerifier._verify_parent_link(event, parent))
        return errors

    @staticmethod
    def _verify_parent_link(
        event: WitnessEvent, parent: WitnessEvent
    ) -> list[str]:
        prefix = f"event {event.event_id}"
        if event.event_type == "feedback_read":
            if event.artifact_hashes.get("feedback") != parent.artifact_hashes.get(
                "feedback"
            ):
                return [f"{prefix} reads a different feedback artifact"]
        elif event.event_type == "prompt_assembled":
            if parent.event_type == "feedback_read":
                feedback = parent.artifact_hashes.get("feedback")
                included = event.metadata.get("included_feedback_hashes", [])
                if feedback not in included:
                    return [
                        f"{prefix} does not bind its causal feedback into the prompt"
                    ]
        else:
            links = {
                "model_request_sent": ("prompt_hash", "prompt"),
                "model_response_received": ("request_hash", "request"),
                "receipt_submitted": ("response_hash", "response"),
                "gate_decision": ("receipt_hash", "receipt"),
                "scorer_completed": ("decision_hash", "decision"),
            }
            link = links.get(event.event_type)
            if link is not None:
                metadata_name, parent_role = link
                expected = parent.artifact_hashes.get(parent_role)
                if event.metadata.get(metadata_name) != expected:
                    return [
                        f"{prefix} does not bind the causal {parent_role} artifact"
                    ]
        return []

    @staticmethod
    def _verify_artifacts(event: WitnessEvent, artifact_root: Path) -> list[str]:
        errors: list[str] = []
        for role, digest in event.artifact_hashes.items():
            path = artifact_root / "sha256" / digest
            if not path.is_file():
                errors.append(
                    f"event {event.event_id} references missing {role} artifact"
                )
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != digest:
                errors.append(
                    f"event {event.event_id} references corrupt {role} artifact"
                )
        return errors


class WitnessLedger:
    """Single-writer component for durable signed event publication.

    The signing key and ledger path must be inaccessible to the observed agent.
    A filesystem lock serializes writers. Existing history is fully verified
    before every append, so corruption causes a fail-closed refusal.
    """

    def __init__(self, path: Path, signer: WitnessSigner):
        self.path = path
        self.signer = signer
        self.verifier = WitnessVerifier(signer.public_key)
        self.lock_path = path.with_suffix(path.suffix + ".lock")

    def append(
        self,
        *,
        run_id: str,
        attempt: int,
        event_type: str,
        actor: str,
        process_id: str,
        correlation_id: str,
        artifact_hashes: Mapping[str, str],
        causation_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        event_id: str | None = None,
        timestamp_ns: int | None = None,
    ) -> WitnessEvent:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_descriptor = os.open(
            self.lock_path, os.O_CREAT | os.O_RDWR, 0o600
        )
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            prior = self.verifier.verify(self.path).require_valid()
            previous_hash = prior[-1].event_hash if prior else GENESIS_HASH
            sequence = len(prior) + 1
            unsigned = {
                "schema_version": SCHEMA_VERSION,
                "event_id": event_id or str(uuid.uuid4()),
                "run_id": run_id,
                "attempt": attempt,
                "sequence": sequence,
                "event_type": event_type,
                "actor": actor,
                "process_id": process_id,
                "correlation_id": correlation_id,
                "causation_id": causation_id,
                "artifact_hashes": {
                    str(name): str(digest).lower()
                    for name, digest in artifact_hashes.items()
                },
                "metadata": dict(metadata or {}),
                "previous_event_hash": previous_hash,
                "timestamp_ns": timestamp_ns or time.time_ns(),
                "key_id": self.signer.key_id,
            }
            event_hash = _hash_bytes(_canonical_json(unsigned))
            event = WitnessEvent(
                **unsigned,
                event_hash=event_hash,
                signature=self.signer.sign(event_hash),
            )
            candidate_errors = self.verifier._verify_events(
                (*prior, event), artifact_root=None
            )
            if candidate_errors:
                raise ValueError("; ".join(candidate_errors))
            line = _canonical_json(event.to_dict()) + b"\n"
            new_file = not self.path.exists()
            descriptor = os.open(
                self.path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600
            )
            try:
                view = memoryview(line)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            if new_file:
                _fsync_dir(self.path.parent)
            return event
        finally:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            os.close(lock_descriptor)
