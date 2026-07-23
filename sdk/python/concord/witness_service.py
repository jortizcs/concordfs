"""Unix-socket service that keeps the witness signing key out of clients."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import socket
import stat
import struct
from pathlib import Path
from typing import Any, Mapping

from .witness import WitnessLedger, WitnessSigner


MAX_REQUEST_BYTES = 64 * 1024 * 1024


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
        socket_mode: int = 0o660,
        socket_gid: int | None = None,
        anchor_path: Path | None = None,
        anchor_actor: str = "independent-scorer",
        artifact_root: Path | None = None,
    ):
        self.socket_path = socket_path
        self.ledger = ledger
        self.actor_by_uid = dict(actor_by_uid or {})
        self.socket_mode = socket_mode
        self.socket_gid = socket_gid
        self.anchor_path = anchor_path
        self.anchor_actor = anchor_actor
        self.artifact_root = artifact_root
        self._server: socket.socket | None = None

    def serve_forever(self) -> None:
        self._serve(max_connections=None)

    def serve_once(self) -> None:
        """Serve one request, primarily for supervised one-shot integrations."""
        self._serve(max_connections=1)

    def _serve(self, *, max_connections: int | None) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o770)
        os.chmod(
            self.socket_path.parent,
            # Clients need search permission on the directory and read/write
            # permission on the socket, but must not be able to unlink or
            # replace the service endpoint.
            0o2750 if self.socket_gid is not None else 0o700,
        )
        if (
            self.socket_gid is not None
            and self.socket_path.parent.stat().st_gid != self.socket_gid
        ):
            os.chown(self.socket_path.parent, -1, self.socket_gid)
        if self.socket_path.exists():
            if not stat.S_ISSOCK(self.socket_path.stat().st_mode):
                raise RuntimeError("refusing to replace a non-socket witness path")
            self.socket_path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server = server
        try:
            server.bind(str(self.socket_path))
            if (
                self.socket_gid is not None
                and self.socket_path.stat().st_gid != self.socket_gid
            ):
                os.chown(self.socket_path, -1, self.socket_gid)
            os.chmod(self.socket_path, self.socket_mode)
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
            actor = self.actor_by_uid.get(uid, str(request.pop("actor", "")))
            process_id = (
                f"pid:{pid}:uid:{uid}:gid:{gid}"
                if pid is not None
                else f"uid:{uid}:gid:{gid}"
            )
            operation = request.pop("operation", "append")
            if operation == "seal":
                if self.anchor_path is None:
                    raise RuntimeError("witness service has no external anchor path")
                if actor != self.anchor_actor:
                    raise PermissionError(
                        f"actor {actor!r} is not authorized to seal the ledger"
                    )
                anchor = self.ledger.write_anchor(self.anchor_path)
                response = {"ok": True, "anchor": anchor.to_dict()}
            elif operation == "put_artifact":
                encoded = request.pop("content", None)
                stored = self._store_artifacts({"content": encoded})
                response = {"ok": True, "digest": stored["content"]}
            elif operation == "get_artifact":
                if self.artifact_root is None:
                    raise RuntimeError(
                        "witness service has no protected artifact root"
                    )
                digest = str(request.pop("digest", ""))
                if (
                    len(digest) != 64
                    or any(char not in "0123456789abcdef" for char in digest)
                ):
                    raise ValueError("invalid artifact digest")
                path = self.artifact_root / "sha256" / digest
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != digest:
                    raise RuntimeError("witness artifact is corrupt")
                response = {
                    "ok": True,
                    "content": base64.b64encode(content).decode("ascii"),
                }
            elif operation == "append":
                inline_artifacts = request.pop("artifacts", None)
                if inline_artifacts is not None:
                    if self.artifact_root is None:
                        raise RuntimeError(
                            "witness service has no protected artifact root"
                        )
                    request["artifact_hashes"] = self._store_artifacts(
                        inline_artifacts
                    )
                event = self.ledger.append(
                    **request,
                    actor=actor,
                    process_id=process_id,
                )
                response = {"ok": True, "event": event.to_dict()}
            else:
                raise ValueError(f"unknown witness operation: {operation}")
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        connection.sendall(
            json.dumps(response, sort_keys=True, separators=(",", ":")).encode()
            + b"\n"
        )

    def _store_artifacts(
        self, artifacts: Mapping[str, Any]
    ) -> dict[str, str]:
        if not isinstance(artifacts, Mapping) or not artifacts:
            raise ValueError("artifacts must be a non-empty role mapping")
        assert self.artifact_root is not None
        hashes: dict[str, str] = {}
        for role, encoded in artifacts.items():
            if not isinstance(role, str) or not role:
                raise ValueError("artifact role must be a non-empty string")
            try:
                content = base64.b64decode(str(encoded), validate=True)
            except ValueError as exc:
                raise ValueError(f"artifact {role} is not valid base64") from exc
            digest = hashlib.sha256(content).hexdigest()
            path = self.artifact_root / "sha256" / digest
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if path.exists():
                if path.read_bytes() != content:
                    raise RuntimeError(f"CAS collision or corruption for {digest}")
            else:
                temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
                descriptor = os.open(
                    temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )
                try:
                    view = memoryview(content)
                    while view:
                        written = os.write(descriptor, view)
                        view = view[written:]
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                os.replace(temporary, path)
            hashes[role] = digest
        return hashes

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
        value = self._request(request)
        return dict(value["event"])

    def append_artifacts(
        self, *, artifacts: Mapping[str, bytes | str], **request: Any
    ) -> dict[str, Any]:
        request["artifacts"] = {
            role: base64.b64encode(
                content.encode("utf-8") if isinstance(content, str) else content
            ).decode("ascii")
            for role, content in artifacts.items()
        }
        value = self._request(request)
        return dict(value["event"])

    def seal(self) -> dict[str, Any]:
        value = self._request({"operation": "seal"})
        return dict(value["anchor"])

    def put(
        self,
        content: bytes | str,
        content_type: str = "application/octet-stream",
    ) -> str:
        del content_type  # content type is carried by the consuming event role
        raw = content.encode("utf-8") if isinstance(content, str) else content
        value = self._request(
            {
                "operation": "put_artifact",
                "content": base64.b64encode(raw).decode("ascii"),
            }
        )
        return str(value["digest"])

    def get(self, hash_value: str) -> bytes | None:
        try:
            value = self._request(
                {"operation": "get_artifact", "digest": hash_value}
            )
        except RuntimeError as exc:
            if "No such file" in str(exc):
                return None
            raise
        return base64.b64decode(value["content"], validate=True)

    def _request(self, request: Mapping[str, Any]) -> dict[str, Any]:
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
        return dict(value)


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
    parser.add_argument(
        "--socket-gid",
        type=int,
        help="shared Unix group allowed to connect to the mode-0660 socket",
    )
    parser.add_argument(
        "--anchor",
        type=Path,
        required=True,
        help="externally retained terminal ledger-head commitment",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        required=True,
        help="service-owned CAS root for witnessed artifact bytes",
    )
    parser.add_argument(
        "--anchor-actor",
        default="independent-scorer",
        help="only this mapped actor may seal the terminal ledger head",
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
        socket_gid=arguments.socket_gid,
        anchor_path=arguments.anchor,
        anchor_actor=arguments.anchor_actor,
        artifact_root=arguments.artifact_root,
    )
    service.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
