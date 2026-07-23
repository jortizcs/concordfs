from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest

from concord.witness import (
    WitnessIntegrityError,
    WitnessLedger,
    WitnessSigner,
    WitnessVerifier,
)
from concord.witness_service import WitnessClient, WitnessService


def _put(root: Path, content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()
    path = root / "sha256" / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return digest


def _append_feedback_chain(
    ledger: WitnessLedger, artifacts: Path
) -> tuple[str, str, str, str, str]:
    feedback_hash = _put(artifacts, b"recompute stale input")
    prompt_hash = _put(artifacts, b"task plus feedback")
    request_hash = _put(artifacts, b'{"messages":["task plus feedback"]}')
    response_hash = _put(artifacts, b"recomputed")
    receipt_hash = _put(artifacts, b'{"attempt":2,"accuracy":0.91}')
    common = {
        "run_id": "run-1",
        "attempt": 2,
        "actor": "request-wrapper",
        "process_id": "wrapper:123",
        "correlation_id": "generation-2",
    }
    published = ledger.append(
        **common,
        event_type="feedback_published",
        artifact_hashes={"feedback": feedback_hash},
    )
    read = ledger.append(
        **common,
        event_type="feedback_read",
        artifact_hashes={"feedback": feedback_hash},
        causation_id=published.event_id,
    )
    prompt = ledger.append(
        **common,
        event_type="prompt_assembled",
        artifact_hashes={"prompt": prompt_hash},
        causation_id=read.event_id,
        metadata={"included_feedback_hashes": [feedback_hash]},
    )
    request = ledger.append(
        **common,
        event_type="model_request_sent",
        artifact_hashes={"request": request_hash},
        causation_id=prompt.event_id,
        metadata={"prompt_hash": prompt_hash},
    )
    response = ledger.append(
        **common,
        event_type="model_response_received",
        artifact_hashes={"response": response_hash},
        causation_id=request.event_id,
        metadata={"generation_id": "gen-123", "request_hash": request_hash},
    )
    ledger.append(
        **common,
        event_type="receipt_submitted",
        artifact_hashes={"receipt": receipt_hash},
        causation_id=response.event_id,
        metadata={"response_hash": response_hash},
    )
    return (
        feedback_hash,
        prompt_hash,
        request_hash,
        response_hash,
        receipt_hash,
    )


def test_signed_chain_verifies_with_artifacts(tmp_path: Path):
    signer = WitnessSigner.generate()
    ledger_path = tmp_path / "witness" / "events.jsonl"
    artifacts = tmp_path / "cas"
    _append_feedback_chain(WitnessLedger(ledger_path, signer), artifacts)

    report = WitnessVerifier(signer.public_bytes()).verify(
        ledger_path, artifact_root=artifacts
    )
    assert report.valid, report.errors
    assert [event.sequence for event in report.events] == list(range(1, 7))
    assert report.events[-1].event_type == "receipt_submitted"


def test_tampering_fails_signature_and_hash_checks(tmp_path: Path):
    signer = WitnessSigner.generate()
    ledger_path = tmp_path / "events.jsonl"
    artifacts = tmp_path / "cas"
    _append_feedback_chain(WitnessLedger(ledger_path, signer), artifacts)
    records = [
        json.loads(line) for line in ledger_path.read_text().splitlines()
    ]
    records[1]["actor"] = "agent"
    ledger_path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n"
    )

    report = WitnessVerifier(signer.public_bytes()).verify(ledger_path)
    assert not report.valid
    assert any("invalid event hash" in error for error in report.errors)


def test_truncation_is_rejected(tmp_path: Path):
    signer = WitnessSigner.generate()
    ledger_path = tmp_path / "events.jsonl"
    feedback = hashlib.sha256(b"feedback").hexdigest()
    WitnessLedger(ledger_path, signer).append(
        run_id="run",
        attempt=1,
        event_type="feedback_published",
        actor="veritas",
        process_id="veritas:1",
        correlation_id="attempt-1",
        artifact_hashes={"feedback": feedback},
    )
    ledger_path.write_bytes(ledger_path.read_bytes()[:-7])

    report = WitnessVerifier(signer.public_bytes()).verify(ledger_path)
    assert not report.valid
    assert any("truncated" in error for error in report.errors)


def test_missing_artifact_is_rejected(tmp_path: Path):
    signer = WitnessSigner.generate()
    ledger_path = tmp_path / "events.jsonl"
    missing = hashlib.sha256(b"missing").hexdigest()
    WitnessLedger(ledger_path, signer).append(
        run_id="run",
        attempt=1,
        event_type="feedback_published",
        actor="veritas",
        process_id="veritas:1",
        correlation_id="attempt-1",
        artifact_hashes={"feedback": missing},
    )

    report = WitnessVerifier(signer.public_bytes()).verify(
        ledger_path, artifact_root=tmp_path / "cas"
    )
    assert not report.valid
    assert any("missing feedback artifact" in error for error in report.errors)


