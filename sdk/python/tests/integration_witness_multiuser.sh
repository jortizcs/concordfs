#!/usr/bin/env bash
set -euo pipefail

# Linux/root-only deployment qualification for the documented three-user
# witness arrangement. Intended for CI; it does not run on developer machines.

if [ "$(id -u)" -ne 0 ] || [ "$(uname -s)" != "Linux" ]; then
  echo "SKIP: requires Linux root"
  exit 0
fi

root="$(mktemp -d /tmp/concord-witness-users.XXXXXX)"
trap 'test -n "${service_pid:-}" && kill "$service_pid" 2>/dev/null || true; rm -rf "$root"' EXIT

groupadd -f concord-witness-clients
group_id="$(getent group concord-witness-clients | cut -d: -f3)"
for account in concord-wrapper concord-veritas concord-scorer concord-witness; do
  id "$account" >/dev/null 2>&1 || useradd --system --no-create-home "$account"
done
usermod -a -G concord-witness-clients concord-wrapper
usermod -a -G concord-witness-clients concord-veritas
usermod -a -G concord-witness-clients concord-scorer

wrapper_uid="$(id -u concord-wrapper)"
veritas_uid="$(id -u concord-veritas)"
scorer_uid="$(id -u concord-scorer)"

chown concord-witness:concord-witness-clients "$root"
chmod 0750 "$root"
install -d -o concord-witness -g concord-witness "$root/private" "$root/ledger" "$root/cas"
install -d -o concord-witness -g concord-witness-clients -m 2750 "$root/socket"
install -d -o concord-witness -g concord-witness -m 0700 "$root/external-anchor"

runuser -u concord-witness -g concord-witness-clients -- python -m concord.witness_service \
  --socket "$root/socket/witness.sock" \
  --socket-gid "$group_id" \
  --ledger "$root/ledger/events.jsonl" \
  --key "$root/private/witness.ed25519" \
  --public-key-out "$root/witness.pub" \
  --artifact-root "$root/cas" \
  --anchor "$root/external-anchor/head.json" \
  --actor "$wrapper_uid=request-wrapper" \
  --actor "$veritas_uid=veritas" \
  --actor "$scorer_uid=independent-scorer" &
service_pid=$!

for _ in $(seq 1 100); do
  [ -S "$root/socket/witness.sock" ] && break
  sleep 0.05
done
test -S "$root/socket/witness.sock"
test "$(stat -c %a "$root/socket/witness.sock")" = "660"

SOCKET="$root/socket/witness.sock" runuser -u concord-wrapper -- python - <<'PY'
import os
from pathlib import Path
from concord.witness_service import WitnessClient
WitnessClient(Path(os.environ["SOCKET"])).append_artifacts(
    run_id="deployment",
    attempt=1,
    event_type="artifact_committed",
    actor="forged",
    correlation_id="wrapper",
    artifacts={"wrapper_probe": b"wrapper"},
)
PY

SOCKET="$root/socket/witness.sock" runuser -u concord-veritas -- python - <<'PY'
import os
from pathlib import Path
from concord.witness_service import WitnessClient
WitnessClient(Path(os.environ["SOCKET"])).append_artifacts(
    run_id="deployment",
    attempt=1,
    event_type="feedback_published",
    actor="forged",
    correlation_id="veritas",
    artifacts={"feedback": b"veritas"},
)
PY

SOCKET="$root/socket/witness.sock" runuser -u concord-scorer -- python - <<'PY'
import os
from pathlib import Path
from concord.witness_service import WitnessClient
client = WitnessClient(Path(os.environ["SOCKET"]))
client.append_artifacts(
    run_id="deployment",
    attempt=1,
    event_type="artifact_committed",
    actor="forged",
    correlation_id="scorer",
    artifacts={"scorer_probe": b"scorer"},
)
client.seal()
PY

kill "$service_pid"
wait "$service_pid" || true
service_pid=""

ROOT="$root" python - <<'PY'
import json
import os
from pathlib import Path
from concord.witness import WitnessVerifier
root = Path(os.environ["ROOT"])
report = WitnessVerifier((root / "witness.pub").read_bytes()).verify(
    root / "ledger/events.jsonl",
    artifact_root=root / "cas",
    anchor_path=root / "external-anchor/head.json",
    require_anchor=True,
)
assert report.valid, report.errors
assert [event.actor for event in report.events] == [
    "request-wrapper", "veritas", "independent-scorer"
]
assert len({event.process_id.split(":uid:")[1].split(":")[0] for event in report.events}) == 3
print("three-user witness deployment qualified")
PY
