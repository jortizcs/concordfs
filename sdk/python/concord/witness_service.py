"""Unix-socket service that keeps the witness signing key out of clients."""
from __future__ import annotations

import argparse
import json
import os
import socket
import stat
import struct
from pathlib import Path
from typing import Any, Mapping

from .witness import WitnessLedger, WitnessSigner


MAX_REQUEST_BYTES = 1024 * 1024


def _peer_identity(connection: socket.socket) -> tuple[int | None, int, int]:
    """Return pid, uid, gid when the platform exposes Unix peer credentials."""
    if hasattr(socket, "SO_PEERCRED"):
        raw = connection.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
        )
        return struct.unpack("3i", raw)
    if hasattr(connection, "getpeereid"):
        uid, gid = connection.getpeereid()  # type: ignore[attr-defined]
        return None, uid, gid
    return None, os.getuid(), os.getgid()


class WitnessService:
    """Serialize signed append requests through a protected Unix socket."""

    def __init__(
        self,
        socket_path: Path,
        ledger: WitnessLedger,
        *,
        actor_by_uid: Mapping[int, str] | None = None,
    ):
        self.socket_path = socket_path
        self.ledger = ledger
        self.actor_by_uid = dict(actor_by_uid or {})
        self._server: socket.socket | None = None

    def serve_forever(self) -> None:
        self._serve(max_connections=None)

    def serve_once(self) -> None:
        """Serve one request, primarily for supervised one-shot integrations."""
        self._serve(max_connections=1)

    def _serve(self, *, max_connections: int | None) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.socket_path.exists():
            if not stat.S_ISSOCK(self.socket_path.stat().st_mode):
                raise RuntimeError("refusing to replace a non-socket witness path")
            self.socket_path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server = server
        try:
            server.bind(str(self.socket_path))
            os.chmod(self.socket_path, 0o600)
            server.listen(16)
            handled = 0
            while True:
                connection, _ = server.accept()
                with connection:
                    self._handle(connection)
                handled += 1
                if max_connections is not None and handled >= max_connections:
                    break
        finally:
            server.close()
            self._server = None
            if self.socket_path.exists():
                self.socket_path.unlink()

    def close(self) -> None:
        if self._server is not None:
            self._server.close()

    def _handle(self, connection: socket.socket) -> None:
        try:
            request = self._read_request(connection)
            pid, uid, gid = _peer_identity(connection)
            if self.actor_by_uid and uid not in self.actor_by_uid:
                raise PermissionError(f"uid {uid} is not authorized to witness events")
            actor = self.actor_by_uid.get(uid, str(request.pop("actor")))
            process_id = (
                f"pid:{pid}:uid:{uid}:gid:{gid}"
                if pid is not None
                else f"uid:{uid}:gid:{gid}"
            )
            event = self.ledger.append(
                **request,
                actor=actor,
                process_id=process_id,
            )
            response: dict[str, Any] = {"ok": True, "event": event.to_dict()}
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        connection.sendall(
            json.dumps(response, sort_keys=True, separators=(",", ":")).encode()
            + b"\n"
        )

    @staticmethod
    def _read_request(connection: socket.socket) -> dict[str, Any]:
        data = bytearray()
        while len(data) <= MAX_REQUEST_BYTES:
            chunk = connection.recv(min(65536, MAX_REQUEST_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if b"\n" in chunk:
                break
        if len(data) > MAX_REQUEST_BYTES:
            raise ValueError("witness request exceeds size limit")
        line, separator, remainder = bytes(data).partition(b"\n")
        if not separator or remainder:
            raise ValueError("witness request must contain exactly one JSON line")
        request = json.loads(line)
        if not isinstance(request, dict):
            raise ValueError("witness request must be a JSON object")
        request.pop("process_id", None)
        return request


class WitnessClient:
    """Submit one event to an isolated witness service."""

    def __init__(self, socket_path: Path):
        self.socket_path = socket_path

    def append(self, **request: Any) -> dict[str, Any]:
        encoded = (
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
            + b"\n"
        )
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ValueError("witness request exceeds size limit")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.connect(str(self.socket_path))
            connection.sendall(encoded)
            response = bytearray()
            while b"\n" not in response:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                response.extend(chunk)
        value = json.loads(bytes(response).splitlines()[0])
        if not value.get("ok"):
            raise RuntimeError(value.get("error", "witness service rejected event"))
        return dict(value["event"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument(
        "--public-key-out",
        type=Path,
        help="raw Ed25519 public key output (default: KEY.pub)",
    )
    parser.add_argument(
        "--actor",
        action="append",
        default=[],
        metavar="UID=NAME",
        help="authorize a Unix uid and assign its witnessed actor name",
    )
    arguments = parser.parse_args()
    if not arguments.actor:
        parser.error("at least one --actor UID=NAME authorization is required")
    if arguments.key.exists():
        signer = WitnessSigner.load_private_key(arguments.key)
    else:
        signer = WitnessSigner.generate()
        signer.save_private_key(arguments.key)
    public_key_path = arguments.public_key_out or Path(
        str(arguments.key) + ".pub"
    )
    signer.save_public_key(public_key_path)
    actors: dict[int, str] = {}
    for assignment in arguments.actor:
        uid, separator, name = assignment.partition("=")
        if not separator or not name:
            parser.error("--actor must use UID=NAME")
        actors[int(uid)] = name
    service = WitnessService(
        arguments.socket,
        WitnessLedger(arguments.ledger, signer),
        actor_by_uid=actors,
    )
    service.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