def test_invalid_causal_order_is_refused_before_append(tmp_path: Path):
    signer = WitnessSigner.generate()
    ledger = WitnessLedger(tmp_path / "events.jsonl", signer)
    response = hashlib.sha256(b"response").hexdigest()
    with pytest.raises(ValueError, match="lacks a required causal parent"):
        ledger.append(
            run_id="run",
            attempt=1,
            event_type="model_response_received",
            actor="wrapper",
            process_id="wrapper:1",
            correlation_id="generation-1",
            artifact_hashes={"response": response},
            metadata={"generation_id": "gen-1"},
        )


def test_prompt_must_bind_the_feedback_it_causally_follows(tmp_path: Path):
    signer = WitnessSigner.generate()
    ledger = WitnessLedger(tmp_path / "events.jsonl", signer)
    feedback = hashlib.sha256(b"feedback").hexdigest()
    other_feedback = hashlib.sha256(b"other").hexdigest()
    prompt = hashlib.sha256(b"prompt").hexdigest()
    published = ledger.append(
        run_id="run",
        attempt=1,
        event_type="feedback_published",
        actor="veritas",
        process_id="veritas:1",
        correlation_id="generation-1",
        artifact_hashes={"feedback": feedback},
    )
    read = ledger.append(
        run_id="run",
        attempt=1,
        event_type="feedback_read",
        actor="wrapper",
        process_id="wrapper:1",
        correlation_id="generation-1",
        artifact_hashes={"feedback": feedback},
        causation_id=published.event_id,
    )
    with pytest.raises(ValueError, match="does not bind its causal feedback"):
        ledger.append(
            run_id="run",
            attempt=1,
            event_type="prompt_assembled",
            actor="wrapper",
            process_id="wrapper:1",
            correlation_id="generation-1",
            artifact_hashes={"prompt": prompt},
            causation_id=read.event_id,
            metadata={"included_feedback_hashes": [other_feedback]},
        )


def test_existing_corruption_blocks_future_appends(tmp_path: Path):
    signer = WitnessSigner.generate()
    ledger_path = tmp_path / "events.jsonl"
    ledger = WitnessLedger(ledger_path, signer)
    feedback = hashlib.sha256(b"feedback").hexdigest()
    ledger.append(
        run_id="run",
        attempt=1,
        event_type="feedback_published",
        actor="veritas",
        process_id="veritas:1",
        correlation_id="attempt-1",
        artifact_hashes={"feedback": feedback},
    )
    ledger_path.write_bytes(ledger_path.read_bytes()[:-1])

    with pytest.raises(WitnessIntegrityError, match="truncated"):
        ledger.append(
            run_id="run",
            attempt=2,
            event_type="feedback_published",
            actor="veritas",
            process_id="veritas:1",
            correlation_id="attempt-2",
            artifact_hashes={"feedback": feedback},
        )


def test_unexpected_signing_key_is_rejected(tmp_path: Path):
    signer = WitnessSigner.generate()
    other = WitnessSigner.generate()
    ledger_path = tmp_path / "events.jsonl"
    feedback = hashlib.sha256(b"feedback").hexdigest()
    WitnessLedger(ledger_path, signer).append(
        run_id="run",
        attempt=1,
        event_type="feedback_published",
        actor="veritas",
        process_id="veritas:1",
        correlation_id="attempt-1",
        artifact_hashes={"feedback": feedback},
    )

    report = WitnessVerifier(other.public_bytes()).verify(ledger_path)
    assert not report.valid
    assert any("unexpected key" in error for error in report.errors)


def test_private_key_permissions_are_enforced(tmp_path: Path):
    path = tmp_path / "witness.key"
    signer = WitnessSigner.generate()
    signer.save_private_key(path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert (
        WitnessSigner.load_private_key(path).public_bytes()
        == signer.public_bytes()
    )
    path.chmod(0o644)
    with pytest.raises(PermissionError, match="group/world"):
        WitnessSigner.load_private_key(path)


def test_service_derives_process_identity_and_keeps_key_server_side(
    tmp_path: Path,
):
    try:
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    except PermissionError:
        pytest.skip("sandbox forbids Unix sockets")
    else:
        probe.close()
    signer = WitnessSigner.generate()
    ledger_path = tmp_path / "events.jsonl"
    socket_path = tmp_path / "witness.sock"
    service = WitnessService(
        socket_path,
        WitnessLedger(ledger_path, signer),
        actor_by_uid={os.getuid(): "request-wrapper"},
    )
    thread = threading.Thread(target=service.serve_once)
    thread.start()
    for _ in range(100):
        if socket_path.exists():
            break
        time.sleep(0.01)
    feedback = hashlib.sha256(b"feedback").hexdigest()
    event = WitnessClient(socket_path).append(
        run_id="run",
        attempt=1,
        event_type="feedback_published",
        actor="untrusted-client-value",
        process_id="forged:999",
        correlation_id="attempt-1",
        artifact_hashes={"feedback": feedback},
    )
    assert event["actor"] == "request-wrapper"
    assert event["process_id"] != "forged:999"
    assert WitnessVerifier(signer.public_bytes()).verify(ledger_path).valid
    thread.join(timeout=2)
    assert not thread.is_alive()
